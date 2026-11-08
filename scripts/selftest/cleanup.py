"""Stop owned native runs before bounded, exact-resource harness cleanup."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from pydantic import Field
from scripts.selftest.contracts import Contract, Identity, ResourceAbsenceEvidence
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    integer_value,
    objects_value,
    text_value,
    write_json,
)
from scripts.selftest.namespace_conditions import read_namespace_condition

type CleanupStatus = Literal["pending", "completed", "failed", "needs_review"]


class PlanStopReceipt(Contract):
    project_id: UUID
    plan_id: UUID | None = None
    run_id: UUID | None = None
    launch_requested: bool = False
    cancel_requested: bool = False
    status: CleanupStatus = "completed"
    reason_codes: tuple[Identity, ...] = Field(default=(), max_length=20)


class FixtureCleanupReceipt(Contract):
    scenario_id: Identity
    delete_requested: bool = False
    status: CleanupStatus = "pending"
    reason_codes: tuple[Identity, ...] = Field(default=(), max_length=20)
    fixture_epoch: Identity | None = None
    registration_epoch: Identity | None = None


class OwnedEnvironment(Contract):
    id: UUID
    project_id: UUID
    name: Identity
    created_by_id: UUID
    created_at: datetime


class ResourceCleanupReceipt(Contract):
    project_id: UUID
    creator_id: UUID
    names: tuple[Identity, ...] = Field(min_length=2, max_length=2)
    armed_at: datetime
    status: CleanupStatus = "pending"
    registered_resource: OwnedEnvironment | None = None
    delete_requested: bool = False
    reason_codes: tuple[Identity, ...] = Field(default=(), max_length=20)


class CleanupReceipt(Contract):
    schema_version: Literal["flowtest-selftest-cleanup-v1"] = "flowtest-selftest-cleanup-v1"
    batch_key: Identity
    status: CleanupStatus
    plan: PlanStopReceipt
    fixtures: tuple[FixtureCleanupReceipt, ...] = Field(max_length=100)
    resource: ResourceCleanupReceipt | None
    reason_codes: tuple[Identity, ...] = Field(default=(), max_length=20)


class PlanStopper:
    """A launch intent is durable before POST; unknown results never permit deletion."""

    def __init__(self, project_id: UUID) -> None:
        self.receipt = PlanStopReceipt(project_id=project_id)
        self._targets: tuple[UUID, ...] = ()
        self._observed: JsonObject | None = None

    def arm(self, plan_id: UUID, targets: tuple[UUID, ...]) -> None:
        if not 1 <= len(targets) <= 100 or len(targets) != len(set(targets)):
            raise HarnessError("SELFTEST_CLEANUP_TARGET_SET_INVALID")
        self._targets = targets
        self.receipt = self.receipt.model_copy(
            update={"plan_id": plan_id, "launch_requested": True, "status": "pending"}
        )

    def started(self, run_id: UUID) -> None:
        self.receipt = self.receipt.model_copy(update={"run_id": run_id})

    def observe(self, raw: JsonObject) -> None:
        self._validate_run(raw)
        self._observed = raw

    def _validate_run(self, raw: JsonObject) -> None:
        items = objects_value(raw.get("items", []))
        identity = (
            raw.get("run_id") == str(self.receipt.run_id)
            and raw.get("project_id") == str(self.receipt.project_id)
            and raw.get("test_plan_id") == str(self.receipt.plan_id)
        )
        complete = (
            raw.get("truncated") is False
            and raw.get("has_more") is False
            and raw.get("total") == len(items)
        )
        targets = [UUID(text_value(item["target_id"])) for item in items]
        if not identity or not complete or sorted(targets) != sorted(self._targets):
            raise HarnessError("SELFTEST_CLEANUP_PLAN_IDENTITY_OR_SET_MISMATCH")

    async def _terminal(self, reader: PublicAPI, raw: JsonObject) -> bool:
        self._validate_run(raw)
        items = objects_value(raw["items"])
        terminal = {"passed", "failed", "cancelled", "quarantined"}
        if raw.get("status") not in terminal or any(
            item["status"] not in terminal for item in items
        ):
            return False
        for item in items:
            if not await self._terminal_attempts(reader, item):
                return False
        return True

    async def _terminal_attempts(self, reader: PublicAPI, item: JsonObject) -> bool:
        ids = item.get("execution_ids")
        if (
            not isinstance(ids, list)
            or len(ids) > 100
            or item.get("attempts_complete") is not True
            or integer_value(item["attempts"]) != len(ids)
        ):
            raise HarnessError("SELFTEST_CLEANUP_ATTEMPTS_INCOMPLETE")
        normalized = [UUID(text_value(value)) for value in ids]
        current = item.get("execution_id")
        if len(normalized) != len(set(normalized)) or current != (ids[-1] if ids else None):
            raise HarnessError("SELFTEST_CLEANUP_ATTEMPT_IDENTITY_MISMATCH")
        for value in ids:
            execution_id = UUID(text_value(value))
            raw = await reader.object(
                "GET",
                f"/ci/projects/{self.receipt.project_id}/workflow-executions/{execution_id}/evidence",
            )
            if (
                raw.get("execution_id") != str(execution_id)
                or raw.get("project_id") != str(self.receipt.project_id)
                or raw.get("source_plan_run_item_id") != item["id"]
            ):
                raise HarnessError("SELFTEST_CLEANUP_EXECUTION_IDENTITY_MISMATCH")
            if raw.get("status") not in {"passed", "failed", "cancelled"}:
                return False
        return True

    async def stop(
        self, writer: PublicAPI, reader: PublicAPI, *, deadline: datetime
    ) -> PlanStopReceipt:
        if not self.receipt.launch_requested:
            return self.receipt
        if self.receipt.run_id is None:
            return self._review("SELFTEST_CLEANUP_LAUNCH_RESULT_UNKNOWN")
        raw = self._observed or await self._read(reader)
        if await self._terminal(reader, raw):
            return self.receipt.model_copy(update={"status": "completed"})
        self.receipt = self.receipt.model_copy(update={"cancel_requested": True})
        try:
            await writer.request(
                "POST",
                f"/projects/{self.receipt.project_id}/test-plan-runs/{self.receipt.run_id}/cancel",
                allow_status=(409,),
            )
        except (HarnessError, httpx.HTTPError):
            # A lost cancel response is resolved by reads, never by another mutation.
            self.receipt = self.receipt.model_copy(
                update={"reason_codes": ("SELFTEST_CLEANUP_CANCEL_RESULT_UNKNOWN",)}
            )
        for _ in range(40):
            if await self._terminal(reader, await self._read(reader)):
                return self.receipt.model_copy(update={"status": "completed"})
            if datetime.now(UTC) >= deadline:
                break
            await asyncio.sleep(0.25)
        return self._review("SELFTEST_CLEANUP_PLAN_NOT_TERMINAL")

    async def _read(self, reader: PublicAPI) -> JsonObject:
        return await reader.object(
            "GET",
            f"/ci/projects/{self.receipt.project_id}/test-plan-runs/{self.receipt.run_id}"
            "?page=1&page_size=100",
        )

    def _review(self, reason: str) -> PlanStopReceipt:
        return self.receipt.model_copy(update={"status": "needs_review", "reason_codes": (reason,)})


class RoundCleanup:
    def __init__(
        self,
        *,
        batch_key: str,
        project_id: UUID,
        output_dir: Path,
        writer: PublicAPI,
        reader: PublicAPI,
        observer: PublicAPI,
        nonce: str,
        fixture_digest: str,
        target_reader: PublicAPI | None = None,
        target_writer: PublicAPI | None = None,
    ) -> None:
        self.batch_key, self.output_dir = batch_key, output_dir
        self.plan = PlanStopper(project_id)
        self._writer, self._reader, self._observer = writer, reader, observer
        self._nonce, self._fixture_digest = nonce, fixture_digest
        self._target_reader, self._target_writer = target_reader, target_writer
        self._fixtures: list[FixtureCleanupReceipt] = []
        self._resource: ResourceCleanupReceipt | None = None
        self._finished: CleanupReceipt | None = None

    def register_fixture(self, scenario_id: str) -> None:
        if len(self._fixtures) >= 100 or scenario_id in {
            item.scenario_id for item in self._fixtures
        }:
            raise HarnessError("SELFTEST_CLEANUP_FIXTURE_DUPLICATE")
        self._fixtures.append(FixtureCleanupReceipt(scenario_id=scenario_id))
        self._persist("pending")

    def arm_plan(self, plan_id: UUID, targets: tuple[UUID, ...]) -> None:
        self.plan.arm(plan_id, targets)
        self._persist("pending")

    def started_plan(self, run_id: UUID) -> None:
        self.plan.started(run_id)
        self._persist("pending")

    async def arm_lifecycle(
        self, *, project_id: UUID, creator_id: UUID, names: tuple[str, str]
    ) -> None:
        if names != (f"{self.batch_key}-created", f"{self.batch_key}-updated"):
            raise HarnessError("SELFTEST_CLEANUP_RESOURCE_NAMESPACE_INVALID")
        resource = ResourceCleanupReceipt(
            project_id=project_id, creator_id=creator_id, names=names, armed_at=datetime.now(UTC)
        )
        rows = await self._environments(resource)
        if any(row.name in names for row in rows):
            raise HarnessError("SELFTEST_CLEANUP_RESOURCE_ALREADY_EXISTS")
        self._resource = resource
        self._persist("pending")

    def observe_absence(self, evidence: ResourceAbsenceEvidence) -> None:
        resource = self._resource
        if resource is None or (
            evidence.project_id != resource.project_id
            or not evidence.complete
            or evidence.observed_at < resource.armed_at
            or set(resource.names) & set(evidence.returned_names)
        ):
            raise HarnessError("SELFTEST_CLEANUP_ABSENCE_NOT_CONFIRMED")
        self._resource = resource.model_copy(update={"status": "completed"})
        self._persist("pending")

    async def _environments(self, resource: ResourceCleanupReceipt) -> tuple[OwnedEnvironment, ...]:
        if self._target_reader is None:
            raise HarnessError("SELFTEST_CLEANUP_RESOURCE_READER_MISSING")
        raw = objects_value(
            await self._target_reader.request(
                "GET", f"/projects/{resource.project_id}/environments"
            )
        )
        if len(raw) > 10000:
            raise HarnessError("SELFTEST_CLEANUP_RESOURCE_LIST_UNBOUNDED")
        rows = tuple(
            OwnedEnvironment.model_validate(
                {
                    key: row[key]
                    for key in ("id", "project_id", "name", "created_by_id", "created_at")
                }
            )
            for row in raw
        )
        if any(row.project_id != resource.project_id for row in rows) or len(rows) != len(
            {row.id for row in rows}
        ):
            raise HarnessError("SELFTEST_CLEANUP_RESOURCE_LIST_INVALID")
        return rows

    async def _cleanup_resource(self) -> None:
        resource = self._resource
        if resource is None or resource.status == "completed":
            return
        if not self.plan.receipt.launch_requested:
            self._resource = resource.model_copy(update={"status": "completed"})
            return
        matches = [row for row in await self._environments(resource) if row.name in resource.names]
        if not matches:
            self._resource = resource.model_copy(update={"status": "completed"})
            return
        if len(matches) != 1 or self._target_writer is None:
            raise HarnessError("SELFTEST_CLEANUP_RESOURCE_OWNERSHIP_AMBIGUOUS")
        owned = matches[0]
        if (
            owned.created_by_id != resource.creator_id
            or owned.created_at.tzinfo is None
            or not resource.armed_at <= owned.created_at <= datetime.now(UTC)
        ):
            raise HarnessError("SELFTEST_CLEANUP_RESOURCE_OWNERSHIP_UNPROVEN")
        self._resource = resource.model_copy(update={"registered_resource": owned})
        self._persist("pending")
        await self._delete_resource(owned)

    async def _delete_resource(self, owned: OwnedEnvironment) -> None:
        resource = self._resource
        if resource is None or self._target_writer is None:
            raise HarnessError("SELFTEST_CLEANUP_RESOURCE_WRITER_MISSING")
        rows = await self._environments(resource)
        if [row for row in rows if row.id == owned.id or row.name in resource.names] != [owned]:
            raise HarnessError("SELFTEST_CLEANUP_RESOURCE_CHANGED_BEFORE_DELETE")
        self._resource = resource.model_copy(update={"delete_requested": True})
        self._persist("pending")
        await self._target_writer.request(
            "DELETE", f"/projects/{owned.project_id}/environments/{owned.id}"
        )
        if any(
            row.id == owned.id or row.name in resource.names
            for row in await self._environments(resource)
        ):
            raise HarnessError("SELFTEST_CLEANUP_RESOURCE_DELETE_NOT_CONFIRMED")
        self._resource = resource.model_copy(
            update={"delete_requested": True, "status": "completed"}
        )

    async def _cleanup_fixtures(self) -> None:
        for index, fixture in enumerate(self._fixtures):
            reasons: tuple[str, ...] = ()
            try:
                await self._delete_fixture(index, fixture)
                status = "completed"
            except (HarnessError, httpx.HTTPError, OSError) as error:
                status = "failed" if self._fixtures[index].delete_requested else "needs_review"
                reasons = failure_codes(error)
            self._fixtures[index] = self._fixtures[index].model_copy(
                update={"status": status, "reason_codes": reasons}
            )
            self._persist("pending")

    async def _delete_fixture(self, index: int, fixture: FixtureCleanupReceipt) -> None:
        condition = await read_namespace_condition(
            self._observer,
            self.batch_key,
            fixture.scenario_id,
            nonce=self._nonce,
            fixture_digest=self._fixture_digest,
        )
        if condition is None:
            return
        self._fixtures[index] = fixture.model_copy(
            update={
                "delete_requested": True,
                "fixture_epoch": condition.expected_fixture_epoch,
                "registration_epoch": condition.expected_registration_epoch,
            }
        )
        self._persist("pending")
        await self._observer.request(
            "DELETE",
            f"/selftest/batches/{self.batch_key}/scenarios/{fixture.scenario_id}",
            condition.body(),
        )
        remaining = await read_namespace_condition(
            self._observer,
            self.batch_key,
            fixture.scenario_id,
            nonce=self._nonce,
            fixture_digest=self._fixture_digest,
        )
        if remaining is not None:
            raise HarnessError("SELFTEST_NAMESPACE_DELETE_NOT_CONFIRMED")

    async def finish(self) -> CleanupReceipt:
        if self._finished is not None:
            return self._finished
        # If cancellation interrupts a mutation, a second finally must not replay it.
        self._finished = self._persist("needs_review", ("SELFTEST_CLEANUP_IN_PROGRESS",))
        reasons: tuple[str, ...] = ()
        try:
            async with asyncio.timeout(45):
                self.plan.receipt = await self.plan.stop(
                    self._writer, self._reader, deadline=datetime.now(UTC) + timedelta(seconds=10)
                )
                self._persist("pending")
                if self.plan.receipt.status == "completed":
                    await self._recover_resource()
                    await self._cleanup_fixtures()
        except (HarnessError, httpx.HTTPError, OSError, ValueError, TimeoutError) as error:
            reasons = failure_codes(error)
            self._mark_unconfirmed_fixture_deletes(reasons)
        except asyncio.CancelledError:
            self._mark_unconfirmed_fixture_deletes(("SELFTEST_CLEANUP_INTERRUPTED",))
            self._finished = self._persist("needs_review", ("SELFTEST_CLEANUP_INTERRUPTED",))
            raise
        statuses = [self.plan.receipt.status, *(item.status for item in self._fixtures)]
        if self._resource is not None:
            statuses.append(self._resource.status)
        status: CleanupStatus = (
            "completed" if set(statuses) == {"completed"} and not reasons else "needs_review"
        )
        if "failed" in statuses:
            status = "failed"
        self._finished = self._persist(status, reasons)
        return self._finished

    def _mark_unconfirmed_fixture_deletes(self, reasons: tuple[str, ...]) -> None:
        self._fixtures = [
            item.model_copy(update={"status": "failed", "reason_codes": reasons})
            if item.delete_requested and item.status == "pending"
            else item
            for item in self._fixtures
        ]

    async def _recover_resource(self) -> None:
        try:
            await self._cleanup_resource()
        except (HarnessError, httpx.HTTPError, OSError, ValueError) as error:
            if self._resource is None:
                raise
            self._resource = self._resource.model_copy(
                update={"status": "needs_review", "reason_codes": failure_codes(error)}
            )

    def _persist(self, status: CleanupStatus, reasons: tuple[str, ...] = ()) -> CleanupReceipt:
        receipt = CleanupReceipt(
            batch_key=self.batch_key,
            status=status,
            plan=self.plan.receipt,
            fixtures=tuple(self._fixtures),
            resource=self._resource,
            reason_codes=reasons,
        )
        write_json(self.output_dir / "cleanup.json", receipt)
        return receipt
