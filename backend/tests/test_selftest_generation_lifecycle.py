"""Characterize lifecycle adaptation against the application's real OpenAPI contract."""

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.bootstrap import Installation  # noqa: E402
from scripts.selftest.contracts import ApiSource  # noqa: E402
from scripts.selftest.generation_lifecycle import (  # noqa: E402
    ENVIRONMENTS_PATH,
    LOGIN_PATH,
    OperationGeneration,
    _context_and_plan,
    _generate_operations,
    _import_document,
    _purpose,
    bind_lifecycle_plan,
    combine_generated_designs,
    lifecycle_document,
)
from scripts.selftest.io import HarnessError  # noqa: E402
from scripts.selftest.mcp_protocol_runner import ProtocolClient  # noqa: E402

from app.domain.integration_plans import (  # noqa: E402
    IntegrationPlannerRequest,
    PlanActor,
    PlanTargetEnvironment,
    SelectedOperationEvidence,
    build_integration_plan,
    compile_integration_plan,
)
from app.domain.test_design import fingerprint_design  # noqa: E402
from app.domain.test_engineering import (  # noqa: E402
    GenerationPolicy,
    fingerprint_contract,
)
from app.domain.test_engineering import (  # noqa: E402
    TestEngineeringEngine as DesignGenerator,
)
from app.importers.contracts import ImportSourceType  # noqa: E402
from app.importers.openapi import parse_openapi  # noqa: E402
from app.main import app  # noqa: E402


def _installation() -> Installation:
    fields = (
        "organization_id",
        "project_id",
        "reviewer_id",
        "mcp_account_id",
        "target_project_id",
        "target_organization_id",
        "target_user_id",
        "fixture_environment_id",
        "target_environment_id",
        "fixture_service_id",
        "target_service_id",
    )
    return Installation.model_validate(
        {
            **{field: str(uuid4()) for field in fields},
            "binding_nonce": "b" * 32,
            "reviewer_email": "reviewer@example.test",
            "target_email": "actor@example.test",
        }
    )


def _generated_inputs(installation: Installation):
    original = app.openapi()
    subset = lifecycle_document(original, installation, "batch-one")
    imported = parse_openapi(subset, ImportSourceType.OPENAPI3)
    selected, generated = [], []
    order = {
        purpose: index
        for index, purpose in enumerate(("login", "create", "list", "patch", "delete"))
    }
    imported = sorted(
        imported,
        key=lambda item: order[
            _purpose({"method": item.request.method.value, "path": item.request.path})
        ],
    )
    for index, item in enumerate(imported):
        contract = item.canonical_contract
        assert contract is not None
        source = f"api-definition://{uuid4()}/version/1"
        contract = contract.model_copy(update={"source_ref": source, "revision": "1"})
        design = DesignGenerator().generate(
            contract=contract,
            policy=GenerationPolicy(
                max_scenarios=50, include_negative=False, include_auth=True, include_state=False
            ),
        )
        happy = next(item for item in design.scenarios if item.kind == "happy_path")
        oracles = [
            oracle
            for oracle in design.oracles
            if oracle.deterministic and not oracle.requires_review and happy.id in oracle.applies_to
        ]
        selected.append(
            SelectedOperationEvidence(
                operation_ref=contract.operation,
                service_ref="selftest_target",
                service_name="selftest_target",
                source_version=1,
                contract=contract,
                scenario=happy,
                oracles=oracles,
                credential_refs=["secret://HTTPBearer"] if contract.auth.required else [],
                evidence_refs=[source],
            )
        )
        generated.append(
            OperationGeneration(
                purpose=("login", "create", "list", "patch", "delete")[index],
                api_source=ApiSource(
                    project_id=installation.project_id,
                    api_definition_id=uuid4(),
                    api_version=1,
                    contract_fingerprint=fingerprint_contract(contract),
                ),
                operation_ref=contract.operation,
                design=design.model_dump(mode="json"),
                design_fingerprint=fingerprint_design(design),
                scenario_id=happy.id,
            )
        )
    return original, subset, selected, tuple(generated)


def test_real_openapi_subset_preserves_response_schemas_security_and_exact_namespace() -> None:
    installed = _installation()
    original, subset, _, _ = _generated_inputs(installed)
    bound = ENVIRONMENTS_PATH.replace("{project_id}", str(installed.target_project_id))
    for original_path, bound_path, method in (
        (LOGIN_PATH, LOGIN_PATH, "post"),
        (ENVIRONMENTS_PATH, bound, "post"),
        (ENVIRONMENTS_PATH, bound, "get"),
        (ENVIRONMENTS_PATH + "/{environment_id}", bound + "/{environment_id}", "patch"),
        (ENVIRONMENTS_PATH + "/{environment_id}", bound + "/{environment_id}", "delete"),
    ):
        actual = subset["paths"][bound_path][method]
        expected = original["paths"][original_path][method]
        assert actual["responses"] == expected["responses"]
        assert actual.get("security") == expected.get("security")
        assert all(parameter["name"] != "project_id" for parameter in actual["parameters"])
    assert "{{secret.SELFTEST_B_PASSWORD}}" in json.dumps(subset)
    assert lifecycle_document(original, installed, "batch-two")["paths"] == subset["paths"]


