import pytest

from app.domain.failure_repair import (
    RepairScopeError,
    diagnose_failure,
    validate_repair_scope,
)
from app.domain.failure_triage import FailureSignal
from app.domain.flow_spec import FlowSpec, FlowSpecEdge, FlowSpecNode, FlowSpecOperation
from app.domain.flow_spec_v2 import FlowSpecCleanupV2, FlowSpecRunPolicy, FlowSpecV2
from app.engine.contracts import (
    FieldMapping,
    MappingSource,
    MappingTarget,
    MappingTargetLocation,
    Position,
)


def _signal(**changes: object) -> FailureSignal:
    payload: dict[str, object] = {
        "evidence_ref": "flowtest://runs/run-1/nodes/node-1",
        "item_status": "failed",
        "attempts": 1,
    }
    payload.update(changes)
    return FailureSignal.model_validate(payload)


def _spec() -> FlowSpec:
    return FlowSpec(
        name="Repair target",
        nodes=[
            FlowSpecNode(
                id="start",
                kind="start",
                name="Start",
                position=Position(x=0, y=0),
            ),
            FlowSpecNode(
                id="assert",
                kind="assert",
                name="Assert",
                position=Position(x=100, y=0),
                config={
                    "source_node_id": "start",
                    "expression": "$.status",
                    "operator": "equals",
                    "expected": 200,
                },
            ),
            FlowSpecNode(
                id="end",
                kind="end",
                name="End",
                position=Position(x=200, y=0),
            ),
        ],
        edges=[
            FlowSpecEdge(id="start-assert", source="start", target="assert"),
            FlowSpecEdge(id="assert-end", source="assert", target="end"),
        ],
    )


def test_failure_diagnosis_product_defect_guard_is_fail_closed() -> None:
    diagnosis = diagnose_failure(
        [_signal(http_status=500, response_received=True, assertion_failed=True)]
    )
    assert diagnosis.triage.primary_classification == "PRODUCT_DEFECT"
    assert diagnosis.repair_policy.product_defect_guard is True
    assert diagnosis.repair_policy.proposal_allowed is False
    assert diagnosis.repair_policy.allowed_kinds == ()

    with pytest.raises(RepairScopeError, match="Product Defect"):
        validate_repair_scope(
            before=_spec(),
            after=_spec().model_copy(update={"variables": {"customer_id": "42"}}),
            diagnosis=diagnosis,
            kind="data",
            acknowledge_oracle_weakening=False,
        )


def test_product_defect_secondary_candidate_also_blocks_test_repair() -> None:
    diagnosis = diagnose_failure(
        [
            _signal(error_code="TEST_DATA_MISSING"),
            _signal(
                evidence_ref="flowtest://runs/run-1/nodes/api-2",
                http_status=500,
                response_received=True,
                assertion_failed=True,
            ),
        ]
    )

    assert diagnosis.triage.primary_classification == "BAD_TEST_DATA"
    assert "PRODUCT_DEFECT" in diagnosis.triage.secondary_candidates
    assert diagnosis.repair_policy.product_defect_guard is True
    assert diagnosis.repair_policy.proposal_allowed is False
    assert diagnosis.repair_policy.allowed_kinds == ()


def test_product_defect_guard_inspects_signals_hidden_by_secondary_limit() -> None:
    error_codes = [
        "RESPONSE_SCHEMA_MISMATCH",
        "RESPONSE_SCHEMA_MISMATCH",
        "SERVICE_ENDPOINT_NOT_FOUND",
        "NETWORK_ERROR",
        "WORKFLOW_ASSERTION_FAILED",
    ]
    signals = [
        _signal(
            evidence_ref=f"flowtest://runs/run-1/nodes/node-{index}",
            error_code=error_code,
        )
        for index, error_code in enumerate(error_codes)
    ]
    signals.extend(
        [
            _signal(
                evidence_ref="flowtest://runs/run-1/nodes/cancelled",
                item_status="cancelled",
            ),
            _signal(
                evidence_ref="flowtest://runs/run-1/nodes/auth",
                http_status=401,
            ),
        ]
    )

    diagnosis = diagnose_failure(signals)

    assert diagnosis.triage.primary_classification == "CONTRACT_DRIFT"
    assert "PRODUCT_DEFECT" not in diagnosis.triage.secondary_candidates
    assert diagnosis.repair_policy.product_defect_guard is True
    assert diagnosis.repair_policy.proposal_allowed is False
    assert diagnosis.repair_policy.allowed_kinds == ()


def test_binding_repair_is_limited_to_binding_surfaces() -> None:
    diagnosis = diagnose_failure([_signal(error_code="MAPPING_INVALID")])
    before = _spec()
    mapping = FieldMapping(
        source=MappingSource(node_id="start", path="$.customer_id"),
        target=MappingTarget(
            node_id="assert",
            location=MappingTargetLocation.VARIABLE,
            key="customer_id",
        ),
    )
    edges = [
        before.edges[0].model_copy(update={"mappings": [mapping]}),
        before.edges[1],
    ]
    after = before.model_copy(update={"edges": edges})

    result = validate_repair_scope(
        before=before,
        after=after,
        diagnosis=diagnosis,
        kind="binding",
        acknowledge_oracle_weakening=False,
    )
    assert result.kind == "binding"
    assert result.oracle_weakening is False

    crossed = after.model_copy(update={"variables": {"unexpected": "change"}})
    with pytest.raises(RepairScopeError, match="边界"):
        validate_repair_scope(
            before=before,
            after=crossed,
            diagnosis=diagnosis,
            kind="binding",
            acknowledge_oracle_weakening=False,
        )


