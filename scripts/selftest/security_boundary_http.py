"""Bounded owned-fixture HTTP; credentials and response payloads never become receipts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
from pydantic import JsonValue
from scripts.selftest.io import HarnessError, JsonObject, PublicAPI
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget


class BoundaryAPI(PublicAPI):
    def __init__(
        self,
        url: str,
        budget: ProtocolHttpBudget,
        deadline: datetime,
        token: str = "",
        organization: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(url, token, organization, transport=transport)
        self.budget, self.deadline = budget, deadline

    def _reserve(self) -> float:
        remaining = (self.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0 or not self.budget.reserve():
            raise HarnessError("SELFTEST_SECURITY_HTTP_BUDGET_OR_DEADLINE")
        return remaining

    async def request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        idempotency_key: str | None = None,
        allow_status: tuple[int, ...] = (),
    ) -> JsonValue:
        async with asyncio.timeout(self._reserve()):
            return await super().request(
                method, path, payload, idempotency_key=idempotency_key, allow_status=allow_status
            )

    async def probe(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        access_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        headers = self._headers(idempotency_key)
        if access_token is not None:
            headers["Authorization"] = "Bearer " + access_token
        async with asyncio.timeout(self._reserve()):
            response = await self._client.request(
                method, path.lstrip("/"), json=payload, headers=headers
            )
        if len(response.content) > 262144:
            raise HarnessError("SELFTEST_SECURITY_RESPONSE_TOO_LARGE")
        return response

    async def upload_synthetic(self, path: str, filename: str, content: bytes) -> JsonObject:
        async with asyncio.timeout(self._reserve()):
            return await super().upload_synthetic(path, filename, content)
