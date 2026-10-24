"""The three cleanup routes share one bounded, metadata-only removal precondition."""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import Field
from scripts.selftest.contracts import Contract, Identity
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    integer_value,
    object_value,
    text_value,
)


class NamespaceRemovalCondition(Contract):
    expected_nonce: str = Field(min_length=16, max_length=160)
    expected_fixture_epoch: Identity
    expected_registration_epoch: Identity

    def body(self) -> JsonObject:
        return object_value(self.model_dump(mode="json"))


def namespace_condition(
    raw: JsonObject,
    batch_key: str,
    scenario_id: str,
    *,
    nonce: str,
    fixture_digest: str,
    require_idle: bool = True,
) -> NamespaceRemovalCondition | None:
    error = raw.get("error")
    if isinstance(error, dict) and error.get("code") == "FIXTURE_NOT_FOUND":
        return None
    metrics = object_value(raw.get("metrics"))
    active = integer_value(metrics.get("active_count"))
    incomplete_terminal = active == 0 and metrics.get("complete") is not True
    if (
        raw.get("batch_key") != batch_key
        or raw.get("scenario_id") != scenario_id
        or not hmac.compare_digest(text_value(raw.get("nonce")), nonce)
        or not hmac.compare_digest(text_value(raw.get("fixture_digest")), fixture_digest)
        or raw.get("entries") != []
        or not isinstance(metrics.get("complete"), bool)
        or incomplete_terminal
        or active < 0
    ):
        raise HarnessError("SELFTEST_NAMESPACE_OWNERSHIP_OR_ACTIVE_REQUEST_UNKNOWN")
    condition = NamespaceRemovalCondition(
        expected_nonce=nonce,
        expected_fixture_epoch=text_value(raw.get("fixture_epoch")),
        expected_registration_epoch=text_value(raw.get("registration_epoch")),
    )
    if require_idle and active != 0:
        raise HarnessError("SELFTEST_NAMESPACE_ACTIVE_REQUESTS")
    return condition


async def read_namespace_condition(
    observer: PublicAPI,
    batch_key: str,
    scenario_id: str,
    *,
    nonce: str,
    fixture_digest: str,
    wait_for_inactive: bool = False,
    deadline: datetime | None = None,
    reserve_request: Callable[[], None] | None = None,
) -> NamespaceRemovalCondition | None:
    limit = datetime.now(UTC) + timedelta(seconds=5.5)
    if deadline is not None:
        if deadline.tzinfo is None:
            raise HarnessError("SELFTEST_NAMESPACE_CLEANUP_DEADLINE_INVALID")
        limit = min(limit, deadline)
    remaining = (limit - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise HarnessError("SELFTEST_NAMESPACE_CLEANUP_DEADLINE")
    try:
        async with asyncio.timeout(remaining):
            return await _wait_namespace_condition(
                observer,
                batch_key,
                scenario_id,
                nonce=nonce,
                fixture_digest=fixture_digest,
                wait=wait_for_inactive,
                reserve_request=reserve_request,
            )
    except TimeoutError as error:
        raise HarnessError("SELFTEST_NAMESPACE_ACTIVE_REQUESTS_OR_READ_TIMEOUT") from error


async def _wait_namespace_condition(
    observer: PublicAPI,
    batch_key: str,
    scenario_id: str,
    *,
    nonce: str,
    fixture_digest: str,
    wait: bool,
    reserve_request: Callable[[], None] | None,
) -> NamespaceRemovalCondition | None:
    path = f"/selftest/batches/{batch_key}/scenarios/{scenario_id}"
    first: NamespaceRemovalCondition | None = None
    for _ in range(12):
        if reserve_request is not None:
            reserve_request()
        raw = object_value(
            await observer.request(
                "GET",
                path + "/journal?after_sequence=2147483647&limit=1",
                allow_status=(404,),
            )
        )
        condition = namespace_condition(
            raw,
            batch_key,
            scenario_id,
            nonce=nonce,
            fixture_digest=fixture_digest,
            require_idle=False,
        )
        if condition is None:
            return None
        if first is not None and first != condition:
            raise HarnessError("SELFTEST_NAMESPACE_REGISTRATION_CHANGED_DURING_WAIT")
        first = condition
        if integer_value(object_value(raw.get("metrics")).get("active_count")) == 0:
            return condition
        if not wait:
            raise HarnessError("SELFTEST_NAMESPACE_ACTIVE_REQUESTS")
        await asyncio.sleep(0.5)
    raise HarnessError("SELFTEST_NAMESPACE_CLEANUP_READ_BUDGET")
