"""H-only reclamation of proven owned Mock namespaces; never an O cleanup verdict."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from pydantic import Field, JsonValue, ValidationError
from scripts.selftest.contracts import Contract, Identity, Sha256, canonical_digest
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    object_value,
    read_json,
    write_json,
)
from scripts.selftest.namespace_conditions import NamespaceRemovalCondition, namespace_condition
from scripts.selftest.namespace_sources import frozen_namespace_keys
from scripts.selftest.product_resource_cleanup import cleanup_owned_lifecycle

from app.schemas.self_tests import AgentTaskResponse, BatchResponse, GenerationSummary
from app.schemas.tasking import TestPlanRunDetailResponse
from app.schemas.workflows import WorkflowExecutionDetailResponse


class NamespaceIdentity(Contract):
    batch_id: UUID
    project_id: UUID
    batch_key: Identity
    manifest_digest: Sha256
    binding_fingerprint: Sha256
    nonce_digest: Sha256
    fixture_digest: Identity
    scenarios: tuple[Identity, ...] = Field(min_length=1, max_length=100)


class NamespaceState(Contract):
    scenario_id: Identity
    namespace_batch_key: Identity | None = None
    epoch: Identity | None = None
    registration_epoch: Identity | None = None
    delete_requested: bool = False
    status: Literal["pending", "completed", "needs_review"] = "pending"
    reason_codes: tuple[Identity, ...] = ()


class NamespaceCleanupReceipt(Contract):
    schema_version: Literal["flowtest-h-namespace-cleanup-v1"] = "flowtest-h-namespace-cleanup-v1"
    identity: NamespaceIdentity
    status: Literal["pending", "completed", "needs_review"]
    namespaces: tuple[NamespaceState, ...] = Field(max_length=100)
    reason_codes: tuple[Identity, ...] = ()
    observed_at: datetime
    independent_verification: Literal["not_performed"] = "not_performed"
    attempts: int = Field(default=0, ge=0, le=3)
    admitted_requests: int = Field(default=0, ge=0, le=100)


class BlockedNamespaceCleanup(Contract):
    batch_id: UUID
    reason_codes: tuple[Identity, ...]


def _owned_task(batch: BatchResponse, directory: Path) -> AgentTaskResponse:
    path = directory / "private-lease.json"
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise HarnessError("SELFTEST_NAMESPACE_PRIVATE_STATE_MISSING")
    task = AgentTaskResponse.model_validate(read_json(path))
    original, frozen = task.batch, task.frozen_manifest
    if original is None or frozen is None:
        raise HarnessError("SELFTEST_NAMESPACE_FROZEN_STATE_MISSING")
    fields = (
        "id",
        "project_id",
        "binding_id",
        "batch_key",
        "manifest_digest",
        "binding_fingerprint",
        "policy_digest",
        "builds",
        "expected_scenario_set",
    )
    if (
        task.task_id != batch.id
        or task.project_id != batch.project_id
        or task.binding_id != batch.binding_id
        or task.binding_fingerprint != batch.binding_fingerprint
        or task.builds != batch.builds
        or any(getattr(original, key) != getattr(batch, key) for key in fields)
        or canonical_digest(frozen.model_dump(mode="json")) != batch.manifest_digest
    ):
        raise HarnessError("SELFTEST_NAMESPACE_FROZEN_IDENTITY_MISMATCH")
    return task


class NamespaceCleaner:
    def __init__(
        self,
        writer: PublicAPI,
        observer: PublicAPI,
        batch: BatchResponse,
        task: AgentTaskResponse,
        path: Path,
        target_cleanup: PublicAPI | None = None,
    ) -> None:
        self.writer, self.observer, self.batch, self.task, self.path = (
            writer,
            observer,
            batch,
            task,
            path,
        )
        self.requests = 0
        self.target_cleanup = target_cleanup
        self.executions: set[UUID] = set()
        self.identity = NamespaceIdentity(
            batch_id=batch.id,
            project_id=batch.project_id,
            batch_key=batch.batch_key,
            manifest_digest=batch.manifest_digest,
            binding_fingerprint=batch.binding_fingerprint,
            nonce_digest=canonical_digest(task.nonce),
            fixture_digest=task.builds.fixture,
            scenarios=tuple(
                dict.fromkeys(item.scenario_id for item in batch.expected_scenario_set)
            ),
        )
        previous = (
            NamespaceCleanupReceipt.model_validate(read_json(path)) if path.exists() else None
        )
        if previous is not None and previous.identity != self.identity:
            raise HarnessError("SELFTEST_NAMESPACE_CLEANUP_IDENTITY_CHANGED")
        self.receipt = previous or NamespaceCleanupReceipt(
            identity=self.identity,
            status="pending",
            observed_at=datetime.now(UTC),
            namespaces=tuple(NamespaceState(scenario_id=sid) for sid in self.identity.scenarios),
        )
        self.requests = self.receipt.admitted_requests

    async def request(
        self,
        api: PublicAPI,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        missing: bool = False,
    ) -> JsonValue:
        if self.requests >= 100:
            raise HarnessError("SELFTEST_NAMESPACE_CLEANUP_REQUEST_BUDGET")
        self.requests += 1
        self.receipt = self.receipt.model_copy(update={"admitted_requests": self.requests})
        write_json(self.path, self.receipt)
        return await api.request(method, path, payload, allow_status=(404,) if missing else ())

    async def stopped(self) -> None:
        batch = self.batch
        snapshot = batch.resource_snapshot
        if batch.plan_run_ids and snapshot is None:
            raise HarnessError("SELFTEST_NAMESPACE_NATIVE_SNAPSHOT_MISSING")
        targets = () if snapshot is None else tuple(item.case.id for item in snapshot.cases)
        for identifier in batch.plan_run_ids:
            raw = await self.request(
                self.writer, "GET", f"/projects/{batch.project_id}/test-plan-runs/{identifier}"
            )
            _complete_projection(object_value(raw), "items")
            detail = TestPlanRunDetailResponse.model_validate(raw)
            if (
                detail.run.id != identifier
                or detail.run.project_id != batch.project_id
                or detail.run.test_plan_id != batch.plan_id
                or detail.run.status not in {"passed", "failed", "cancelled"}
                or sorted(item.target_id for item in detail.items) != sorted(targets)
            ):
                raise HarnessError("SELFTEST_NAMESPACE_NATIVE_RUN_NOT_TERMINAL")
            await self._attempts(detail)
        latest = BatchResponse.model_validate(
            await self.request(
                self.writer, "GET", f"/projects/{batch.project_id}/self-tests/runs/{batch.id}"
            )
        )
        if (
            latest.phase not in {"cancelled", "expired"}
            or latest.plan_run_ids != batch.plan_run_ids
            or latest.manifest_digest != batch.manifest_digest
        ):
            raise HarnessError("SELFTEST_NAMESPACE_NATIVE_DISPATCH_UNKNOWN")

    async def _attempts(self, detail: TestPlanRunDetailResponse) -> None:
        for item in detail.items:
            if item.status not in {"passed", "failed", "cancelled", "quarantined"}:
                raise HarnessError("SELFTEST_NAMESPACE_NATIVE_ITEM_NOT_TERMINAL")
            if item.attempts > 1 or (item.attempts == 0) != (item.workflow_execution_id is None):
                raise HarnessError("SELFTEST_NAMESPACE_NATIVE_ATTEMPTS_UNKNOWN")
            if item.workflow_execution_id is not None:
                await self._execution(
                    item.workflow_execution_id, item.workflow_id, parent=None, depth=0
                )

    async def _execution(
        self, identifier: UUID, workflow: UUID | None, *, parent: UUID | None, depth: int
    ) -> None:
        if depth > 10 or identifier in self.executions:
            raise HarnessError("SELFTEST_NAMESPACE_NATIVE_LINEAGE_LIMIT")
        self.executions.add(identifier)
        raw = await self.request(
            self.writer,
            "GET",
            f"/projects/{self.batch.project_id}/workflow-executions/{identifier}?compact_control=true",
        )
        _complete_projection(object_value(raw), "children")
        detail = WorkflowExecutionDetailResponse.model_validate(raw)
        execution = detail.execution
        if (
            execution.id != identifier
            or execution.project_id != self.batch.project_id
            or execution.workflow_id != workflow
            or execution.parent_execution_id != parent
            or execution.status not in {"passed", "failed", "cancelled"}
            or len(detail.children) > 100
            or any(node.status == "running" for node in detail.nodes)
        ):
            raise HarnessError("SELFTEST_NAMESPACE_NATIVE_EXECUTION_NOT_TERMINAL")
        for child in detail.children:
            await self._execution(child.id, child.workflow_id, parent=identifier, depth=depth + 1)

    def save(self, index: int, state: NamespaceState) -> None:
        rows = list(self.receipt.namespaces)
        rows[index] = state
        self.receipt = self.receipt.model_copy(
            update={"namespaces": tuple(rows), "observed_at": datetime.now(UTC)}
        )
        write_json(self.path, self.receipt)

    async def resolve_sources(self) -> None:
        if self.batch.batch_kind != "mcp_generated" or (
            not self.task.before_sources and self.batch.resource_digest is None
        ):
            return
        raw = await self.request(
            self.writer,
            "GET",
            f"/projects/{self.batch.project_id}/self-tests/runs/{self.batch.id}/generation",
        )
        keys = frozen_namespace_keys(
            self.batch,
            GenerationSummary.model_validate(raw),
            assisted=bool(self.task.before_sources),
        )
        for index, state in enumerate(self.receipt.namespaces):
            key = keys[state.scenario_id]
            if state.namespace_batch_key is not None and state.namespace_batch_key != key:
                raise HarnessError("SELFTEST_NAMESPACE_SOURCE_ALIAS_CHANGED")
            self.save(index, state.model_copy(update={"namespace_batch_key": key}))

    async def metadata(self, state: NamespaceState) -> JsonObject:
        batch_key = state.namespace_batch_key or self.batch.batch_key
        return object_value(
            await self.request(
                self.observer,
                "GET",
                f"/selftest/batches/{batch_key}/scenarios/{state.scenario_id}/journal?after_sequence=2147483647&limit=1",
                missing=True,
            )
        )

    @staticmethod
    def absent(raw: JsonObject) -> bool:
        error = raw.get("error")
        return isinstance(error, dict) and error.get("code") == "FIXTURE_NOT_FOUND"

    async def remove(self, index: int, state: NamespaceState) -> None:
        if state.status == "completed":
            return
        raw = await self.metadata(state)
        if self.absent(raw):
            self.save(index, state.model_copy(update={"status": "completed", "reason_codes": ()}))
            return
        condition = self._validate_namespace(state, raw)
        epoch, registration = (
            condition.expected_fixture_epoch,
            condition.expected_registration_epoch,
        )
        if state.delete_requested:
            raise HarnessError("SELFTEST_NAMESPACE_DELETE_RESULT_UNKNOWN")
        state = state.model_copy(
            update={"epoch": epoch, "registration_epoch": registration, "delete_requested": True}
        )
        self.save(index, state)
        namespace = state.namespace_batch_key or self.batch.batch_key
        await self.request(
            self.observer,
            "DELETE",
            f"/selftest/batches/{namespace}/scenarios/{state.scenario_id}",
            condition.body(),
        )
        if not self.absent(await self.metadata(state)):
            raise HarnessError("SELFTEST_NAMESPACE_DELETE_NOT_CONFIRMED")
        self.save(index, state.model_copy(update={"status": "completed", "reason_codes": ()}))

    def _validate_namespace(
        self, state: NamespaceState, raw: JsonObject
    ) -> NamespaceRemovalCondition:
        condition = namespace_condition(
            raw,
            state.namespace_batch_key or self.batch.batch_key,
            state.scenario_id,
            nonce=self.task.nonce,
            fixture_digest=self.identity.fixture_digest,
        )
        budget = object_value(raw.get("budget"))
        if (
            budget.get("parent_batch_key") != self.batch.batch_key
            or budget.get("nonce") != self.task.nonce
        ):
            raise HarnessError("SELFTEST_NAMESPACE_PARENT_BUDGET_MISMATCH")
        if condition is None or (
            state.epoch is not None
            and (condition.expected_fixture_epoch, condition.expected_registration_epoch)
            != (state.epoch, state.registration_epoch)
        ):
            raise HarnessError("SELFTEST_NAMESPACE_OWNERSHIP_OR_ACTIVE_REQUEST_UNKNOWN")
        return condition

    async def finish(self) -> None:
        if self.receipt.status == "completed":
            return
        self.archive()
        if self.receipt.attempts >= 3:
            reasons = tuple(
                dict.fromkeys((*self.receipt.reason_codes, "SELFTEST_NAMESPACE_RECOVERY_LIMIT"))
            )
            self.receipt = self.receipt.model_copy(
                update={"status": "needs_review", "reason_codes": reasons}
            )
            write_json(self.path, self.receipt)
            return
        self.receipt = self.receipt.model_copy(
            update={"attempts": self.receipt.attempts + 1, "status": "pending"}
        )
        write_json(self.path, self.receipt)
        try:
            async with asyncio.timeout(45):
                await self.stopped()
                await self.resolve_sources()
                await cleanup_owned_lifecycle(
                    self.task,
                    self.batch,
                    self.target_cleanup,
                    self.path.parent,
                    self.request,
                    self.receipt.attempts,
                )
                for index, state in enumerate(self.receipt.namespaces):
                    await self.remove(index, state)
            self.receipt = self.receipt.model_copy(
                update={"status": "completed", "reason_codes": ()}
            )
        except (HarnessError, httpx.HTTPError, OSError, ValueError, TimeoutError) as error:
            self.receipt = self.receipt.model_copy(
                update={"status": "needs_review", "reason_codes": failure_codes(error)}
            )
        except asyncio.CancelledError:
            self.receipt = self.receipt.model_copy(
                update={
                    "status": "needs_review",
                    "reason_codes": ("SELFTEST_NAMESPACE_CLEANUP_INTERRUPTED",),
                }
            )
            write_json(self.path, self.receipt)
            self.archive()
            raise
        write_json(self.path, self.receipt)
        self.archive()

    def archive(self) -> None:
        if not self.receipt.attempts:
            return
        path = self.path.with_name(f"namespace-cleanup-attempt-{self.receipt.attempts}.json")
        if not path.exists():
            write_json(path, self.receipt)


async def cleanup_owned_namespaces(
    writer: PublicAPI,
    observer: PublicAPI,
    batch: BatchResponse,
    directory: Path,
    *,
    target_cleanup: PublicAPI | None = None,
) -> None:
    if batch.phase not in {"cancelled", "expired"} or batch.cleanup_status == "completed":
        return
    try:
        with _cleanup_lock(directory):
            task = _owned_task(batch, directory)
            cleaner = NamespaceCleaner(
                writer, observer, batch, task, directory / "namespace-cleanup.json", target_cleanup
            )
            await cleaner.finish()
    except (HarnessError, ValidationError, OSError) as error:
        blocked = BlockedNamespaceCleanup(batch_id=batch.id, reason_codes=failure_codes(error))
        digest = canonical_digest(object_value(blocked.model_dump(mode="json")))
        path = directory / f"namespace-cleanup-blocked-{digest[:16]}.json"
        if path.exists():
            return
        write_json(path, blocked)
        return


@contextmanager
def _cleanup_lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = directory / ".namespace-cleanup.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as error:
        raise HarnessError("SELFTEST_NAMESPACE_CLEANUP_IN_PROGRESS_OR_NEEDS_REVIEW") from error
    try:
        yield
    finally:
        lock.rmdir()


def _complete_projection(raw: JsonObject, field: str) -> None:
    for name in ("has_more", "truncated", f"{field}_truncated"):
        if name in raw and raw[name] is not False:
            raise HarnessError("SELFTEST_NAMESPACE_NATIVE_PROJECTION_INCOMPLETE")
    if raw.get("next_cursor") is not None or raw.get(f"{field}_complete", True) is not True:
        raise HarnessError("SELFTEST_NAMESPACE_NATIVE_PROJECTION_INCOMPLETE")
    total = raw.get(f"{field}_total", raw.get("total"))
    rows = raw.get(field)
    if total is not None and (not isinstance(rows, list) or total != len(rows)):
        raise HarnessError("SELFTEST_NAMESPACE_NATIVE_PROJECTION_INCOMPLETE")
