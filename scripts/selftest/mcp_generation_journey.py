"""Generate this batch's assets through MCP, then use the public fixture reviewer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from scripts.selftest.bootstrap import Installation
from scripts.selftest.contracts import ApiSource, Contract, McpCallReceipt, OracleBinding
from scripts.selftest.generation_scopes import ProjectScope
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    integer_value,
    object_value,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import ROOT
from scripts.selftest.mcp_protocol_runner import ProtocolClient
from scripts.selftest.review_driver import FixtureReviewDriver, ReviewDriver
from scripts.selftest.review_fixture_driver import (
    ReviewedCase,
    ReviewedWorkflow,
)


class GeneratedAsset(Contract):
    scenario_id: str
    variant_key: str
    api_source: ApiSource
    design: JsonObject
    design_fingerprint: str
    compilation_fingerprint: str
    oracle_bindings: tuple[OracleBinding, ...]
    workflow: ReviewedWorkflow
    case: ReviewedCase
    calls: tuple[McpCallReceipt, ...]
    generated_at: datetime
    frozen_at: datetime


async def import_operation(
    client: ProtocolClient,
    *,
    installation: ProjectScope,
    scenario_id: str,
    operation: JsonObject,
    service_id: str,
    environment_id: str,
    output_dir: Path,
) -> JsonObject:
    preview = await client.call(
        "flowtest.preview_contract_import",
        {
            "request": {
                "project_id": str(installation.project_id),
                "source_kind": "operations",
                "operations": [operation],
                "service_id": service_id,
                "environment_id": environment_id,
                "persist": True,
            }
        },
        scenario_id=scenario_id,
        phase="contract_preview",
    )
    write_json(output_dir / "contract-preview.json", preview)
    items = [
        item
        for item in objects_value(preview["items"])
        if item["method"] == operation["method"] and item["path"] == operation["path"]
    ]
    if len(items) != 1 or items[0]["change"] != "added":
        raise HarnessError("SELFTEST_CONTRACT_NOT_NEW_FOR_BATCH")
    committed = await client.call(
        "flowtest.commit_contract_import",
        {
            "request": {
                "project_id": str(installation.project_id),
                "preview_id": preview["preview_id"],
                "preview_sha256": preview["source_sha256"],
                "selected_operations": [items[0]["import_key"]],
                "expected_current_versions": {},
                "service_id": service_id,
                "environment_id": environment_id,
            },
            "idempotency_key": f"{client.batch_key}:{scenario_id}:import",
        },
        scenario_id=scenario_id,
        phase="contract_commit",
    )
    write_json(output_dir / "contract-import.json", committed)
    if committed["applied_keys"] != [items[0]["import_key"]]:
        raise HarnessError("SELFTEST_CONTRACT_APPLIED_SET_MISMATCH")
    results = [
        item
        for item in objects_value(committed["results"])
        if item["import_key"] == items[0]["import_key"]
    ]
    if len(results) != 1 or results[0]["definition_id"] is None:
        raise HarnessError("SELFTEST_CONTRACT_MAPPING_MISSING")
    return results[0]


async def begin_context(
    client: ProtocolClient,
    *,
    installation: ProjectScope,
    scenario_id: str,
    environment_id: str,
    api_id: str,
    api_version: int,
    contract_fingerprint: str,
) -> JsonObject:
    context = await client.call(
        "flowtest.begin_test_context",
        {
            "project_id": str(installation.project_id),
            "name": f"{client.batch_key}:{scenario_id}",
            "objective": "本轮 MCP 生成并核验固定契约的原生测试资产",
            "target_environment_id": environment_id,
            "required_evidence": ["contract"],
            "contract_revisions": [
                {
                    "source_ref": f"api-definition://{api_id}/version/{api_version}",
                    "revision": contract_fingerprint,
                }
            ],
        },
        scenario_id=scenario_id,
        phase="context",
    )
    revision = object_value(context["revision"])
    return {
        "context_id": context["id"],
        "context_revision_id": revision["id"],
        "context_fingerprint": revision["fingerprint"],
    }


async def generate_canary(
    client: ProtocolClient,
    reviewer: PublicAPI,
    *,
    installation: Installation,
    scenario_id: str,
    expected_actual: int,
    output_dir: Path,
    review_driver: ReviewDriver | None = None,
) -> GeneratedAsset:
    generated_at = datetime.now(UTC)
    golden = object_value(
        object_value(
            read_json(ROOT / "selftest/packs/mcp-core-v1/golden-contracts/canaries.json")[
                "scenarios"
            ]
        )[scenario_id]
    )
    operation: JsonObject = {
        "name": f"{client.batch_key}_{scenario_id}",
        "method": "GET",
        "path": f"/selftest/{client.batch_key}/{scenario_id}/request",
        "responses": {
            "200": {
                "description": "受保护的合成响应契约",
                "content_type": "application/json",
                "schema": golden["schema"],
            }
        },
    }
    imported = await import_operation(
        client,
        installation=installation,
        scenario_id=scenario_id,
        operation=operation,
        service_id=str(installation.fixture_service_id),
        environment_id=str(installation.fixture_environment_id),
        output_dir=output_dir,
    )
    api_id, api_version = text_value(imported["definition_id"]), integer_value(imported["version"])
    inspection = await client.call(
        "flowtest.inspect_contract",
        {
            "project_id": str(installation.project_id),
            "api_definition_id": api_id,
            "version": api_version,
        },
        scenario_id=scenario_id,
        phase="contract_read",
    )
    inspected = objects_value(inspection["items"])
    if (
        len(inspected) != 1
        or inspected[0]["id"] != api_id
        or inspected[0]["version"] != api_version
    ):
        raise HarnessError("SELFTEST_CANARY_CONTRACT_VERSION_MISMATCH")
    write_json(output_dir / "contract-inspection.json", inspection)
    generated = await client.call(
        "flowtest.generate_test_design",
        {
            "project_id": str(installation.project_id),
            "api_definition_id": api_id,
            "api_version": api_version,
            "generation_policy": {
                "include_negative": False,
                "include_auth": False,
                "include_state": False,
                "include_data_constraints": False,
                "pairwise_enabled": False,
            },
        },
        scenario_id=scenario_id,
        phase="design",
    )
    design, origin = object_value(generated["design"]), object_value(generated["origin"])
    write_json(
        output_dir / "generated-design.json",
        {
            "design": design,
            "origin": origin,
            "fingerprint": generated["fingerprint"],
            "persisted": generated["persisted"],
        },
    )
    scenarios = [
        item for item in objects_value(design["scenarios"]) if item["kind"] == "happy_path"
    ]
    if generated["persisted"] is not False or len(scenarios) != 1:
        raise HarnessError("SELFTEST_GENERATED_DESIGN_NOT_READY")
    await client.call(
        "flowtest.analyze_test_coverage",
        {
            "project_id": str(installation.project_id),
            "api_definition_id": api_id,
            "api_version": api_version,
            "generation_policy": origin["generation_policy"],
        },
        scenario_id=scenario_id,
        phase="coverage",
    )
    context = await begin_context(
        client,
        installation=installation,
        scenario_id=scenario_id,
        environment_id=str(installation.fixture_environment_id),
        api_id=api_id,
        api_version=api_version,
        contract_fingerprint=text_value(origin["contract_fingerprint"]),
    )
    compilation = await client.call(
        "flowtest.compile_test_design",
        {
            "request": {
                "project_id": str(installation.project_id),
                "design": design,
                "design_fingerprint": generated["fingerprint"],
                "origin": origin,
                "scenario_ids": [scenarios[0]["id"]],
                "environment_id": str(installation.fixture_environment_id),
                "context_binding": context,
            }
        },
        scenario_id=scenario_id,
        phase="compilation",
    )
    if compilation["readiness"] != "ready":
        write_json(output_dir / "blocked-compilation.json", compilation)
        raise HarnessError("SELFTEST_DESIGN_COMPILATION_NOT_READY")
    write_json(output_dir / "design-compilation.json", compilation)
    compiled = objects_value(compilation["scenarios"])[0]
    executable = object_value(compiled["executable_payload"])
    spec = object_value(executable["spec"])
    bound_spec = {**spec, "name": f"{client.batch_key}:{scenario_id}:{spec['name']}"[:200]}
    write_json(
        output_dir / "metadata-bindings.json",
        {
            "kind": "batch_namespace",
            "original_workflow_name": spec["name"],
            "workflow_name": bound_spec["name"],
            "native_definition_changed": False,
        },
    )
    proposal = await client.call(
        "flowtest.propose_flow_draft",
        {
            "project_id": str(installation.project_id),
            "context_id": context["context_id"],
            "context_revision_id": context["context_revision_id"],
            "spec": bound_spec,
            "operation_mappings": executable["operation_mappings"],
            "operation_version_mappings": executable["operation_version_mappings"],
            "service_mappings": executable["service_mappings"],
            "source_ref": f"mcp://selftest/{client.batch_key}/{scenario_id}",
            "idempotency_key": f"{client.batch_key}:{scenario_id}:workflow",
            "dry_run": False,
        },
        scenario_id=scenario_id,
        phase="workflow_proposal",
    )
    flow = await (review_driver or FixtureReviewDriver()).flow(
        reviewer,
        project_id=str(installation.project_id),
        reviewer_id=str(installation.reviewer_id),
        proposal_id=text_value(proposal["change_set_id"]),
        expected_definition=object_value(executable["native_definition"]),
        expected_api_ids=(api_id,),
        output_dir=output_dir,
    )
    case = await propose_case(
        client,
        reviewer,
        installation,
        scenario_id,
        design,
        flow,
        output_dir,
        review_driver=review_driver,
    )
    bindings = tuple(
        OracleBinding(
            oracle_id=text_value(item["oracle_id"]),
            node_id=text_value(item["node_id"]),
            assertion_name="workflow_assertion",
            expression=text_value(item["normalized_expression"]),
            expected_value_digest=text_value(item["expected_value_fingerprint"]),
        )
        for item in objects_value(compiled["oracle_bindings"])
    )
    result = GeneratedAsset(
        scenario_id=scenario_id,
        variant_key="negative_assertion_canary"
        if expected_actual == 2
        else "positive_assertion_canary",
        api_source=ApiSource(
            project_id=installation.project_id,
            api_definition_id=UUID(api_id),
            api_version=api_version,
            contract_fingerprint=text_value(origin["contract_fingerprint"]),
        ),
        design=design,
        design_fingerprint=text_value(generated["fingerprint"]),
        compilation_fingerprint=text_value(compilation["compilation_fingerprint"]),
        oracle_bindings=bindings,
        workflow=flow,
        case=case,
        calls=tuple(item for item in client.receipts if item.scenario_id == scenario_id),
        generated_at=generated_at,
        frozen_at=datetime.now(UTC),
    )
    write_json(output_dir / "generated-asset.json", result)
    return result


async def propose_case(
    client: ProtocolClient,
    reviewer: PublicAPI,
    installation: Installation,
    scenario_id: str,
    design: JsonObject,
    workflow: ReviewedWorkflow,
    output_dir: Path,
    *,
    environment_id: str | None = None,
    review_driver: ReviewDriver | None = None,
) -> ReviewedCase:
    definition: JsonObject = {
        "workflow_id": workflow.workflow["id"],
        "workflow_version": workflow.version["version"],
        "environment_id": environment_id or str(installation.fixture_environment_id),
        "runtime_variables": {},
        "runtime_headers": {},
    }
    proposed = await client.call(
        "flowtest.propose_test_design",
        {
            "project_id": str(installation.project_id),
            "title": f"{client.batch_key}:{scenario_id}",
            "confidence": 1.0,
            "risk_level": "low",
            "design": design,
            "test_cases": [
                {
                    "name": f"{client.batch_key}:{scenario_id}",
                    "description": "本轮 MCP 编译发布流程的正式用例",
                    "definition": definition,
                }
            ],
            "idempotency_key": f"{client.batch_key}:{scenario_id}:case",
            "dry_run": False,
            "source_ref": f"mcp://selftest/{client.batch_key}/{scenario_id}",
        },
        scenario_id=scenario_id,
        phase="case_proposal",
    )
    return await (review_driver or FixtureReviewDriver()).case(
        reviewer,
        project_id=str(installation.project_id),
        reviewer_id=str(installation.reviewer_id),
        proposal_id=text_value(proposed["id"]),
        expected_definition=definition,
        output_dir=output_dir,
    )
