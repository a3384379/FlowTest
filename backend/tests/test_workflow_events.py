from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.v1.endpoints import workflow_events
from app.api.v1.endpoints.workflow_events import websocket_access_token, websocket_after_sequence
from app.services.execution_events import ExecutionEvent, ExecutionEventType


def test_websocket_access_token_uses_dedicated_subprotocol() -> None:
    assert (
        websocket_access_token("flowtest.events.v1, flowtest.token.header.payload.signature")
        == "header.payload.signature"
    )
    assert websocket_access_token("flowtest.events.v1") is None
    assert websocket_access_token("flowtest.token.") is None
    assert websocket_access_token(None) is None


def test_websocket_event_cursor_rejects_invalid_and_oversized_values() -> None:
    assert websocket_after_sequence(None) == 0
    assert websocket_after_sequence("0") == 0
    assert websocket_after_sequence("42") == 42
    assert websocket_after_sequence("-1") is None
    assert websocket_after_sequence("12x") is None
    assert websocket_after_sequence("\uff11\uff12") is None
    assert websocket_after_sequence("9223372036854775808") is None


@pytest.mark.asyncio
async def test_websocket_replays_after_cursor_and_closes_completed_runs(monkeypatch) -> None:
    execution_id = uuid4()
    event = ExecutionEvent(
        sequence=4,
        type=ExecutionEventType.EXECUTION_COMPLETED,
        execution_id=execution_id,
        emitted_at=datetime.now(UTC),
        execution_status="passed",
    )
    bus = _EventBus(event)
    monkeypatch.setattr(workflow_events, "_event_bus", lambda _socket: bus)

    async def authorize(_socket, _execution_id, _token):
        return SimpleNamespace(status="running")

    monkeypatch.setattr(workflow_events, "_authorize", authorize)
    socket = _Socket("3")
    await workflow_events.workflow_execution_events(socket, execution_id)
    assert bus.after_sequence == 3
    assert socket.accepted
    assert socket.sent == [event.model_dump_json()]
    assert socket.closed_code == 1000

    async def completed(_socket, _execution_id, _token):
        return SimpleNamespace(status="passed")

    monkeypatch.setattr(workflow_events, "_authorize", completed)
    terminal_socket = _Socket("4")
    await workflow_events.workflow_execution_events(terminal_socket, execution_id)
    assert terminal_socket.accepted
    assert terminal_socket.sent == []
    assert terminal_socket.closed_code == 1000

    invalid_socket = _Socket("bad")
    await workflow_events.workflow_execution_events(invalid_socket, execution_id)
    assert not invalid_socket.accepted
    assert invalid_socket.closed_code == 4400


class _Socket:
    def __init__(self, cursor: str) -> None:
        self.headers = {"sec-websocket-protocol": "flowtest.events.v1, flowtest.token.test"}
        self.query_params = {"after_sequence": cursor}
        self.accepted = False
        self.closed_code: int | None = None
        self.sent: list[str] = []

    async def accept(self, *, subprotocol: str) -> None:
        assert subprotocol == "flowtest.events.v1"
        self.accepted = True

    async def send_text(self, value: str) -> None:
        self.sent.append(value)

    async def close(self, *, code: int, reason: str = "") -> None:
        self.closed_code = code


class _EventBus:
    def __init__(self, event: ExecutionEvent) -> None:
        self.event = event
        self.after_sequence: int | None = None

    async def subscribe(self, _execution_id, *, after_sequence: int = 0):
        self.after_sequence = after_sequence
        yield self.event


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
