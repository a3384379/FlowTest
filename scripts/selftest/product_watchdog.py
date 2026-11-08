"""Bounded, resumable cancellation of exactly the expired batch's native runs."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from pydantic import Field
from scripts.selftest.contracts import Contract, Sha256
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import HarnessError, PublicAPI, object_value, read_json, write_json
from scripts.selftest.product_agent_client import agent_root

from app.schemas.self_test_watchdog import WatchdogRequest
from app.schemas.self_tests import BatchResponse


class WatchdogIdentity(Contract):
    manifest_digest: Sha256
    binding_fingerprint: Sha256
    plan_run_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)


class WatchdogState(Contract):
    identity: WatchdogIdentity
    attempts: int = Field(ge=1, le=3)
    status: Literal["pending", "cancel_requested"]
    reason_codes: tuple[str, ...] = Field(default=(), max_length=20)


async def run_expired_watchdogs(
    machine: PublicAPI,
    batches: tuple[BatchResponse, ...],
    directory: Path,
    *,
    writer: PublicAPI | None = None,
    observer: PublicAPI | None = None,
    target_cleanup: PublicAPI | None = None,
) -> None:
    for batch in batches:
        try:
            if batch.phase == "expired" and batch.plan_run_ids and batch.sealed_at is None:
                await _request(machine, batch, directory / str(batch.id) / "watchdog.json")
        finally:
            if writer is not None and observer is not None:
                from scripts.selftest.product_namespace_cleanup import cleanup_owned_namespaces

                await cleanup_owned_namespaces(
                    writer,
                    observer,
                    batch,
                    directory / str(batch.id),
                    target_cleanup=target_cleanup,
                )


async def _request(machine: PublicAPI, batch: BatchResponse, path: Path) -> None:
    identity = WatchdogIdentity(
        manifest_digest=batch.manifest_digest,
        binding_fingerprint=batch.binding_fingerprint,
        plan_run_ids=batch.plan_run_ids,
    )
    previous = WatchdogState.model_validate(read_json(path)) if path.exists() else None
    if previous is not None and previous.identity != identity:
        raise HarnessError("SELFTEST_WATCHDOG_IDENTITY_CHANGED")
    if previous is not None and previous.status == "cancel_requested":
        return
    attempts = previous.attempts if previous is not None else 0
    if attempts >= 3:
        raise HarnessError("SELFTEST_WATCHDOG_CANCELLATION_UNKNOWN")
    pending = WatchdogState(identity=identity, attempts=attempts + 1, status="pending")
    write_json(path, pending)
    try:
        result = BatchResponse.model_validate(
            await machine.object(
                "POST",
                f"{agent_root(batch.project_id)}/runs/{batch.id}/watchdog",
                object_value(
                    WatchdogRequest(
                        manifest_digest=identity.manifest_digest,
                        binding_fingerprint=identity.binding_fingerprint,
                    ).model_dump(mode="json")
                ),
            )
        )
    except httpx.RequestError as error:
        write_json(path, pending.model_copy(update={"reason_codes": failure_codes(error)}))
        return
    except HarnessError as error:
        if not str(error).startswith("SELFTEST_HTTP_503:"):
            raise
        write_json(path, pending.model_copy(update={"reason_codes": failure_codes(error)}))
        return
    if (
        result.id != batch.id
        or result.plan_run_ids != batch.plan_run_ids
        or result.manifest_digest != batch.manifest_digest
        or result.binding_fingerprint != batch.binding_fingerprint
        or result.phase != "expired"
        or result.verdict != "blocked"
    ):
        raise HarnessError("SELFTEST_WATCHDOG_RECEIPT_INVALID")
    # This acknowledges a cancellation request only; it never claims terminal
    # execution, complete cleanup, a passed observer, or a new business run.
    write_json(path, pending.model_copy(update={"status": "cancel_requested"}))