def test_oracle_change_requires_explicit_weakening_acknowledgement() -> None:
    diagnosis = diagnose_failure([_signal(error_code="MAPPING_INVALID")])
    before = _spec()
    changed_assert = before.nodes[1].model_copy(
        update={
            "config": {
                **before.nodes[1].config,
                "expected": [200, 201],
                "operator": "in",
            }
        }
    )
    after = before.model_copy(update={"nodes": [before.nodes[0], changed_assert, before.nodes[2]]})

    with pytest.raises(RepairScopeError, match="显式确认"):
        validate_repair_scope(
            before=before,
            after=after,
            diagnosis=diagnosis,
            kind="oracle",
            acknowledge_oracle_weakening=False,
        )
    accepted = validate_repair_scope(
        before=before,
        after=after,
        diagnosis=diagnosis,
        kind="oracle",
        acknowledge_oracle_weakening=True,
    )
    assert accepted.oracle_weakening is True


def test_oracle_repair_cannot_replace_assertion_node_identity() -> None:
    diagnosis = diagnose_failure([_signal(error_code="MAPPING_INVALID")])
    before = _spec()
    replaced_assert = before.nodes[1].model_copy(
        update={
            "kind": "http",
            "name": "Run arbitrary request",
            "config": {"method": "POST", "url": "https://example.invalid"},
        }
    )
    after = before.model_copy(update={"nodes": [before.nodes[0], replaced_assert, before.nodes[2]]})

    with pytest.raises(RepairScopeError, match="边界"):
        validate_repair_scope(
            before=before,
            after=after,
            diagnosis=diagnosis,
            kind="oracle",
            acknowledge_oracle_weakening=True,
        )


def test_cleanup_failure_adds_cleanup_repair_without_widening_other_failures() -> None:
    cleanup = diagnose_failure([_signal(error_code="MAPPING_INVALID", phase="cleanup")])
    main = diagnose_failure([_signal(error_code="MAPPING_INVALID", phase="main")])

    assert cleanup.repair_policy.allowed_kinds == ("binding", "oracle", "cleanup")
    assert main.repair_policy.allowed_kinds == ("binding", "oracle")


def test_environment_cleanup_failure_does_not_allow_test_repair() -> None:
    diagnosis = diagnose_failure(
        [_signal(error_code="ENVIRONMENT_PROVISION_TIMEOUT", phase="cleanup")]
    )

    assert diagnosis.triage.primary_classification == "ENVIRONMENT_FAILURE"
    assert diagnosis.repair_policy.proposal_allowed is False
    assert diagnosis.repair_policy.allowed_kinds == ()


def test_cleanup_repair_is_limited_to_v2_cleanup_and_run_policy() -> None:
    diagnosis = diagnose_failure([_signal(error_code="MAPPING_INVALID", phase="cleanup")])
    before = FlowSpecV2.model_validate(
        {
            **_spec().model_dump(mode="json"),
            "schema_version": "flowtest-flow-spec-v2",
            "fingerprint_version": "flowtest-flow-spec-v2-fingerprint-v1",
            "cleanup": [],
            "plan_metadata": {},
            "run_policy": {},
        }
    )
    after = before.model_copy(
        update={
            "cleanup": [
                FlowSpecCleanupV2(
                    id="cleanup-fixture",
                    operation_ref="fixture.delete",
                    cleanup_for=["assert"],
                )
            ],
            "run_policy": FlowSpecRunPolicy(cleanup_request_budget=2),
        }
    )

    accepted = validate_repair_scope(
        before=before,
        after=after,
        diagnosis=diagnosis,
        kind="cleanup",
        acknowledge_oracle_weakening=False,
    )
    assert accepted.kind == "cleanup"

    crossed = after.model_copy(update={"variables": {"unexpected": "change"}})
    with pytest.raises(RepairScopeError, match="边界"):
        validate_repair_scope(
            before=before,
            after=crossed,
            diagnosis=diagnosis,
            kind="cleanup",
            acknowledge_oracle_weakening=False,
        )


def test_contract_drift_repair_preserves_operation_identity() -> None:
    diagnosis = diagnose_failure([_signal(error_code="RESPONSE_SCHEMA_MISMATCH")])
    operation = FlowSpecOperation(
        ref="orders.get",
        service_ref="orders",
        name="Get order",
        method="GET",
        path="/orders/{id}",
        version_strategy="pinned",
        source_version=1,
        contract_fingerprint="a" * 64,
    )
    before = _spec().model_copy(update={"operations": [operation]})
    after = before.model_copy(
        update={
            "operations": [
                operation.model_copy(update={"source_version": 2, "contract_fingerprint": "b" * 64})
            ]
        }
    )

    accepted = validate_repair_scope(
        before=before,
        after=after,
        diagnosis=diagnosis,
        kind="contract_drift",
        acknowledge_oracle_weakening=False,
    )
    assert accepted.oracle_weakening is False

    changed_identity = after.model_copy(
        update={"operations": [after.operations[0].model_copy(update={"path": "/users"})]}
    )
    with pytest.raises(RepairScopeError, match="版本和契约指纹"):
        validate_repair_scope(
            before=before,
            after=changed_identity,
            diagnosis=diagnosis,
            kind="contract_drift",
            acknowledge_oracle_weakening=False,
        )
