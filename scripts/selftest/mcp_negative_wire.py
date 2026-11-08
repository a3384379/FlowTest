"""Bounded wire IDs/digests around the locked SDK's actual transport streams."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import uuid4

from mcp.client._transport import ReadStream, WriteStream
from mcp.shared.message import SessionMessage
from mcp_types import JSONRPCError, JSONRPCRequest, JSONRPCResponse
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError
from scripts.selftest.mcp_negative_contracts import RpcRequest, RpcResponse


class WireJournal:
    def __init__(self, reserve_tool: Callable[[], bool] | None = None) -> None:
        self._reserve_tool = reserve_tool
        self.session_id = uuid4()
        self.requests: list[RpcRequest] = []
        self.responses: list[RpcResponse] = []

    def sent(self, item: SessionMessage) -> None:
        message = item.message
        if not isinstance(message, JSONRPCRequest):
            return
        if len(self.requests) >= 100:
            raise HarnessError("SELFTEST_PROTOCOL_REQUEST_BUDGET_EXCEEDED")
        if (
            message.method == "tools/call"
            and self._reserve_tool is not None
            and not self._reserve_tool()
        ):
            raise HarnessError("SELFTEST_PROTOCOL_TOOL_BUDGET_EXCEEDED")
        params = message.params or {}
        tool = params.get("name") if message.method == "tools/call" else None
        arguments = params.get("arguments", {}) if message.method == "tools/call" else None
        self.requests.append(
            RpcRequest(
                session_id=self.session_id,
                id=message.id,
                method=message.method,
                tool_name=tool if isinstance(tool, str) else None,
                arguments_digest=canonical_digest(arguments) if arguments is not None else None,
                observed_at=datetime.now(UTC),
            )
        )

    def received(self, item: SessionMessage | Exception) -> None:
        if isinstance(item, Exception):
            return
        message = item.message
        if len(self.responses) >= 100:
            raise HarnessError("SELFTEST_PROTOCOL_RESPONSE_BUDGET_EXCEEDED")
        if isinstance(message, JSONRPCResponse):
            self.responses.append(
                RpcResponse(
                    session_id=self.session_id,
                    id=message.id,
                    result_digest=canonical_digest(message.result),
                    observed_at=datetime.now(UTC),
                )
            )
        elif isinstance(message, JSONRPCError):
            self.responses.append(
                RpcResponse(
                    session_id=self.session_id,
                    id=message.id,
                    error_code=message.error.code,
                    observed_at=datetime.now(UTC),
                )
            )


class RecordingWrite:
    def __init__(self, inner: WriteStream[SessionMessage], journal: WireJournal) -> None:
        self._inner, self._journal = inner, journal

    async def send(self, item: SessionMessage, /) -> None:
        self._journal.sent(item)
        await self._inner.send(item)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()


class RecordingRead:
    def __init__(self, inner: ReadStream[SessionMessage | Exception], journal: WireJournal) -> None:
        self._inner, self._journal = inner, journal

    async def receive(self) -> SessionMessage | Exception:
        value = await self._inner.receive()
        self._journal.received(value)
        return value

    async def aclose(self) -> None:
        await self._inner.aclose()

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> SessionMessage | Exception:
        import anyio

        try:
            return await self.receive()
        except anyio.EndOfStream:
            raise StopAsyncIteration from None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()
