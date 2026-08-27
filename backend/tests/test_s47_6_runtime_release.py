"""S47.6 runtime release-evidence golden tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.change_regression import (
    OperationIdentity,
    SemanticCoverageFact,
    oracle_set_fingerprint,
)
from app.engine.results import (
    HttpRequestSnapshot,
    HttpResponseSnapshot,
    NodeObservation,
    NodeResult,
)
from app.models.workflows import WorkflowNodeExecution
from app.services.change_regression import _runtime_fact_is_covered


def _identity() -> OperationIdentity:
    return OperationIdentity(
        api_definition_id="00000000-0000-0000-0000-000000000001",
        api_version=2,
        portable_operation_ref="orders.create",
        service_key="orders",
        method="POST",
        normalized_path="/tenants/{}/orders",
        contract_fingerprint="a" * 64,
    )


def _fact(
    *,
    location: str = "body",
    field_path: str = "quantity",
    semantic_value: str = "1000",
    oracle_identities: tuple[str, ...] = ("status:422",),
    oracle_node_ids: tuple[str, ...] = (),
) -> SemanticCoverageFact:
    return SemanticCoverageFact.model_validate(
        {
            "operation_identity": _identity(),
            "request_location": location,
            "field_path": field_path,
            "semantic_value": semantic_value,
            "scenario_kind": "number_above_max",
            "expected_category": "invalid_request",
            "oracle_identities": oracle_identities,
            "oracle_set_fingerprint": oracle_set_fingerprint(oracle_identities),
            "source_asset_type": "workflow",
            "source_asset_id": "workflow-1",
            "source_asset_version": 3,
            "workflow_version": 3,
            "request_node_id": "request",
            "request_path_template": "/tenants/{tenant_id}/orders",
            "oracle_node_ids": oracle_node_ids,
        }
    )


def _api_node(
    *,
    status: str = "passed",
    url: str = "https://orders.example.test/tenants/t-1/orders?page=2",
    headers: dict[str, str] | None = None,
    body: object = None,
    response_status: int = 422,
) -> WorkflowNodeExecution:
    now = datetime.now(UTC)
    observation = NodeObservation(
        attempt=1,
        request=HttpRequestSnapshot(
            method="POST",
            url=url,
            headers=headers or {},
            body=body,
            service_key="orders",
        ),
        response=HttpResponseSnapshot(
            status_code=response_status,
            headers={},
            body={"error": "invalid"},
            size_bytes=19,
        ),
        duration_ms=1,
        started_at=now,
        completed_at=now,
    )
    result = NodeResult.passed({}, observations=(observation,))
    return WorkflowNodeExecution(
        id=uuid4(),
        workflow_execution_id=uuid4(),
        node_id="request",
        node_type="api",
        name="Request",
        status=status,
        attempts=1,
        output={},
        result=result.model_dump(mode="json"),
        completed_at=now,
    )


def _assert_node(*, status: str = "passed") -> WorkflowNodeExecution:
    now = datetime.now(UTC)
    result = NodeResult.passed(
        {
            "passed": True,
            "source_node_id": "request",
            "expression": "body",
            "operator": "equals",
        }
    )
    return WorkflowNodeExecution(
        id=uuid4(),
        workflow_execution_id=uuid4(),
        node_id="assert-schema",
        node_type="assert",
        name="Schema assert",
        status=status,
        attempts=1,
        output=result.output,
        result=result.model_dump(mode="json"),
        completed_at=now,
    )


def test_runtime_release_coverage_requires_actual_value_and_status_oracle() -> None:
    fact = _fact()

    assert _runtime_fact_is_covered(fact, [_api_node(body={"quantity": 1000})])
    assert not _runtime_fact_is_covered(fact, [_api_node(body={"quantity": 999})])
    assert not _runtime_fact_is_covered(
        fact,
        [_api_node(body={"quantity": 1000}, response_status=400)],
    )


def test_skipped_request_and_skipped_assert_do_not_form_release_coverage() -> None:
    direct = _fact()
    schema = _fact(
        oracle_identities=("status:422", "schema:" + "b" * 64),
        oracle_node_ids=("assert-schema",),
    )
    request = _api_node(body={"quantity": 1000})

    assert not _runtime_fact_is_covered(
        direct,
        [_api_node(status="skipped", body={"quantity": 1000})],
    )
    assert not _runtime_fact_is_covered(schema, [request, _assert_node(status="skipped")])
    assert _runtime_fact_is_covered(schema, [request, _assert_node()])


@pytest.mark.parametrize(
    ("location", "field_path", "semantic_value", "node"),
    [
        ("path", "tenant_id", '"t-1"', _api_node(body={})),
        ("query", "page", "2", _api_node(body={})),
        (
            "header",
            "X-Mode",
            '"strict"',
            _api_node(headers={"x-mode": "strict"}, body={}),
        ),
        (
            "cookie",
            "region",
            '"cn"',
            _api_node(headers={"Cookie": "region=cn"}, body={}),
        ),
    ],
)
def test_runtime_release_coverage_reads_final_request_locations(
    location: str,
    field_path: str,
    semantic_value: str,
    node: WorkflowNodeExecution,
) -> None:
    assert _runtime_fact_is_covered(
        _fact(location=location, field_path=field_path, semantic_value=semantic_value),
        [node],
    )
