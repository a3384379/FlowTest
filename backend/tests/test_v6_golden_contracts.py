from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from app.domain.change_regression import OperationIdentity
from app.domain.evidence import DataProfile
from app.domain.flow_spec import (
    FlowSpec,
    flow_spec_fingerprint,
    flow_spec_to_workflow_definition,
    normalize_flow_spec,
    validate_flow_spec,
    workflow_definition_to_flow_spec,
)
from app.domain.flow_spec_v2 import (
    FlowSpecCleanupV2,
    FlowSpecRunPolicy,
    FlowSpecV2,
    convert_flow_spec_v1_to_v2,
    downgrade_flow_spec_v2_to_v1,
    flow_spec_v2_fingerprint,
    flow_spec_v2_to_workflow_definition,
    validate_flow_spec_v2,
)
from app.domain.integration_plans import (
    IntegrationPlan,
    compile_integration_plan,
    integration_plan_fingerprint,
    validate_integration_plan,
)
from app.domain.mcp_read import MCP_READ_SCHEMA_VERSION, MCP_SERVER_NAME
from app.domain.sandbox_preview import MCP_SANDBOX_PREVIEW_SERVER_VERSION
from app.domain.test_design import TestDesignDocument as GoldenTestDesignDocument
from app.domain.test_design import fingerprint_design
from app.domain.test_engineering import OperationContract, fingerprint_contract
from app.domain.v6_evaluation import (
    EvaluationAnnotation,
    EvaluationMetric,
    summarize_evaluations,
)
from app.engine.contracts import WorkflowDefinition
from app.mcp.client import MCPReadGatewayClient
from app.mcp.server import create_mcp_server
from app.operations.standalone_transfer import (
    STANDALONE_SCHEMA_REVISION,
    TRANSFER_SCHEMA_VERSION,
)
from app.schemas.ai_change_sets import AIChangeSetDetailResponse

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "v6_golden"


def _load(name: str) -> Any:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _load_mapping(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], _load(name))


def test_frozen_contracts_parse_with_current_models() -> None:
    assert OperationContract.model_validate(_load("http-contract.json")).operation == (
        "orders.create"
    )
    assert WorkflowDefinition.model_validate(_load("workflow-definition.json")).schema_version == (
        "1.0"
    )
    assert AIChangeSetDetailResponse.model_validate(_load("ai-change-set.json")).items[
        0
    ].item_type == ("workflow")
    assert GoldenTestDesignDocument.model_validate(_load("test-design.json")).intent.key == (
        "orders.create"
    )
    assert DataProfile.model_validate(_load("db-profile.json")).entity == "orders"


def test_flowspec_fingerprints_v1_v2_v3_are_frozen() -> None:
    spec = FlowSpec.model_validate(_load("login-create-query.flowspec-v1.json"))
    fingerprints = _load_mapping("fingerprints.json")
    versions = {
        "flow_spec_v1": "flowtest-flow-spec-fingerprint-v1",
        "flow_spec_v2": "flowtest-flow-spec-fingerprint-v2",
        "flow_spec_v3": "flowtest-flow-spec-fingerprint-v3",
    }
    for key, version in versions.items():
        candidate = spec.model_copy(update={"fingerprint_version": version})
        assert flow_spec_fingerprint(candidate) == fingerprints[key]
    assert validate_flow_spec(spec).valid is True


def test_integration_plan_and_compiled_flowspec_fingerprints_are_frozen() -> None:
    plan = IntegrationPlan.model_validate(_load("login-create-query.integration-plan-v1.json"))
    expected_flow_spec = FlowSpec.model_validate(
        _load("login-create-query.compiled.flowspec-v1.json")
    )
    fingerprints = _load_mapping("fingerprints.json")
    compilation = compile_integration_plan(plan)

    assert validate_integration_plan(plan).valid is True
    assert integration_plan_fingerprint(plan) == fingerprints["integration_plan_v1"]
    assert plan.plan_fingerprint == fingerprints["integration_plan_v1"]
    assert compilation.importable is True
    assert compilation.flow_spec == expected_flow_spec
    assert (
        compilation.flow_spec_fingerprint == fingerprints["integration_plan_compiled_flow_spec_v1"]
    )
    assert compilation.node_evidence
    assert compilation.edge_evidence


def test_flowspec_v1_to_v2_is_deterministic_and_lossless_for_v1_semantics() -> None:
    v1 = FlowSpec.model_validate(_load("login-create-query.flowspec-v1.json"))
    expected = FlowSpecV2.model_validate(_load("login-create-query.flowspec-v2.json"))
    converted = convert_flow_spec_v1_to_v2(v1)

    assert converted == expected
    assert convert_flow_spec_v1_to_v2(v1) == converted
    assert (
        convert_flow_spec_v1_to_v2(_load_mapping("login-create-query.flowspec-v1.json"))
        == converted
    )
    assert validate_flow_spec_v2(converted).valid is True
    assert (
        flow_spec_v2_fingerprint(converted)
        == _load_mapping("fingerprints.json")["flow_spec_schema_v2"]
    )
    assert downgrade_flow_spec_v2_to_v1(converted) == normalize_flow_spec(v1)