def test_generated_real_contract_oracles_survive_typed_plan_bindings_and_compile() -> None:
    installed = _installation()
    _, _, selected, _ = _generated_inputs(installed)
    plan = build_integration_plan(
        IntegrationPlannerRequest(
            context_revision_id=uuid4(),
            context_fingerprint="a" * 64,
            objective="Environment lifecycle",
            actors=[PlanActor(id="fixture", role="owner")],
            target_environment=PlanTargetEnvironment(
                key="target", source_ref=f"environment://{installed.target_environment_id}"
            ),
            selected_operations=selected,
        )
    )
    old_oracles = deepcopy(plan.oracles)

    bound = bind_lifecycle_plan(plan, installed, "batch-one")
    compilation = compile_integration_plan(bound)

    assert bound.oracles == old_oracles
    assert compilation.importable, [(item.code, item.message) for item in compilation.diagnostics]
    assert len([node for node in compilation.flow_spec.nodes if node.kind == "assert"]) == len(
        old_oracles
    )
    assert sum(oracle.kind == "schema" for oracle in old_oracles) >= 4
    paths = [binding for binding in bound.bindings if binding.target.location == "path"]
    assert len(paths) == 2
    assert all(binding.target.key == "environment_id" for binding in paths)
    assert all(binding.candidates[0].path == "body.id" for binding in paths)
    for operation in bound.operations:
        if operation.path == LOGIN_PATH:
            continue
        assert next(
            item.value for item in operation.request.headers if item.name == "X-Organization-ID"
        ) == str(installed.target_organization_id)


def test_design_composition_preserves_all_generated_scenarios_and_oracles() -> None:
    _, _, _, operations = _generated_inputs(_installation())
    combined, mapping = combine_generated_designs(operations)
    assert len(combined.oracles) == sum(len(item.design["oracles"]) for item in operations)
    assert len(combined.scenarios) == sum(len(item.design["scenarios"]) for item in operations)
    assert set(mapping) == {"login", "create", "list", "patch", "delete"}
    for item in operations:
        oracle_map = mapping[item.purpose]["oracles"]
        for source in item.design["oracles"]:
            emitted = next(
                oracle for oracle in combined.oracles if oracle.id == oracle_map[source["id"]]
            )
            assert emitted.expression == source["expression"]
            assert emitted.expected == source["expected"]


async def test_frozen_source_reads_use_real_mcp_result_shape_and_pinned_versions(
    tmp_path: Path,
) -> None:
    installed = _installation()
    _, _, _, generated = _generated_inputs(installed)
    operation = generated[0]
    api_id = str(operation.api_source.api_definition_id)
    calls: list[tuple[str, dict[str, Any]]] = []

    class DesignClient:
        async def call(self, name: str, arguments: dict[str, Any], **_: object) -> dict[str, Any]:
            calls.append((name, arguments))
            if name == "flowtest.inspect_contract":
                return {"items": [{"id": api_id, "version": 1}]}
            if name == "flowtest.generate_test_design":
                # The actual MCP read envelope deliberately has no `contract` field.
                return {
                    "design": operation.design,
                    "fingerprint": operation.design_fingerprint,
                    "origin": {
                        "api_definition_id": api_id,
                        "api_version": 1,
                        "contract_fingerprint": operation.api_source.contract_fingerprint,
                        "generation_policy": arguments["generation_policy"],
                    },
                    "persisted": False,
                }
            assert name == "flowtest.analyze_test_coverage"
            return operation.design["coverage"]

    result = await _generate_operations(
        cast(ProtocolClient, DesignClient()),
        installed,
        [{"definition_id": api_id, "version": 1, "method": "POST", "path": LOGIN_PATH}],
        tmp_path,
    )

    assert result[0].operation_ref == operation.operation_ref
    assert [name for name, _ in calls] == [
        "flowtest.inspect_contract",
        "flowtest.generate_test_design",
        "flowtest.analyze_test_coverage",
    ]
    assert calls[0][1]["version"] == 1
    assert calls[1][1]["api_version"] == calls[2][1]["api_version"] == 1


