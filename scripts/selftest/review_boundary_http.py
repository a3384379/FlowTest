"""Record bounded HTTP metadata; one explicit loss discards the publication body."""

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import uuid4

from pydantic import JsonValue
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, JsonObject, object_value
from scripts.selftest.review_boundary_contracts import ReviewHTTPReceipt
from scripts.selftest.security_boundary_http import BoundaryAPI


class UnknownReviewResult(Exception):
    """The server response body was deliberately lost before exposing it to the driver."""


class ReviewHTTPUnexpected(HarnessError):
    def __init__(self, receipt: ReviewHTTPReceipt) -> None:
        self.receipt = receipt
        super().__init__(
            f"SELFTEST_REVIEW_HTTP_{receipt.step}_{receipt.status}_{receipt.code or 'UNKNOWN'}"
        )


class ReviewAPI(BoundaryAPI):
    async def action(
        self,
        step: str,
        method: Literal["GET", "POST", "PUT", "PATCH"],
        path: str,
        payload: JsonObject | None = None,
        *,
        expected: tuple[int, ...] = (200,),
        lose_body: bool = False,
    ) -> tuple[JsonValue, ReviewHTTPReceipt]:
        started = datetime.now(UTC)
        async with asyncio.timeout(self._reserve()):
            response = await self._client.request(
                method, path.lstrip("/"), json=payload, headers=self._headers()
            )
        if len(response.content) > 262144:
            raise HarnessError("SELFTEST_REVIEW_HTTP_RESPONSE_TOO_LARGE")
        returned = {} if lose_body else cast(JsonValue, response.json())
        error = object_value(returned.get("error", {})) if isinstance(returned, dict) else {}
        receipt = ReviewHTTPReceipt(
            id=uuid4(),
            step=step,
            method=method,
            path=path,
            request_digest=canonical_digest(payload),
            status=response.status_code,
            code=error.get("code"),
            trace_present=bool(error.get("trace_id")),
            outcome="lost_response_body" if lose_body else "received",
            response_digest=None if lose_body else hashlib.sha256(response.content).hexdigest(),
            started_at=started,
            completed_at=datetime.now(UTC),
        )
        if response.status_code not in expected:
            raise ReviewHTTPUnexpected(receipt)
        if lose_body:
            return {}, receipt
        return returned, receipt