def test_flowspec_v2_rejects_unknown_fields_and_lossy_downgrade() -> None:
    raw = _load_mapping("login-create-query.flowspec-v2.json")
    with pytest.raises(ValidationError):
        FlowSpecV2.model_validate({**raw, "future_runtime_switch": True})
    with pytest.raises(ValidationError):
        FlowSpecV2.model_validate(
            {
                **raw,
                "bindings": [{"from": "$.login.token", "to": "$.create.token", "form": "typo"}],
            }
        )
    with pytest.raises(ValidationError, match="cleanup IDs must be unique"):
        FlowSpecV2.model_validate(
            {
                **raw,
                "cleanup": [
                    {"id": "duplicate", "operation_ref": "orders.create"},
                    {"id": "duplicate", "operation_ref": "orders.query"},
                ],
            }
        )

    spec = FlowSpecV2.model_validate(raw)
    v2_only = spec.model_copy(
        update={
            "run_policy": FlowSpecRunPolicy(
                request_budget=21,
                cleanup_request_budget=21,
            ),
            "cleanup": [
                FlowSpecCleanupV2(
                    id="cleanup-001",
                    operation_ref="orders.missing",
                    cleanup_for=["missing-node"],
                )
            ],
        }
    )
    validation = validate_flow_spec_v2(v2_only)
    assert validation.valid is False
    assert {issue.code for issue in validation.issues} >= {
        "REQUEST_BUDGET_EXCEEDS_SECURITY_POLICY",
        "CLEANUP_REQUEST_BUDGET_EXCEEDS_SECURITY_POLICY",
        "UNKNOWN_CLEANUP_OPERATION",
        "UNKNOWN_CLEANUP_TARGET",
    }
    with pytest.raises(ValueError, match="cannot represent"):
        downgrade_flow_spec_v2_to_v1(v2_only)

    custom_identity = spec.model_copy(
        update={"cleanup": [FlowSpecCleanupV2(id="custom-cleanup", operation_ref="orders.create")]}
    )
    with pytest.raises(ValueError, match="cannot represent"):
        downgrade_flow_spec_v2_to_v1(custom_identity)


def test_flowspec_v2_validation_paths_preserve_submitted_order() -> None:
    raw = _load_mapping("login-create-query.flowspec-v2.json")
    spec = FlowSpecV2.model_validate(
        {
            **raw,
            "cleanup": [
                {"id": "z-first", "operation_ref": "orders.missing"},
                {"id": "a-second", "operation_ref": "orders.create"},
            ],
        }
    )

    validation = validate_flow_spec_v2(spec)

    assert [
        issue.path for issue in validation.issues if issue.code == "UNKNOWN_CLEANUP_OPERATION"
    ] == ["$.cleanup[0].operation_ref"]


def test_flowspec_v2_compiles_cleanup_into_bounded_runtime_phase() -> None:
    raw = _load_mapping("login-create-query.flowspec-v2.json")
    spec = FlowSpecV2.model_validate(
        {
            **raw,
            "cleanup": [
                {
                    "id": "delete-order",
                    "operation_ref": "orders.query",
                    "run_when": "failure",
                    "cleanup_for": ["create"],
                    "best_effort": True,
                    "cleanup_timeout_seconds": 12,
                    "cleanup_retry_budget": 1,
                }
            ],
            "run_policy": {
                "cleanup_request_budget": 2,
                "force_cancel_skips_cleanup": True,
            },
        }
    )
    operation_ids = {
        operation.ref: UUID(int=index) for index, operation in enumerate(spec.operations, start=1)
    }

    definition = flow_spec_v2_to_workflow_definition(
        spec,
        operation_mappings=operation_ids,
        service_keys={"auth": "auth", "orders": "orders"},
        operation_versions={operation.ref: 1 for operation in spec.operations},
    )

    cleanup = next(node for node in definition.nodes if node.phase == "cleanup")
    assert definition.schema_version == "2.0"
    assert definition.run_policy.cleanup_request_budget == 2
    assert definition.run_policy.force_cancel_skips_cleanup is True
    assert cleanup.id == "delete-order"
    assert cleanup.cleanup_for == ["create"]
    assert cleanup.run_when == "failure"
    assert cleanup.best_effort is True
    assert cleanup.cleanup_timeout_seconds == 12
    assert cleanup.cleanup_retry_budget == 1