def _import_selection(change: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    collection = "/api/v1/projects/isolated-project/environments"
    specifications = [
        ("POST", LOGIN_PATH),
        ("POST", collection),
        ("GET", collection),
        ("PATCH", collection + "/{environment_id}"),
        ("DELETE", collection + "/{environment_id}"),
    ]
    paths: dict[str, Any] = {}
    items = []
    for index, (method, path) in enumerate(specifications):
        paths.setdefault(path, {})[method.lower()] = {}
        items.append(
            {
                "method": method,
                "path": path.replace("{environment_id}", "{{environment_id}}"),
                "import_key": f"selected-{index}",
                "change": change,
                "definition_id": str(uuid4()) if change != "added" else None,
                "version": 2,
            }
        )
    return {"paths": paths}, items


@pytest.mark.parametrize("change", ["unchanged", "changed", "deleted"])
async def test_second_round_source_preview_never_commits_existing_changes(
    change: str, tmp_path: Path
) -> None:
    document, items = _import_selection(change)
    called: list[str] = []

    class ImportClient:
        batch_key = "second-round"

        async def call(self, name: str, arguments: dict[str, Any], **_: object) -> dict[str, Any]:
            called.append(name)
            assert name == "flowtest.preview_contract_import"
            return {"items": items}

    client = cast(ProtocolClient, ImportClient())
    if change == "unchanged":
        result = await _import_document(client, _installation(), document, tmp_path)
        assert result == items
    else:
        with pytest.raises(HarnessError, match="IMPORT_REQUIRES_EXISTING_CHANGE"):
            await _import_document(client, _installation(), document, tmp_path)
    assert called == ["flowtest.preview_contract_import"]


@pytest.mark.parametrize("change", ["added", "unchanged"])
async def test_import_selects_only_the_five_document_operations_among_unselected_diffs(
    change: str, tmp_path: Path
) -> None:
    document, selected = _import_selection(change)
    foreign = [
        {
            "method": "GET",
            "path": "/selftest/older-batch/ST-MCP-025/request",
            "import_key": "unselected-canary",
            "change": "deleted",
            "definition_id": str(uuid4()),
            "version": 1,
        },
        {
            "method": "PUT",
            "path": LOGIN_PATH,
            "import_key": "wrong-method",
            "change": "changed",
            "definition_id": str(uuid4()),
            "version": 1,
        },
    ]
    preview = {
        "items": [*selected, *foreign],
        "preview_id": str(uuid4()),
        "source_sha256": "a" * 64,
    }
    commits: list[dict[str, Any]] = []

    class DiffClient:
        batch_key = "new-isolated-batch"

        async def call(self, name: str, arguments: dict[str, Any], **_: object) -> dict[str, Any]:
            if name == "flowtest.preview_contract_import":
                return preview
            assert name == "flowtest.commit_contract_import"
            commits.append(arguments)
            return {
                "applied_keys": [item["import_key"] for item in selected],
                "results": [
                    {**item, "definition_id": str(uuid4()), "version": 1} for item in selected
                ]
                + foreign,
            }

    result = await _import_document(
        cast(ProtocolClient, DiffClient()), _installation(), document, tmp_path
    )

    assert len(result) == 5
    assert {item["import_key"] for item in result} == {item["import_key"] for item in selected}
    assert len(commits) == int(change == "added")
    if commits:
        assert set(commits[0]["request"]["selected_operations"]) == {
            item["import_key"] for item in selected
        }
    saved = json.loads((tmp_path / "contract-preview.json").read_text())
    assert saved == preview


async def test_context_namespace_reaches_the_actual_compiler_name_without_changing_oracles() -> (
    None
):
    installed = _installation()
    _, _, selected, operations = _generated_inputs(installed)
    original = build_integration_plan(
        IntegrationPlannerRequest(
            context_revision_id=uuid4(),
            context_fingerprint="a" * 64,
            objective="Environment lifecycle",
            actors=[PlanActor(id="fixture", role="owner")],
            target_environment=PlanTargetEnvironment(
                key="target", source_ref=f"environment://{installed.target_environment_id}"
            ),
            selected_operations=selected,
        )
    )
    names: list[str] = []

    class ContextClient:
        def __init__(self, batch_key: str) -> None:
            self.batch_key = batch_key
            self.context_inputs: dict[str, Any] = {}

        async def call(self, name: str, arguments: dict[str, Any], **_: object) -> dict[str, Any]:
            if name == "flowtest.begin_test_context":
                self.context_inputs.update(arguments)
                return {
                    "id": str(uuid4()),
                    "revision": {
                        "id": str(original.context_revision_id),
                        "fingerprint": original.context_fingerprint,
                    },
                }
            assert name == "flowtest.plan_integration_test"
            return original.model_copy(
                update={"objective": self.context_inputs["objective"]}
            ).model_dump(mode="json")

    for batch in ("batch-first", "batch-second"):
        _, plan = await _context_and_plan(
            cast(ProtocolClient, ContextClient(batch)), installed, operations
        )
        compilation = compile_integration_plan(plan)
        assert compilation.importable, compilation.diagnostics
        assert compilation.flow_spec is not None
        assert compilation.flow_spec.name.startswith(batch + ":ST-MCP-023:")
        assert "真实 B 环境登录、创建、列表、更新和删除的原生生命周期" in plan.objective
        assert plan.oracles == original.oracles
        names.append(compilation.flow_spec.name)
    assert len(set(names)) == 2
