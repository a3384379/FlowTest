"""Generate the B environment lifecycle through the existing MCP integration compiler."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

from pydantic import JsonValue
from scripts.selftest.bootstrap import Installation
from scripts.selftest.contracts import (
    ApiSource,
    Contract,
    McpCallReceipt,
    OracleBinding,
    canonical_digest,
)
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    integer_value,
    object_value,
    objects_value,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import StackBinding
from scripts.selftest.mcp_generation_journey import propose_case
from scripts.selftest.mcp_protocol_runner import ProtocolClient
from scripts.selftest.review_driver import FixtureReviewDriver, ReviewDriver
from scripts.selftest.review_fixture_driver import ReviewedCase, ReviewedWorkflow

from app.domain.evidence import EvidenceRef
from app.domain.flow_spec import FlowSpec, flow_spec_to_workflow_definition
from app.domain.integration_plans import (
    IntegrationPlan,
    PlanBinding,
    PlanBindingCandidate,
    PlanBindingTarget,
    PlanRequestValue,
    seal_integration_plan,
)
from app.domain.test_design import (
    CoverageEntry,
    KnowledgeEdge,
    KnowledgeNode,
    OracleSpec,
    ScenarioCandidate,
    TestDesignDocument,
    fingerprint_design,
)

SCENARIO = "ST-MCP-023"
LOGIN_PATH = "/api/v1/auth/login"
ENVIRONMENTS_PATH = "/api/v1/projects/{project_id}/environments"
LIFECYCLE_OBJECTIVE = "真实 B 环境登录、创建、列表、更新和删除的原生生命周期"


class OperationGeneration(Contract):
    purpose: str
    api_source: ApiSource
    operation_ref: str
    design: JsonObject
    design_fingerprint: str
    scenario_id: str


class LifecycleAsset(Contract):
    scenario_id: str = SCENARIO
    variant_key: str = "environment_lifecycle"
    target_project_id: UUID
    operations: tuple[OperationGeneration, ...]
    source_document_digest: str
    bound_document_digest: str
    source_reused: bool
    context: JsonObject
    integration_plan: JsonObject
    combined_design: JsonObject
    combined_design_fingerprint: str
    design_composition: JsonObject
    compilation_fingerprint: str
    oracle_bindings: tuple[OracleBinding, ...]
    workflow: ReviewedWorkflow
    case: ReviewedCase
    calls: tuple[McpCallReceipt, ...]
    created_resource_name: str
    updated_resource_name: str
    generated_at: datetime
    frozen_at: datetime


def _component_references(value: object) -> set[str]:
    if isinstance(value, dict):
        references = {
            item
            for key, item in value.items()
            if key == "$ref" and isinstance(item, str) and item.startswith("#/components/")
        }
        return references | set().union(*(_component_references(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_component_references(item) for item in value))
    return set()


def _selected_components(document: JsonObject, paths: JsonObject) -> JsonObject:
    components = object_value(document.get("components", {}))
    selected: JsonObject = {}
    pending = _component_references(paths)
    # Security requirement names are not JSON references.
    schemes = object_value(components.get("securitySchemes", {}))
    if schemes:
        selected["securitySchemes"] = deepcopy(schemes)
    seen: set[str] = set()
    while pending:
        reference = pending.pop()
        if reference in seen:
            continue
        seen.add(reference)
        parts = reference.split("/")
        if len(parts) != 4:
            raise HarnessError("SELFTEST_OPENAPI_COMPONENT_REFERENCE_UNSUPPORTED")
        category, name = parts[2:]
        value = object_value(components.get(category, {})).get(name)
        if value is None:
            raise HarnessError("SELFTEST_OPENAPI_COMPONENT_MISSING")
        group = object_value(selected.get(category, {}))
        group[name] = deepcopy(value)
        selected[category] = group
        pending.update(_component_references(value) - seen)
    return selected


def lifecycle_document(
    document: JsonObject, installation: Installation, batch_key: str
) -> JsonObject:
    """Bind only the known disposable project; preserve response schemas and security."""
    paths = object_value(document["paths"])
    selected: JsonObject = {}
    specifications = (
        ("login", LOGIN_PATH, "post"),
        ("create", ENVIRONMENTS_PATH, "post"),
        ("list", ENVIRONMENTS_PATH, "get"),
        ("patch", ENVIRONMENTS_PATH + "/{environment_id}", "patch"),
        ("delete", ENVIRONMENTS_PATH + "/{environment_id}", "delete"),
    )
    for index, (purpose, path, method) in enumerate(specifications):
        path_item = object_value(paths[path])
        operation = deepcopy(object_value(path_item[method]))
        operation["operationId"] = f"selftest_lifecycle_{index}_{purpose}"
        operation["summary"] = f"selftest lifecycle {purpose}"
        parameters = [
            *objects_value(path_item.get("parameters", [])),
            *objects_value(operation.get("parameters", [])),
        ]
        operation["parameters"] = [
            item
            for item in parameters
            if not (item.get("in") == "path" and item.get("name") == "project_id")
        ]
        if purpose == "login":
            request = deepcopy(object_value(operation["requestBody"]))
            content = object_value(request["content"])
            media = object_value(content["application/json"])
            media["example"] = {
                "email": installation.target_email,
                "password": "{{secret.SELFTEST_B_PASSWORD}}",
            }
            content["application/json"] = media
            request["content"] = content
            operation["requestBody"] = request
        bound = path.replace("{project_id}", str(installation.target_project_id))
        entry = object_value(selected.get(bound, {}))
        entry[method] = operation
        selected[bound] = entry
    result: JsonObject = {
        "openapi": document["openapi"],
        "info": {"title": f"{batch_key} B environment lifecycle", "version": "1"},
        "paths": selected,
        "components": _selected_components(document, selected),
    }
    if "security" in document:
        result["security"] = deepcopy(document["security"])
    return result


async def _import_document(
    client: ProtocolClient, installation: Installation, document: JsonObject, output_dir: Path
) -> list[JsonObject]:
    preview = await client.call(
        "flowtest.preview_contract_import",
        {
            "request": {
                "project_id": str(installation.project_id),
                "source_kind": "document",
                "document_name": f"{client.batch_key}-lifecycle.openapi.json",
                "document_content": json.dumps(document, ensure_ascii=False),
                "source_type": "openapi3",
                "persist": True,
                "service_id": str(installation.target_service_id),
                "environment_id": str(installation.target_environment_id),
            }
        },
        scenario_id=SCENARIO,
        phase="contract_preview",
    )
    write_json(output_dir / "contract-preview.json", preview)
    items = _selected_import_items(document, objects_value(preview["items"]))
    if len(items) != 5 or any(item["change"] not in {"added", "unchanged"} for item in items):
        raise HarnessError("SELFTEST_LIFECYCLE_IMPORT_REQUIRES_EXISTING_CHANGE")
    if all(item["change"] == "unchanged" for item in items):
        if any(
            item["definition_id"] is None or integer_value(item["version"]) < 1 for item in items
        ):
            raise HarnessError("SELFTEST_LIFECYCLE_IMPORT_MAPPING_MISSING")
        write_json(
            output_dir / "contract-import.json",
            {
                "source_reused": True,
                "preview": preview,
                "results": cast(JsonValue, items),
            },
        )
        return items
    if any(item["change"] != "added" for item in items):
        raise HarnessError("SELFTEST_LIFECYCLE_IMPORT_MIXED_STATE")
    committed = await client.call(
        "flowtest.commit_contract_import",
        {
            "request": {
                "project_id": str(installation.project_id),
                "preview_id": preview["preview_id"],
                "preview_sha256": preview["source_sha256"],
                "selected_operations": [item["import_key"] for item in items],
                "expected_current_versions": {},
                "service_id": str(installation.target_service_id),
                "environment_id": str(installation.target_environment_id),
            },
            "idempotency_key": f"{client.batch_key}:{SCENARIO}:import",
        },
        scenario_id=SCENARIO,
        phase="contract_commit",
    )
    write_json(output_dir / "contract-import.json", committed)
    expected_keys = {text_value(item["import_key"]) for item in items}
    applied_keys = committed["applied_keys"]
    if not isinstance(applied_keys, list):
        raise HarnessError("SELFTEST_LIFECYCLE_IMPORT_APPLIED_SET_MISMATCH")
    if len(applied_keys) != 5 or {text_value(key) for key in applied_keys} != expected_keys:
        raise HarnessError("SELFTEST_LIFECYCLE_IMPORT_APPLIED_SET_MISMATCH")
    results = _selected_import_items(document, objects_value(committed["results"]))
    if any(item["definition_id"] is None or item["change"] != "added" for item in results):
        raise HarnessError("SELFTEST_LIFECYCLE_IMPORT_MAPPING_MISSING")
    return results


def _import_identity(method: str, path: str) -> tuple[str, str]:
    return method.upper(), re.sub(r"\{\{([A-Za-z_][A-Za-z0-9_.-]*)\}\}", r"{\1}", path)


def _selected_import_items(document: JsonObject, items: list[JsonObject]) -> list[JsonObject]:
    methods = ("get", "post", "put", "patch", "delete", "head", "options", "trace")
    expected = {
        _import_identity(method, path)
        for path, value in object_value(document["paths"]).items()
        for method in methods
        if method in object_value(value)
    }
    selected = [
        item
        for item in items
        if _import_identity(text_value(item["method"]), text_value(item["path"])) in expected
    ]
    actual = {
        _import_identity(text_value(item["method"]), text_value(item["path"])) for item in selected
    }
    if len(expected) != 5 or len(selected) != 5 or actual != expected:
        raise HarnessError("SELFTEST_LIFECYCLE_IMPORT_OPERATION_SET_MISMATCH")
    return selected


def _purpose(item: JsonObject) -> str:
    method, path = text_value(item["method"]), text_value(item["path"])
    path = path.replace("{{environment_id}}", "{environment_id}")
    if path == LOGIN_PATH and method == "POST":
        return "login"
    if path.endswith("/{environment_id}"):
        return {"PATCH": "patch", "DELETE": "delete"}[method]
    return {"POST": "create", "GET": "list"}[method]


async def _generate_operations(
    client: ProtocolClient, installation: Installation, imported: list[JsonObject], output_dir: Path
) -> tuple[OperationGeneration, ...]:
    generated: list[OperationGeneration] = []
    for item in imported:
        api_id, version = text_value(item["definition_id"]), integer_value(item["version"])
        inspection = await client.call(
            "flowtest.inspect_contract",
            {
                "project_id": str(installation.project_id),
                "api_definition_id": api_id,
                "version": version,
            },
            scenario_id=SCENARIO,
            phase="contract_read",
        )
        inspected = objects_value(inspection["items"])
        if (
            len(inspected) != 1
            or inspected[0]["id"] != api_id
            or inspected[0]["version"] != version
        ):
            raise HarnessError("SELFTEST_LIFECYCLE_CONTRACT_VERSION_MISMATCH")
        write_json(output_dir / f"contract-inspection-{_purpose(item)}.json", inspection)
        response = await client.call(
            "flowtest.generate_test_design",
            {
                "project_id": str(installation.project_id),
                "api_definition_id": api_id,
                "api_version": version,
                "generation_policy": {
                    "max_scenarios": 50,
                    "include_negative": False,
                    "include_auth": True,
                    "include_state": False,
                },
            },
            scenario_id=SCENARIO,
            phase="design",
        )
        design, origin = object_value(response["design"]), object_value(response["origin"])
        if origin["api_definition_id"] != api_id or origin["api_version"] != version:
            raise HarnessError("SELFTEST_LIFECYCLE_GENERATED_ORIGIN_MISMATCH")
        if fingerprint_design(TestDesignDocument.model_validate(design)) != response["fingerprint"]:
            raise HarnessError("SELFTEST_LIFECYCLE_GENERATED_DESIGN_FINGERPRINT_MISMATCH")
        coverage = await client.call(
            "flowtest.analyze_test_coverage",
            {
                "project_id": str(installation.project_id),
                "api_definition_id": api_id,
                "api_version": version,
                "generation_policy": origin["generation_policy"],
            },
            scenario_id=SCENARIO,
            phase="coverage",
        )
        if canonical_digest(coverage) != canonical_digest(design["coverage"]):
            raise HarnessError("SELFTEST_LIFECYCLE_FROZEN_COVERAGE_MISMATCH")
        write_json(output_dir / f"coverage-{_purpose(item)}.json", coverage)
        happy = [
            item for item in objects_value(design["scenarios"]) if item["kind"] == "happy_path"
        ]
        if len(happy) != 1 or response["persisted"] is not False:
            raise HarnessError("SELFTEST_LIFECYCLE_HAPPY_PATH_NOT_UNIQUE")
        generated.append(
            OperationGeneration(
                purpose=_purpose(item),
                api_source=ApiSource(
                    project_id=installation.project_id,
                    api_definition_id=UUID(api_id),
                    api_version=version,
                    contract_fingerprint=text_value(origin["contract_fingerprint"]),
                ),
                operation_ref=text_value(object_value(design["intent"])["key"]),
                design=design,
                design_fingerprint=text_value(response["fingerprint"]),
                scenario_id=text_value(happy[0]["id"]),
            )
        )
    order = {
        purpose: index
        for index, purpose in enumerate(("login", "create", "list", "patch", "delete"))
    }
    return tuple(sorted(generated, key=lambda item: order[item.purpose]))


def _response_binding(
    source: str,
    target: str,
    *,
    path: str,
    location: Literal["path", "header"],
    key: str,
    evidence: list[str],
) -> PlanBinding:
    identity = f"fixture-{target}-{location}-{key}"
    candidate = PlanBindingCandidate(
        id=identity,
        source_kind="previous_response",
        source_step_id=source,
        path=path,
        value_type="string",
        confidence=1,
        evidence_refs=evidence,
        transform="template" if location == "header" else "identity",
        template="Bearer {{value}}" if location == "header" else None,
    )
    return PlanBinding(
        id=identity,
        candidates=[candidate],
        selected_candidate_id=identity,
        target=PlanBindingTarget(step_id=target, location=location, key=key, value_type="string"),
        confidence=1,
        evidence_refs=evidence,
    )


def bind_lifecycle_plan(
    plan: IntegrationPlan, installation: Installation, batch_key: str
) -> IntegrationPlan:
    """Supply explicit synthetic fixture data and typed, reviewed response dependencies."""
    if installation.target_organization_id is None:
        raise HarnessError("SELFTEST_LIFECYCLE_TARGET_ORGANIZATION_REQUIRED")
    steps = [step for step in plan.steps if step.kind == "operation"]
    if len(steps) != 5:
        raise HarnessError("SELFTEST_LIFECYCLE_PLAN_STEPS_MISMATCH")
    by_ref = {operation.ref: operation for operation in plan.operations}
    purposes = {
        _purpose(
            {"method": by_ref[step.operation_ref].method, "path": by_ref[step.operation_ref].path}
        ): step
        for step in steps
        if step.operation_ref is not None
    }
    if [
        purpose
        for purpose in ("login", "create", "list", "patch", "delete")
        if purpose not in purposes
    ]:
        raise HarnessError("SELFTEST_LIFECYCLE_PLAN_PURPOSE_MISSING")
    evidence = [f"selftest-fixture://{batch_key}/environment-lifecycle"]
    bindings = list(plan.bindings)
    resolved: set[str] = set()
    for purpose in ("create", "list", "patch", "delete"):
        step = purposes[purpose]
        bindings = [
            binding
            for binding in bindings
            if not (
                binding.target.step_id == step.id
                and binding.target.location == "header"
                and binding.target.key.lower() == "authorization"
            )
        ]
        bindings.append(
            _response_binding(
                purposes["login"].id,
                step.id,
                path="body.access_token",
                location="header",
                key="Authorization",
                evidence=evidence,
            )
        )
        resolved.add(f"missing-bind-{step.id}-header-Authorization")
    for purpose in ("patch", "delete"):
        step = purposes[purpose]
        bindings = [
            binding
            for binding in bindings
            if not (
                binding.target.step_id == step.id
                and binding.target.location == "path"
                and binding.target.key == "environment_id"
            )
        ]
        bindings.append(
            _response_binding(
                purposes["create"].id,
                step.id,
                path="body.id",
                location="path",
                key="environment_id",
                evidence=evidence,
            )
        )
        resolved.add(f"unsupported-{step.id}-path-environment_id")
    bodies: dict[str, JsonObject] = {
        "login": {"email": installation.target_email, "password": "{{secret.SELFTEST_B_PASSWORD}}"},
        "create": {"name": f"{batch_key}-created", "base_url": "https://synthetic.invalid"},
        "patch": {"name": f"{batch_key}-updated"},
    }
    operations = []
    for purpose, step in purposes.items():
        if step.operation_ref is None:
            raise HarnessError("SELFTEST_LIFECYCLE_PLAN_OPERATION_MISSING")
        operation = by_ref[step.operation_ref]
        request = operation.request.model_copy(update={"auth_mode": "disabled"})
        if purpose != "login":
            headers = [item for item in request.headers if item.name.lower() != "x-organization-id"]
            headers.append(
                PlanRequestValue(
                    name="X-Organization-ID", value=str(installation.target_organization_id)
                )
            )
            request = request.model_copy(update={"headers": headers})
        if purpose in bodies:
            request = request.model_copy(update={"body": bodies[purpose], "body_kind": "json"})
        operations.append(operation.model_copy(update={"request": request, "credential_refs": []}))
    return seal_integration_plan(
        plan.model_copy(
            update={
                "operations": operations,
                "bindings": bindings,
                "steps": [
                    purposes[purpose] for purpose in ("login", "create", "list", "patch", "delete")
                ],
                "unresolved_items": [
                    item for item in plan.unresolved_items if item.id not in resolved
                ],
                "evidence_refs": [*plan.evidence_refs, *evidence],
            }
        )
    )


async def _context_and_plan(
    client: ProtocolClient, installation: Installation, operations: tuple[OperationGeneration, ...]
) -> tuple[JsonObject, IntegrationPlan]:
    context = await client.call(
        "flowtest.begin_test_context",
        {
            "project_id": str(installation.project_id),
            "name": f"{client.batch_key}:{SCENARIO}",
            "objective": f"{client.batch_key}:{SCENARIO}:{LIFECYCLE_OBJECTIVE}",
            "target_environment_id": str(installation.target_environment_id),
            "required_evidence": ["contract"],
            "contract_revisions": [
                {
                    "source_ref": f"api-definition://{item.api_source.api_definition_id}/version/{item.api_source.api_version}",
                    "revision": item.api_source.contract_fingerprint,
                }
                for item in operations
            ],
        },
        scenario_id=SCENARIO,
        phase="context",
    )
    revision = object_value(context["revision"])
    binding: JsonObject = {
        "context_id": context["id"],
        "context_revision_id": revision["id"],
        "context_fingerprint": revision["fingerprint"],
    }
    plan = await client.call(
        "flowtest.plan_integration_test",
        {
            "project_id": str(installation.project_id),
            "context_id": context["id"],
            "context_revision_id": revision["id"],
            "actors": [
                {
                    "id": "synthetic-owner",
                    "role": "隔离 B 项目所有者",
                    "evidence_refs": [f"selftest-fixture://{client.batch_key}/actor"],
                }
            ],
            "target_environment": {
                "key": "target",
                "source_ref": f"environment://{installation.target_environment_id}",
                "evidence_refs": [f"environment://{installation.target_environment_id}"],
            },
            "operations": [
                {
                    "definition_id": str(item.api_source.api_definition_id),
                    "api_version": item.api_source.api_version,
                    "contract_fingerprint": item.api_source.contract_fingerprint,
                    "scenario_id": item.scenario_id,
                }
                for item in operations
            ],
        },
        scenario_id=SCENARIO,
        phase="integration_plan",
    )
    return binding, bind_lifecycle_plan(
        IntegrationPlan.model_validate(plan), installation, client.batch_key
    )


def _oracle_bindings(compilation: JsonObject) -> tuple[OracleBinding, ...]:
    nodes = objects_value(object_value(compilation["flow_spec"])["nodes"])
    return tuple(
        OracleBinding(
            oracle_id=text_value(node["name"]).removeprefix("Assert "),
            node_id=text_value(node["id"]),
            assertion_name="workflow_assertion",
            expression=text_value(object_value(node["config"])["expression"]),
            expected_value_digest=canonical_digest(object_value(node["config"])["expected"]),
        )
        for node in nodes
        if node["kind"] == "assert"
    )


def _design_id(index: int, identifier: str) -> str:
    value = f"operation-{index}-{identifier}"
    return value if len(value) <= 120 else value[:107] + "-" + canonical_digest(value)[:12]


def combine_generated_designs(
    operations: tuple[OperationGeneration, ...],
) -> tuple[TestDesignDocument, JsonObject]:
    """Combine generated documents with an explicit ID map; never invent executable nodes."""
    documents = [TestDesignDocument.model_validate(item.design) for item in operations]
    scenarios: list[ScenarioCandidate] = []
    oracles: list[OracleSpec] = []
    nodes: list[KnowledgeNode] = []
    edges: list[KnowledgeEdge] = []
    evidence: list[EvidenceRef] = []
    coverage: list[CoverageEntry] = []
    mappings: JsonObject = {}
    for index, (operation, design) in enumerate(zip(operations, documents, strict=True)):
        scenario_ids = {item.id: _design_id(index, item.id) for item in design.scenarios}
        oracle_ids = {item.id: _design_id(index, item.id) for item in design.oracles}
        node_ids = {item.id: _design_id(index, item.id) for item in design.knowledge_graph.nodes}
        scenarios.extend(
            item.model_copy(update={"id": scenario_ids[item.id]}) for item in design.scenarios
        )
        oracles.extend(
            item.model_copy(
                update={
                    "id": oracle_ids[item.id],
                    "applies_to": [scenario_ids[value] for value in item.applies_to],
                }
            )
            for item in design.oracles
        )
        nodes.extend(
            item.model_copy(update={"id": node_ids[item.id]})
            for item in design.knowledge_graph.nodes
        )
        edges.extend(
            item.model_copy(
                update={"source": node_ids[item.source], "target": node_ids[item.target]}
            )
            for item in design.knowledge_graph.edges
        )
        evidence.extend(design.evidence_refs)
        coverage.extend(design.coverage.entries)
        mappings[operation.purpose] = {
            "source_fingerprint": operation.design_fingerprint,
            "scenarios": cast(JsonValue, scenario_ids),
            "oracles": cast(JsonValue, oracle_ids),
            "knowledge_nodes": cast(JsonValue, node_ids),
        }
    combined = documents[0].model_copy(
        update={
            "intent": documents[0].intent.model_copy(
                update={
                    "key": "selftest-environment-lifecycle",
                    "objective": "组合五个真实 MCP 生成设计,验证 B 环境生命周期",
                    "acceptance_criteria": ["登录、创建、列表、更新、删除均保留生成断言及固定来源"],
                }
            ),
            "scenarios": scenarios,
            "oracles": oracles,
            "evidence_refs": evidence,
            "knowledge_graph": documents[0].knowledge_graph.model_copy(
                update={"nodes": nodes, "edges": edges}
            ),
            "coverage": documents[0].coverage.model_copy(update={"entries": coverage}),
        }
    )
    return TestDesignDocument.model_validate(combined.model_dump(mode="json")), mappings


async def generate_lifecycle(
    client: ProtocolClient,
    reviewer: PublicAPI,
    *,
    installation: Installation,
    binding: StackBinding,
    batch_key: str,
    output_dir: Path,
    review_driver: ReviewDriver | None = None,
) -> LifecycleAsset:
    if batch_key != client.batch_key:
        raise HarnessError("SELFTEST_LIFECYCLE_BATCH_MISMATCH")
    generated_at = datetime.now(UTC)
    target = PublicAPI(binding.target_url, api_prefix="")
    try:
        document = await target.object("GET", "/openapi.json")
    finally:
        await target.close()
    selected = lifecycle_document(document, installation, batch_key)
    write_json(output_dir / "bound-openapi.json", selected)
    imported = await _import_document(client, installation, selected, output_dir)
    operations = await _generate_operations(client, installation, imported, output_dir)
    context, plan = await _context_and_plan(client, installation, operations)
    write_json(output_dir / "integration-plan.json", plan)
    validation = await client.call(
        "flowtest.validate_integration_plan",
        {"plan": plan.model_dump(mode="json")},
        scenario_id=SCENARIO,
        phase="integration_validation",
    )
    compilation = await client.call(
        "flowtest.compile_integration_flowspec",
        {"plan": plan.model_dump(mode="json")},
        scenario_id=SCENARIO,
        phase="compilation",
    )
    write_json(output_dir / "integration-compilation.json", compilation)
    if validation["valid"] is not True or compilation["importable"] is not True:
        raise HarnessError("SELFTEST_LIFECYCLE_COMPILATION_BLOCKED")
    spec = FlowSpec.model_validate(compilation["flow_spec"])
    write_json(
        output_dir / "metadata-bindings.json",
        {
            "kind": "context_batch_namespace",
            "field": "context.objective",
            "original_objective": LIFECYCLE_OBJECTIVE,
            "context_objective": plan.objective,
            "workflow_name": spec.name,
            "compilation_fingerprint": compilation["flow_spec_fingerprint"],
            "compiled_spec_changed": False,
            "native_definition_changed": False,
        },
    )
    mapping = {item.operation_ref: item.api_source.api_definition_id for item in operations}
    versions = {operation.ref: operation.source_version for operation in plan.operations}
    services = {operation.service_ref: "selftest_target" for operation in plan.operations}
    native = flow_spec_to_workflow_definition(
        spec, operation_mappings=mapping, operation_versions=versions, service_keys=services
    ).model_dump(mode="json")
    proposal = await client.call(
        "flowtest.propose_flow_draft",
        {
            "project_id": str(installation.project_id),
            "context_id": context["context_id"],
            "context_revision_id": context["context_revision_id"],
            "integration_plan": plan.model_dump(mode="json"),
            "compilation": compilation,
            "operation_mappings": {key: str(value) for key, value in mapping.items()},
            "operation_version_mappings": cast(JsonValue, versions),
            "service_mappings": {
                operation.service_ref: str(installation.target_service_id)
                for operation in plan.operations
            },
            "source_ref": f"mcp://selftest/{batch_key}/{SCENARIO}",
            "idempotency_key": f"{batch_key}:{SCENARIO}:workflow",
            "dry_run": False,
        },
        scenario_id=SCENARIO,
        phase="workflow_proposal",
    )
    workflow = await (review_driver or FixtureReviewDriver()).flow(
        reviewer,
        project_id=str(installation.project_id),
        reviewer_id=str(installation.reviewer_id),
        proposal_id=text_value(proposal["change_set_id"]),
        expected_definition=native,
        expected_api_ids=tuple(str(item.api_source.api_definition_id) for item in operations),
        output_dir=output_dir,
    )
    combined, composition = combine_generated_designs(operations)
    case = await propose_case(
        client,
        reviewer,
        installation,
        SCENARIO,
        combined.model_dump(mode="json"),
        workflow,
        output_dir,
        environment_id=str(installation.target_environment_id),
        review_driver=review_driver,
    )
    asset = LifecycleAsset(
        target_project_id=installation.target_project_id,
        operations=operations,
        source_document_digest=canonical_digest(document),
        bound_document_digest=canonical_digest(selected),
        source_reused=all(item["change"] == "unchanged" for item in imported),
        context=context,
        integration_plan=plan.model_dump(mode="json"),
        combined_design=combined.model_dump(mode="json"),
        combined_design_fingerprint=fingerprint_design(combined),
        design_composition=composition,
        compilation_fingerprint=text_value(compilation["flow_spec_fingerprint"]),
        oracle_bindings=_oracle_bindings(compilation),
        workflow=workflow,
        case=case,
        calls=tuple(item for item in client.receipts if item.scenario_id == SCENARIO),
        created_resource_name=f"{batch_key}-created",
        updated_resource_name=f"{batch_key}-updated",
        generated_at=generated_at,
        frozen_at=datetime.now(UTC),
    )
    write_json(output_dir / "generated-lifecycle-asset.json", asset)
    return asset
