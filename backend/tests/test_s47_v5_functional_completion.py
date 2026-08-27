"""Cross-module S47 functional gate; assertions validate behavior, not file presence."""

from uuid import UUID

from app.domain.change_regression import (
    _focused_change_contract,
    _mutation_path,
    _schema_at_path,
    missing_test_design,
    oracle_set_fingerprint,
)
from app.domain.failure_triage import FailureSignal, triage_failures
from app.domain.flow_spec import (
    FlowSpecNodeTarget,
    FlowSpecOperation,
    FlowSpecService,
    flow_spec_fingerprint,
    flow_spec_to_workflow_definition,
    workflow_definition_to_flow_spec,
)
from app.domain.test_design import TestDesignDocument as DesignDocument
from app.domain.test_design import sensitive_paths
from app.domain.test_engineering import OperationContract, TestEngineeringEngine
from app.engine.contracts import WorkflowDefinition


def test_s47_generated_design_has_exact_boundaries_evidence_and_coverage() -> None:
    contract = OperationContract.model_validate(
        {
            "operation": "orders.create",
            "method": "POST",
            "path": "/orders",
            "auth": {"required": True},
            "request": {
                "type": "object",
                "required": ["quantity", "type"],
                "properties": {
                    "quantity": {"type": "integer", "minimum": 1, "maximum": 999},
                    "type": {"type": "string", "enum": ["NORMAL", "PRIORITY"]},
                },
            },
            "responses": {
                "200": {"description": "success"},
                "400": {"description": "invalid"},
                "401": {"description": "unauthorized"},
            },
        }
    )

    design = TestEngineeringEngine().generate(contract=contract)
    values = {
        (scenario.kind, mutation.path, mutation.value)
        for scenario in design.scenarios
        for mutation in scenario.mutations
    }

    assert {
        ("number_below_min", "body.quantity", 0),
        ("number_at_min", "body.quantity", 1),
        ("number_at_max", "body.quantity", 999),
        ("number_above_max", "body.quantity", 1000),
        ("enum_value", "body.type", "NORMAL"),
        ("enum_value", "body.type", "PRIORITY"),
        ("enum_invalid", "body.type", "__invalid__"),
        ("auth_missing", "auth", None),
    } <= values
    assert all(entry.covered for entry in design.coverage.entries)
    assert design.evidence_refs
    assert sensitive_paths(design.model_dump(mode="json")) == ()


def test_s47_portable_multi_service_mapping_is_uuid_independent() -> None:
    source_project = UUID("00000000-0000-4000-8000-000000000047")
    target_project = UUID("00000000-0000-4000-8000-000000000048")
    definition = WorkflowDefinition.model_validate(
        {
            "nodes": [
                _node("start", "start", {}),
                _node("orders", "api", {"api_definition_id": str(source_project)}),
                _node("billing", "api", {"api_definition_id": str(target_project)}),
                _node("end", "end", {}),
            ],
            "edges": [
                {"id": "start-orders", "source": "start", "target": "orders"},
                {"id": "orders-billing", "source": "orders", "target": "billing"},
                {"id": "billing-end", "source": "billing", "target": "end"},
            ],
        }
    )
    services = [
        FlowSpecService(ref="service.orders", name="Orders"),
        FlowSpecService(ref="service.billing", name="Billing"),
    ]
    operations = [
        FlowSpecOperation(
            ref="orders.health",
            service_ref="service.orders",
            name="Orders health",
            method="GET",
            path="/health",
        ),
        FlowSpecOperation(
            ref="billing.health",
            service_ref="service.billing",
            name="Billing health",
            method="GET",
            path="/health",
        ),
    ]
    spec = workflow_definition_to_flow_spec(
        definition,
        project_id=source_project,
        operation_refs={"orders": "orders.health", "billing": "billing.health"},
        node_targets={
            "orders": FlowSpecNodeTarget(service_ref="service.orders", endpoint_variant="blue"),
            "billing": FlowSpecNodeTarget(service_ref="service.billing", endpoint_variant="canary"),
        },
        services=services,
        operations=operations,
    )
    relocated = spec.model_copy(update={"project_id": target_project})

    assert flow_spec_fingerprint(spec) == flow_spec_fingerprint(relocated)
    mapped = flow_spec_to_workflow_definition(
        relocated,
        operation_mappings={
            "orders.health": UUID("00000000-0000-4000-8000-000000000101"),
            "billing.health": UUID("00000000-0000-4000-8000-000000000102"),
        },
        service_keys={"service.orders": "orders", "service.billing": "billing"},
    )
    configs = {node.id: node.config for node in mapped.nodes}
    assert configs["orders"]["service_override"] == "orders"
    assert configs["orders"]["endpoint_variant"] == "blue"
    assert configs["billing"]["service_override"] == "billing"
    assert configs["billing"]["endpoint_variant"] == "canary"


