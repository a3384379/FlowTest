from datetime import UTC, datetime
from uuid import uuid4

from app.api.v1.endpoints.workflow_events import websocket_access_token
from app.services.execution_events import ExecutionEvent, ExecutionEventType


def test_websocket_access_token_uses_dedicated_subprotocol() -> None:
    assert (
        websocket_access_token("flowtest.events.v1, flowtest.token.header.payload.signature")
        == "header.payload.signature"
    )
    assert websocket_access_token("flowtest.events.v1") is None
    assert websocket_access_token("flowtest.token.") is None
    assert websocket_access_token(None) is None


def test_execution_event_serialization_is_explicit() -> None:
    execution_id = uuid4()
    event = ExecutionEvent(
        sequence=3,
        type=ExecutionEventType.NODE_STATUS,
        execution_id=execution_id,
        emitted_at=datetime.now(UTC),
        node_id="api",
        node_name="查询用户",
        node_type="api",
        node_status="running",
    )

    restored = ExecutionEvent.model_validate_json(event.model_dump_json())

    assert restored.execution_id == execution_id
    assert restored.node_status == "running"
    assert restored.sequence == 3
