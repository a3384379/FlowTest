"""A single admission counter covers H public calls; native and MCP reserves stay explicit."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from pydantic import JsonValue
from scripts.selftest.io import HarnessError, JsonObject, PublicAPI
from scripts.selftest.mcp_protocol_runner import ProtocolClient


class BadTargetsBudget:
    def __init__(self, deadline: datetime) -> None:
        remaining = (deadline - datetime.now(UTC)).total_seconds() if deadline.tzinfo else -1
        if not 0 < remaining <= 600:
            raise HarnessError("SELFTEST_BADTARGET_DEADLINE_INVALID")
        self.deadline = deadline
        self.attempts = 0

    def remaining(self) -> float:
        remaining = (self.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise HarnessError("SELFTEST_BADTARGET_HTTP_BUDGET_OR_DEADLINE")
        return remaining

    def admit(self) -> None:
        if datetime.now(UTC) >= self.deadline or self.attempts >= 392:
            raise HarnessError("SELFTEST_BADTARGET_HTTP_BUDGET_OR_DEADLINE")
        self.attempts += 1


class BoundedBadTargetAPI(PublicAPI):
    """Delegate credentials untouched; receipts contain counts rather than request payloads."""

    def __init__(self, delegate: PublicAPI, budget: BadTargetsBudget) -> None:
        self._delegate, self._budget = delegate, budget

    async def request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        idempotency_key: str | None = None,
        allow_status: tuple[int, ...] = (),
    ) -> JsonValue:
        self._budget.admit()
        async with asyncio.timeout(self._budget.remaining()):
            return await self._delegate.request(
                method,
                path,
                payload,
                idempotency_key=idempotency_key,
                allow_status=allow_status,
            )

    async def object(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        self._budget.admit()
        async with asyncio.timeout(self._budget.remaining()):
            return await self._delegate.object(
                method, path, payload, idempotency_key=idempotency_key
            )


class BoundedBadTargetProtocol(ProtocolClient):
    """Use the original SDK session/receipts and its one shared 100-tool admission cap."""

    def __init__(self, delegate: ProtocolClient, budget: BadTargetsBudget) -> None:
        self._delegate, self._budget = delegate, budget
        self.batch_key = delegate.batch_key
        self.catalog_digest = delegate.catalog_digest
        self.receipts = delegate.receipts

    @property
    def attempt_count(self) -> int:
        return self._delegate.attempt_count

    @attempt_count.setter
    def attempt_count(self, value: int) -> None:
        self._delegate.attempt_count = value

    async def call(
        self,
        tool_name: str,
        arguments: JsonObject,
        *,
        scenario_id: str,
        phase: str,
    ) -> JsonObject:
        if self._delegate.max_tool_calls > 100:
            raise HarnessError("SELFTEST_BADTARGET_TOOL_BUDGET_INVALID")
        async with asyncio.timeout(self._budget.remaining()):
            return await self._delegate.call(
                tool_name, arguments, scenario_id=scenario_id, phase=phase
            )