def test_s47_change_boundary_and_failure_triage_are_concrete() -> None:
    document = DesignDocument.model_validate(
        missing_test_design(
            gap={
                "change_key": "orders.quantity.maximum",
                "source_key": "POST /orders",
                "label": "quantity maximum 100 -> 999",
                "semantic_type": "maximum_changed",
                "field_path": "request.body.quantity.maximum",
                "before": 100,
                "after": 999,
            },
            source_ref="github://acme/orders/commit/s47",
            position=1,
        )
    )
    values_by_tag = {
        tag: scenario.mutations[0].value
        for scenario in document.scenarios
        if scenario.mutations
        for tag in scenario.tags
        if tag
        in {
            "new_legal_boundary",
            "new_illegal_boundary",
            "historical_boundary",
            "historical_adjacent",
        }
    }
    triage = triage_failures(
        [
            FailureSignal(
                evidence_ref="execution://s47/item/1",
                item_status="failed",
                attempts=2,
                error_code="HTTP_5XX",
                retryable=True,
                http_status=503,
                affected_service="orders",
                affected_operation="POST /orders",
                response_received=True,
            )
        ]
    )

    assert values_by_tag == {
        "new_legal_boundary": 999,
        "new_illegal_boundary": 1000,
        "historical_boundary": 100,
        "historical_adjacent": 101,
    }
    assert triage.primary_classification == "UPSTREAM_SERVICE_FAILURE"
    assert "UPSTREAM_RESPONSE_5XX" in triage.reason_codes
    assert triage.evidence_refs == ["execution://s47/item/1"]
    assert triage.retry_signal is True
    assert triage.recommended_regression


def test_s47_semantic_coverage_avoids_historical_boundary_duplicates() -> None:
    success_oracle = oracle_set_fingerprint(("status:201",))
    assert success_oracle is not None
    current_contract = OperationContract.model_validate(
        {
            "operation": "orders.create",
            "method": "POST",
            "path": "/tenants/{tenant_id}/orders",
            "auth": {"required": True, "kind": "bearer"},
            "parameters": [
                {
                    "name": "tenant_id",
                    "location": "path",
                    "required": True,
                    "schema": {"type": "string", "format": "uuid"},
                }
            ],
            "request_body": {
                "required": True,
                "schema": {
                    "type": "object",
                    "required": ["quantity"],
                    "properties": {"quantity": {"type": "integer", "minimum": 1, "maximum": 999}},
                },
            },
            "responses": {
                "201": {"description": "created"},
                "422": {"description": "invalid"},
            },
        }
    )
    document = DesignDocument.model_validate(
        missing_test_design(
            gap={
                "change_key": "orders.quantity.maximum",
                "source_key": "POST /orders",
                "label": "quantity maximum 100 -> 999",
                "semantic_type": "maximum_changed",
                "field_path": "request.body.quantity.maximum",
                "before": 100,
                "after": 999,
            },
            source_ref="github://acme/orders/commit/s47-1",
            position=1,
            current_contract=current_contract,
            covered_values={
                f"99|success|{success_oracle}",
                f"100|success|{success_oracle}",
                f"101|success|{success_oracle}",
            },
        )
    )

    assert {
        scenario.mutations[0].value for scenario in document.scenarios if scenario.mutations
    } == {999, 1000}
    assert {
        oracle.expected
        for oracle in document.oracles
        if oracle.kind == "status" and oracle.deterministic
    } == {
        201,
        422,
    }
    assert (
        _focused_change_contract(current_contract, {"field_path": "request.body.quantity"})
        is current_contract
    )
    assert (
        _focused_change_contract(current_contract, {"field_path": "request.body.missing.maximum"})
        is current_contract
    )
    assert _schema_at_path({"properties": {"quantity": 1}}, ["quantity", "child"]) is None
    assert _schema_at_path({"type": "object"}, ["missing"]) is None
    assert _mutation_path(document) == "body.quantity"


def _node(node_id: str, node_type: str, config: dict[str, str]) -> dict[str, object]:
    return {
        "id": node_id,
        "type": node_type,
        "name": node_id.title(),
        "position": {"x": 0, "y": 0},
        "config": config,
    }
