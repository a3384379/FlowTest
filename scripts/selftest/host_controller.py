"""Two model phases separated by public human review; no review/write bypass."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError
from scripts.selftest.contracts import HostEvidence, canonical_digest
from scripts.selftest.host_attempts import AttemptRecord, AttemptStore, State
from scripts.selftest.host_binary import check_frozen_binary, inspect_binary
from scripts.selftest.host_contracts import HostAttemptResult, HostModelSummary
from scripts.selftest.host_gateway import BoundedGateway
from scripts.selftest.host_launch import (
    CodexLaunchPlan,
    HostDeployment,
    HostReadiness,
    VerifiedGrant,
    launch_plan,
    readiness,
)
from scripts.selftest.host_materialized import (
    HostMaterialization,
    HostSelection,
    assemble_materialized,
)
from scripts.selftest.host_observer import HostFrozenTrail
from scripts.selftest.host_repairs import RepairProof, resolve_known_read_errors
from scripts.selftest.host_runner import ProcessReceipt, run_process
from scripts.selftest.host_sources import (
    FrozenHostCase,
    FrozenHostSource,
    freeze_cases,
    freeze_workflows,
    reviewed_workflows,
)
from scripts.selftest.io import HarnessError, PublicAPI, write_json


class HostController:
    def __init__(
        self,
        *,
        grant: VerifiedGrant,
        deployment: HostDeployment,
        store: AttemptStore,
        gateway: BoundedGateway,
        reader: PublicAPI,
        directory: Path,
    ) -> None:
        self.grant, self.deployment, self.store = grant, deployment, store
        self.gateway, self.reader, self.directory = gateway, reader, directory

    def _ready(self, record: AttemptRecord) -> HostReadiness:
        result = readiness(self.grant, self.deployment)
        if result.status != "ready":
            return result
        deadline = record.created_at + timedelta(
            seconds=self.grant.authorization.budget.wall_seconds
        )
        if datetime.now(UTC) >= deadline:
            return HostReadiness("NOT_RUN", ("HOST_DEADLINE_EXCEEDED",))
        self.gateway.deadline = min(self.gateway.deadline, deadline)
        return result

    async def start(self, *, attempt_id: UUID, prompt: str) -> HostAttemptResult | HostReadiness:
        status = readiness(self.grant, self.deployment)
        if status.status != "ready":
            return status
        record = self.store.reserve(self.grant, attempt_id)
        if self.gateway.attempt_id != attempt_id or self.gateway.phase != "workflow":
            raise HarnessError("HOST_ATTEMPT_GATEWAY_CHANGED")
        return await self._phase(record, "workflow", prompt)

    async def resume_after_workflow_review(
        self, *, prompt: str
    ) -> HostAttemptResult | HostReadiness:
        record = self.store.read(self.grant)
        if record.state != "waiting_workflow_review":
            raise HarnessError("HOST_REVIEW_RESUME_STATE_INVALID")
        status = self._ready(record)
        if status.status != "ready":
            return status
        path = self.directory / "workflow-sources.json"
        sources = TypeAdapter(tuple[FrozenHostSource, ...]).validate_json(path.read_bytes())
        if (
            canonical_digest([item.model_dump(mode="json") for item in sources])
            != record.source_manifest_digest
        ):
            raise HarnessError("HOST_FROZEN_SOURCE_MANIFEST_CHANGED")
        bindings = await reviewed_workflows(
            self.reader, sources, reviewer_ids=self.grant.authorization.reviewer_ids
        )
        if not self.gateway.receipts:
            self.gateway.restore_receipts()
        self.gateway.begin_case_phase(bindings)
        record = self.store.transition(
            self.grant, record, "case_ready", reviewed_workflows=bindings
        )
        return await self._phase(record, "case", prompt)

    async def _phase(
        self,
        record: AttemptRecord,
        phase: str,
        prompt: str,
    ) -> HostAttemptResult | HostReadiness:
        status = self._ready(record)
        if status.status != "ready":
            return status
        identity = await inspect_binary(self.deployment)
        check_frozen_binary(identity, self.directory / "cli-identity.json")
        write_json(self.directory / "cli-identity.json", identity)
        phase_dir = self.directory / phase
        schema = self.directory / (phase + "-output.schema.json")
        write_json(schema, HostModelSummary.model_json_schema())
        output = self.directory / (phase + "-last-message.json")
        plan = launch_plan(
            self.grant,
            self.deployment,
            prompt=prompt,
            schema=schema,
            output=output,
            deadline=self.gateway.deadline,
        )
        if not isinstance(plan, CodexLaunchPlan):
            return plan
        following: State = "workflow_running" if phase == "workflow" else "case_running"
        record = self.store.transition(self.grant, record, following)
        try:
            process = await run_process(
                plan,
                prompt=prompt,
                gateway=self.gateway,
                socket_path=self.deployment.relay_socket,
                output_dir=phase_dir,
            )
            if process.receipt.reason_code or process.receipt.summary is None:
                raise HarnessError(process.receipt.reason_code or "HOST_MODEL_SUMMARY_MISSING")
            summary = process.receipt.summary
            if summary.phase != phase:
                raise HarnessError("HOST_MODEL_PHASE_CHANGED")
            repairs = resolve_known_read_errors(self.gateway)
            write_json(
                self.directory / (phase + "-repairs.json"),
                [item.model_dump(mode="json") for item in repairs],
            )
            identifiers = await self._freeze(phase, summary)
            state: State = (
                "waiting_workflow_review" if phase == "workflow" else "waiting_case_review"
            )
            record = self.store.transition(
                self.grant,
                record,
                state,
                proposal_ids=identifiers,
                source_manifest_digest=self._source_digest(phase),
            )
            result = self._result(record, phase, plan, "waiting_for_review", ())
        except asyncio.CancelledError:
            record = self.store.transition(
                self.grant, record, "error", reason_code="HOST_PROCESS_CANCELLED"
            )
            write_json(
                self.directory / (phase + "-result.json"),
                self._result(record, phase, plan, "error", ("HOST_PROCESS_CANCELLED",)),
            )
            raise
        except (HarnessError, ValidationError, httpx.HTTPError, OSError) as error:
            code = (
                str(error).split(":")[0]
                if isinstance(error, HarnessError)
                else "HOST_SOURCE_READBACK_OR_RECEIPT_ERROR"
            )
            record = self.store.transition(self.grant, record, "error", reason_code=code)
            result = self._result(record, phase, plan, "error", (code,))
        write_json(self.directory / (phase + "-result.json"), result)
        return result

    async def _freeze(self, phase: str, summary: HostModelSummary) -> tuple[UUID, ...]:
        if phase == "workflow":
            sources = await freeze_workflows(self.reader, self.gateway, summary)
            write_json(
                self.directory / "workflow-sources.json",
                [item.model_dump(mode="json") for item in sources],
            )
            return tuple(item.proposal_id for item in sources)
        sources = TypeAdapter(tuple[FrozenHostSource, ...]).validate_json(
            (self.directory / "workflow-sources.json").read_bytes()
        )
        cases = await freeze_cases(self.reader, self.gateway, summary, sources=sources)
        write_json(
            self.directory / "case-sources.json", [item.model_dump(mode="json") for item in cases]
        )
        return tuple(dict.fromkeys(item.proposal_id for item in cases))

    def _source_digest(self, phase: str) -> str:
        import json

        workflow = json.loads((self.directory / "workflow-sources.json").read_bytes())
        if phase == "workflow":
            return canonical_digest(workflow)
        cases = json.loads((self.directory / "case-sources.json").read_bytes())
        return canonical_digest({"workflow": workflow, "case": cases})

    def _result(
        self,
        record: AttemptRecord,
        phase: str,
        plan: CodexLaunchPlan,
        status: str,
        reasons: tuple[str, ...],
    ) -> HostAttemptResult:
        process_path = self.directory / phase / "process.json"
        process = (
            ProcessReceipt.model_validate_json(process_path.read_bytes())
            if process_path.exists()
            else None
        )
        return HostAttemptResult.model_validate(
            {
                "attempt_id": record.attempt_id,
                "phase": phase,
                "status": status,
                "reason_codes": reasons,
                "host": self.deployment.host_id,
                "model": self.grant.authorization.model,
                "cli_version": self.deployment.cli_version,
                "skill_digest": self.deployment.skill_digest,
                "prompt_digest": plan.prompt_digest,
                "authorized_budget_digest": self.grant.digest,
                "actual_tool_calls": len(self.gateway.receipts),
                "catalog_digest": self.gateway.catalog_digest,
                "started_at": record.created_at,
                "completed_at": datetime.now(UTC),
                "exit_code": process.exit_code if process else None,
                "input_tokens": process.input_tokens if process else None,
                "output_tokens": process.output_tokens if process else None,
                "proposal_ids": record.workflow_proposal_ids
                if phase == "workflow"
                else record.case_proposal_ids,
            }
        )

    async def materialize_after_case_review(
        self,
        *,
        selections: tuple[HostSelection, ...],
        transport: Literal["stdio", "streamable-http"],
        protocol_version: str,
    ) -> HostMaterialization | HostReadiness:
        record = self.store.read(self.grant)
        if record.state != "waiting_case_review":
            raise HarnessError("HOST_CASE_REVIEW_RESUME_STATE_INVALID")
        status = self._ready(record)
        if status.status != "ready":
            return status
        if self._source_digest("case") != record.source_manifest_digest:
            raise HarnessError("HOST_FROZEN_SOURCE_MANIFEST_CHANGED")
        sources = TypeAdapter(tuple[FrozenHostSource, ...]).validate_json(
            (self.directory / "workflow-sources.json").read_bytes()
        )
        cases = TypeAdapter(tuple[FrozenHostCase, ...]).validate_json(
            (self.directory / "case-sources.json").read_bytes()
        )
        results = tuple(
            HostAttemptResult.model_validate_json(
                (self.directory / (phase + "-result.json")).read_bytes()
            )
            for phase in ("workflow", "case")
        )
        trail = self._trail(results)
        result = await assemble_materialized(
            self.reader,
            grant=self.grant,
            gateway=self.gateway,
            record=record,
            sources=sources,
            cases=cases,
            selections=selections,
            workflow_result=results[0],
            case_result=results[1],
            transport=transport,
            sdk_version=version("mcp"),
            protocol_version=protocol_version,
            trail=trail,
        )
        write_json(self.directory / "host-materialized.json", result)
        self.store.transition(self.grant, record, "sealed")
        return result

    def _trail(self, results: tuple[HostAttemptResult, ...]) -> HostFrozenTrail:
        phases = tuple(
            ProcessReceipt.model_validate_json(
                (self.directory / phase / "process.json").read_bytes()
            )
            for phase in ("workflow", "case")
        )
        repairs: list[RepairProof] = []
        for phase in ("workflow", "case"):
            repairs.extend(
                TypeAdapter(tuple[RepairProof, ...]).validate_json(
                    (self.directory / (phase + "-repairs.json")).read_bytes()
                )
            )
        unique = {item.failed_sequence: item for item in repairs}
        return HostFrozenTrail(
            authorization_digest=self.grant.digest,
            task_digest=self.grant.authorization.task_digest,
            host=HostEvidence(
                host=self.deployment.host_id,
                model=self.grant.authorization.model,
                skill_digest=self.deployment.skill_digest,
                prompt_digest=canonical_digest(
                    {"workflow": results[0].prompt_digest, "case": results[1].prompt_digest}
                ),
                authorized_budget_digest=self.grant.digest,
                actual_tool_calls=len(self.gateway.receipts),
            ),
            catalog_digest=self.gateway.catalog_digest,
            receipts=tuple(self.gateway.receipts),
            repairs=tuple(unique.values()),
            phases=(phases[0], phases[1]),
            stop=self.gateway.stop_receipt,
        )
