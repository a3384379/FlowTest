from app.domain.failure_triage import FailureSignal, triage_failures


def _signal(**changes: object) -> FailureSignal:
    payload: dict[str, object] = {
        "evidence_ref": "flowtest://runs/run-1/nodes/api-1",
        "item_status": "failed",
        "attempts": 1,
        "affected_service": "orders.internal",
        "affected_operation": "POST /orders",
    }
    payload.update(changes)
    return FailureSignal.model_validate(payload)


def test_failure_triage_uses_status_and_error_codes() -> None:
    auth = triage_failures([_signal(http_status=401, response_received=True)])
    assert auth.primary_classification == "AUTH_FAILURE"
    assert auth.reason_codes == ["HTTP_AUTH_STATUS"]

    timeout = triage_failures([_signal(error_code="NETWORK_TIMEOUT", retryable=True)])
    assert timeout.primary_classification == "TIMEOUT"
    assert timeout.retry_signal is True

    contract = triage_failures(
        [_signal(error_code="WORKFLOW_ASSERTION_FAILED", contract_assertion_failed=True)]
    )
    assert contract.primary_classification == "CONTRACT_DRIFT"
    assert contract.recommended_regression == ["重跑 Contract Oracle", "生成差异边界用例"]


def test_failure_triage_aggregates_service_and_flaky_evidence() -> None:
    endpoint = triage_failures(
        [
            _signal(error_code="NETWORK_ERROR"),
            _signal(
                evidence_ref="flowtest://runs/run-1/nodes/api-2",
                error_code="NETWORK_ERROR",
                affected_operation="GET /orders/health",
            ),
        ]
    )
    assert endpoint.primary_classification == "SERVICE_ENDPOINT_FAILURE"
    assert "MULTIPLE_NODES_SAME_SERVICE" in endpoint.reason_codes
    assert endpoint.confidence == 0.95

    flaky = triage_failures([_signal(item_status="passed", attempts=2, error_code=None)])
    assert flaky.primary_classification == "FLAKY"
    assert flaky.retry_signal is True


def test_failure_triage_keeps_product_and_bad_test_as_candidates() -> None:
    result = triage_failures(
        [_signal(assertion_failed=True, response_received=True, http_status=200)]
    )
    assert result.primary_classification == "PRODUCT_DEFECT"
    assert result.secondary_candidates == ["BAD_TEST"]
    assert result.evidence_refs == ["flowtest://runs/run-1/nodes/api-1"]

    cancelled = triage_failures([_signal(item_status="cancelled")])
    assert cancelled.primary_classification == "CANCELLED"

    unknown = triage_failures([])
    assert unknown.primary_classification == "UNKNOWN"
    assert unknown.reason_codes == ["NO_STRUCTURED_FAILURE_EVIDENCE"]