def test_v1_workflow_round_trip_preserves_semantic_fingerprint() -> None:
    spec = FlowSpec.model_validate(_load("login-create-query.flowspec-v1.json"))
    operation_ids = {
        "auth.login": UUID("00000000-0000-0000-0000-000000000101"),
        "orders.create": UUID("00000000-0000-0000-0000-000000000102"),
        "orders.query": UUID("00000000-0000-0000-0000-000000000103"),
    }
    service_keys = {"auth": "auth", "orders": "orders"}
    versions = {operation.ref: 1 for operation in spec.operations}
    workflow = flow_spec_to_workflow_definition(
        spec,
        operation_mappings=operation_ids,
        service_keys=service_keys,
        operation_versions=versions,
    )
    operation_refs = {
        node.id: node.operation_ref for node in spec.nodes if node.operation_ref is not None
    }
    node_targets = {node.id: node.target for node in spec.nodes if node.target is not None}
    restored = workflow_definition_to_flow_spec(
        workflow,
        name=spec.name,
        description=spec.description,
        source_evidence=spec.source_evidence,
        operation_refs=operation_refs,
        node_targets=node_targets,
        services=spec.services,
        operations=spec.operations,
    )
    assert flow_spec_fingerprint(restored) == flow_spec_fingerprint(spec)


def test_semantic_contracts_and_snapshot_shape_are_frozen() -> None:
    fingerprints = _load_mapping("fingerprints.json")
    contract = OperationContract.model_validate(_load("http-contract.json"))
    design = GoldenTestDesignDocument.model_validate(_load("test-design.json"))
    identity = OperationIdentity.model_validate(_load("operation-identity.json"))
    snapshot = _load_mapping("execution-snapshot.json")

    assert fingerprint_contract(contract) == fingerprints["http_contract"]
    assert fingerprint_design(design) == fingerprints["test_design"]
    assert identity.semantic_prefix == fingerprints["operation_semantic_prefix"]
    assert set(snapshot) == {
        "schema_version",
        "workflow",
        "environment",
        "apis",
        "subflows",
        "data_nodes",
        "protocol_nodes",
        "event_nodes",
        "capabilities",
        "dataset",
        "runtime",
    }
    workflow = cast(dict[str, Any], snapshot["workflow"])
    WorkflowDefinition.model_validate(workflow["definition"])


def test_standalone_and_static_source_fixtures_are_pinned_without_execution() -> None:
    transfer = _load_mapping("standalone-transfer-manifest.json")
    assert transfer["schema_version"] == TRANSFER_SCHEMA_VERSION
    assert transfer["source_schema_revision"] == STANDALONE_SCHEMA_REVISION
    assert transfer["target_schema_revision"] == STANDALONE_SCHEMA_REVISION

    manifest = _load_mapping("small-spring/manifest.json")
    assert manifest["execute_analyzed_code"] is False
    files = cast(dict[str, str], manifest["files"])
    for relative_path, expected_hash in files.items():
        content = (FIXTURE_ROOT / "small-spring" / relative_path).read_bytes()
        assert hashlib.sha256(content).hexdigest() == expected_hash

    ruoyi = _load_mapping("ruoyi-target.json")
    compose = (FIXTURE_ROOT.parents[3] / "deploy" / "ruoyi" / "compose.yaml").read_text(
        encoding="utf-8"
    )
    assert ruoyi["execute_analyzed_code"] is False
    assert str(ruoyi["image"]) in compose
    assert "mysql:8.4" in compose


@pytest.mark.asyncio
async def test_mcp_tool_contract_is_frozen() -> None:
    contract = _load_mapping("mcp-contract.json")
    transport = httpx.MockTransport(lambda request: httpx.Response(500, request=request))
    async with MCPReadGatewayClient(
        base_url="http://golden.invalid",
        token="ftsa_golden_reference",
        transport=transport,
    ) as gateway:
        tools = await create_mcp_server(client=gateway).list_tools()

    assert contract["server_name"] == MCP_SERVER_NAME
    assert contract["server_version"] == MCP_SANDBOX_PREVIEW_SERVER_VERSION
    assert contract["read_schema_version"] == MCP_READ_SCHEMA_VERSION
    assert [tool.name for tool in tools] == contract["tools"]


def test_evaluation_annotation_and_statistics_contract_is_reproducible() -> None:
    annotations = [
        EvaluationAnnotation.model_validate(item) for item in _load("evaluation-annotations.json")
    ]
    summaries = {item.metric: item for item in summarize_evaluations(annotations)}

    assert summaries[EvaluationMetric.OPERATION_CANDIDATE_PRECISION].value == 1.0
    assert summaries[EvaluationMetric.BINDING_CANDIDATE_PRECISION].value == 0.0
    assert summaries[EvaluationMetric.COMPILER_SUCCESS].value == 1.0
    assert summaries[EvaluationMetric.MANUAL_EDIT_RATE].value == 0.0
    assert summaries[EvaluationMetric.PREVIEW_FIRST_PASS].value is None
    assert summaries[EvaluationMetric.EVIDENCE_CONFLICT_RATE].value == 0.0

    invalid = annotations[0].model_dump(mode="json") | {"label": "pass"}
    with pytest.raises(ValidationError):
        EvaluationAnnotation.model_validate(invalid)
