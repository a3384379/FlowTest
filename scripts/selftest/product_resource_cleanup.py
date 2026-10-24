"""H-only cleanup of a pre-armed B lifecycle namespace after native termination."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from pydantic import Field, JsonValue
from scripts.selftest.cleanup import OwnedEnvironment
from scripts.selftest.contracts import Contract, Identity, Sha256, canonical_digest
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    object_value,
    objects_value,
    read_json,
    write_json,
)

from app.schemas.self_tests import AgentTaskResponse, AssistedBeforeSource, BatchResponse

type CleanupRequest = Callable[[PublicAPI, str, str, JsonObject | None], Awaitable[JsonValue]]


class LifecycleIdentity(Contract):
    batch_id: UUID
    project_id: UUID
    target_project_id: UUID
    creator_id: UUID
    manifest_digest: Sha256
    binding_fingerprint: Sha256
    nonce_digest: Sha256
    naming_batch_key: Identity
    names: tuple[Identity, Identity]


class LifecycleArm(Contract):
    identity: LifecycleIdentity
    armed_at: datetime
    initial_absence_confirmed: Literal[True] = True


class LifecycleCleanup(Contract):
    identity: LifecycleIdentity
    status: Literal["pending", "completed", "needs_review"] = "pending"
    registered_resource: OwnedEnvironment | None = None
    delete_requested: bool = False
    reason_codes: tuple[Identity, ...] = Field(default=(), max_length=20)
    independent_verification: Literal["not_performed"] = "not_performed"
    attempt: int = Field(default=1, ge=1, le=3)


def _checked_projection(item: AssistedBeforeSource) -> None:
    if (
        item.source_digest != canonical_digest(object_value(item.source.model_dump(mode="json")))
        or item.evidence_integrity != "complete"
        or item.cleanup_status != "completed"
        or item.resource_digest is None
        or item.sealed_at.tzinfo is None
        or (item.scenario_id, item.variant_key)
        != (item.source.scenario_id, item.source.variant_key)
    ):
        raise HarnessError("SELFTEST_RESOURCE_BEFORE_SOURCE_UNPROVEN")


def _naming_key(task: AgentTaskResponse, variant: str) -> str:
    batch, frozen = task.batch, task.frozen_manifest
    if batch is None or frozen is None:
        raise HarnessError("SELFTEST_RESOURCE_FROZEN_TASK_MISSING")
    if (
        frozen.batch_id != batch.id
        or frozen.project_id != batch.project_id
        or canonical_digest(object_value(frozen.model_dump(mode="json"))) != batch.manifest_digest
    ):
        raise HarnessError("SELFTEST_RESOURCE_FROZEN_IDENTITY_MISMATCH")
    before_id = frozen.assisted_before_batch_id
    if before_id is None:
        if task.before_sources:
            raise HarnessError("SELFTEST_RESOURCE_BEFORE_SOURCE_UNEXPECTED")
        return batch.batch_key
    candidates = [
        item
        for item in task.before_sources
        if item.batch_id == before_id
        and (item.scenario_id, item.variant_key) == ("ST-MCP-023", variant)
    ]
    if len(candidates) != 1:
        raise HarnessError("SELFTEST_RESOURCE_BEFORE_SOURCE_MISSING")
    before = candidates[0]
    _checked_projection(before)
    origin_id = (
        before.batch_id
        if before.source.assisted is None
        else before.source.assisted.origin_batch_id
    )
    origins = [
        item
        for item in task.before_sources
        if item.batch_id == origin_id
        and (item.scenario_id, item.variant_key) == ("ST-MCP-023", variant)
    ]
    if len(origins) != 1:
        raise HarnessError("SELFTEST_RESOURCE_ORIGIN_SOURCE_MISSING")
    origin = origins[0]
    _checked_projection(origin)
    if origin.source.assisted is not None or origin.source.fixture_batch_key is not None:
        raise HarnessError("SELFTEST_RESOURCE_ORIGIN_SOURCE_INVALID")
    return origin.batch_key


def lifecycle_identity(task: AgentTaskResponse) -> LifecycleIdentity | None:
    batch, mapping = task.batch, task.installation.mapping
    if batch is None:
        raise HarnessError("SELFTEST_RESOURCE_FROZEN_TASK_MISSING")
    variants = [
        item.variant_key for item in batch.expected_scenario_set if item.scenario_id == "ST-MCP-023"
    ]
    if not variants:
        return None
    if len(variants) != 1 or mapping is None:
        raise HarnessError("SELFTEST_RESOURCE_TARGET_MAPPING_INVALID")
    key = _naming_key(task, variants[0])
    names = (f"{key}-created", f"{key}-updated")
    if any(len(name) > 160 for name in names):
        raise HarnessError("SELFTEST_RESOURCE_NAMESPACE_TOO_LONG")
    return LifecycleIdentity(
        batch_id=batch.id,
        project_id=batch.project_id,
        target_project_id=mapping.target_project_id,
        creator_id=mapping.target_user_id,
        manifest_digest=batch.manifest_digest,
        binding_fingerprint=batch.binding_fingerprint,
        nonce_digest=canonical_digest(task.nonce),
        naming_batch_key=key,
        names=names,
    )


def _private_model(path: Path, model: type[LifecycleArm]) -> LifecycleArm:
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise HarnessError("SELFTEST_RESOURCE_ARM_PRIVATE_STATE_MISSING")
    return model.model_validate(read_json(path))


def _environments(raw: JsonValue, project_id: UUID) -> tuple[OwnedEnvironment, ...]:
    items = objects_value(raw)
    if len(items) > 1000:
        raise HarnessError("SELFTEST_RESOURCE_LIST_BUDGET")
    rows = tuple(
        OwnedEnvironment.model_validate(
            {
                key: item.get(key)
                for key in ("id", "project_id", "name", "created_by_id", "created_at")
            }
        )
        for item in items
    )
    if len(rows) != len({row.id for row in rows}) or any(
        row.project_id != project_id for row in rows
    ):
        raise HarnessError("SELFTEST_RESOURCE_LIST_INCOMPLETE_OR_CROSS_PROJECT")
    return rows


async def arm_owned_lifecycle(
    task: AgentTaskResponse, target_reader: PublicAPI | None, directory: Path
) -> None:
    identity = lifecycle_identity(task)
    if identity is None:
        return
    path = directory / "lifecycle-arm.json"
    if path.exists():
        if _private_model(path, LifecycleArm).identity != identity:
            raise HarnessError("SELFTEST_RESOURCE_ARM_IDENTITY_CHANGED")
        return
    if (
        task.batch is None
        or task.batch.plan_run_ids
        or task.task_kind not in {"generation", "preparation"}
    ):
        raise HarnessError("SELFTEST_RESOURCE_ARM_AFTER_DISPATCH_OR_WRONG_ROLE")
    if target_reader is None:
        raise HarnessError("SELFTEST_RESOURCE_CLEANUP_IDENTITY_REQUIRED")
    armed_at = datetime.now(UTC)
    rows = _environments(
        await target_reader.request("GET", f"/projects/{identity.target_project_id}/environments"),
        identity.target_project_id,
    )
    if any(row.name in identity.names for row in rows):
        raise HarnessError("SELFTEST_RESOURCE_NAMESPACE_ALREADY_EXISTS")
    write_json(path, LifecycleArm(identity=identity, armed_at=armed_at))


class LifecycleCleaner:
    def __init__(
        self,
        task: AgentTaskResponse,
        arm: LifecycleArm,
        target: PublicAPI,
        directory: Path,
        request: CleanupRequest,
        attempt: int,
    ) -> None:
        self.arm, self.target, self.directory, self.request, self.attempt = (
            arm,
            target,
            directory,
            request,
            attempt,
        )
        self.path = directory / "lifecycle-cleanup.json"
        self.state = (
            LifecycleCleanup.model_validate(read_json(self.path))
            if self.path.exists()
            else LifecycleCleanup(identity=arm.identity)
        )
        if self.state.identity != lifecycle_identity(task):
            raise HarnessError("SELFTEST_RESOURCE_CLEANUP_IDENTITY_CHANGED")
        if self.path.exists():
            self.archive()
        self.state = self.state.model_copy(update={"attempt": attempt})

    async def rows(self) -> tuple[OwnedEnvironment, ...]:
        identity = self.arm.identity
        return _environments(
            await self.request(
                self.target, "GET", f"/projects/{identity.target_project_id}/environments", None
            ),
            identity.target_project_id,
        )

    def save(self) -> None:
        write_json(self.path, self.state)

    def archive(self) -> None:
        path = self.path.with_name(f"lifecycle-cleanup-attempt-{self.state.attempt}.json")
        if not path.exists():
            write_json(path, self.state)

    def select(self, rows: tuple[OwnedEnvironment, ...]) -> OwnedEnvironment | None:
        identity, previous = self.arm.identity, self.state.registered_resource
        selected = [
            row
            for row in rows
            if row.name in identity.names or (previous is not None and row.id == previous.id)
        ]
        if not selected:
            return None
        if len(selected) != 1:
            raise HarnessError("SELFTEST_RESOURCE_OWNERSHIP_AMBIGUOUS")
        owned = selected[0]
        if (
            owned.name not in identity.names
            or owned.created_by_id != identity.creator_id
            or owned.created_at.tzinfo is None
        ):
            raise HarnessError("SELFTEST_RESOURCE_OWNERSHIP_UNPROVEN")
        # SQLite's public database timestamps have whole-second precision. The
        # complete pre-launch absence proof still excludes pre-existing rows.
        earliest = self.arm.armed_at.replace(microsecond=0)
        if not earliest <= owned.created_at <= datetime.now(UTC):
            raise HarnessError("SELFTEST_RESOURCE_CREATED_OUTSIDE_ARMING_WINDOW")
        if previous is not None and previous != owned:
            raise HarnessError("SELFTEST_RESOURCE_IDENTITY_CHANGED")
        return owned

    async def finish(self) -> None:
        if self.state.status == "completed":
            return
        try:
            await self.remove()
            self.state = self.state.model_copy(update={"status": "completed", "reason_codes": ()})
        except (HarnessError, httpx.HTTPError, ValueError, OSError) as error:
            self.state = self.state.model_copy(
                update={"status": "needs_review", "reason_codes": failure_codes(error)}
            )
            self.save()
            self.archive()
            raise
        except asyncio.CancelledError:
            self.state = self.state.model_copy(
                update={
                    "status": "needs_review",
                    "reason_codes": ("SELFTEST_RESOURCE_CLEANUP_INTERRUPTED",),
                }
            )
            self.save()
            self.archive()
            raise
        self.save()
        self.archive()

    async def remove(self) -> None:
        owned = self.select(await self.rows())
        if owned is None:
            return
        if self.state.delete_requested:
            raise HarnessError("SELFTEST_RESOURCE_DELETE_RESULT_UNKNOWN")
        self.state = self.state.model_copy(update={"registered_resource": owned})
        self.save()
        if self.select(await self.rows()) != owned:
            raise HarnessError("SELFTEST_RESOURCE_CHANGED_BEFORE_DELETE")
        self.state = self.state.model_copy(update={"delete_requested": True})
        self.save()
        await self.request(
            self.target, "DELETE", f"/projects/{owned.project_id}/environments/{owned.id}", None
        )
        if self.select(await self.rows()) is not None:
            raise HarnessError("SELFTEST_RESOURCE_DELETE_NOT_CONFIRMED")


async def cleanup_owned_lifecycle(
    task: AgentTaskResponse,
    batch: BatchResponse,
    target: PublicAPI | None,
    directory: Path,
    request: CleanupRequest,
    attempt: int,
) -> None:
    identity = lifecycle_identity(task)
    if identity is None:
        return
    path = directory / "lifecycle-arm.json"
    if not batch.plan_run_ids and not path.exists():
        return
    arm = _private_model(path, LifecycleArm)
    if arm.identity != identity or target is None or arm.armed_at.tzinfo is None:
        raise HarnessError("SELFTEST_RESOURCE_ARM_OR_CLEANUP_IDENTITY_INVALID")
    await LifecycleCleaner(task, arm, target, directory, request, attempt).finish()
