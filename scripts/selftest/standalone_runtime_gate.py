"""Occupy actual bounded Standalone slots to observe a queued run without DB edits."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from scripts.selftest.collect_evidence import _journal_snapshot
from scripts.selftest.contracts import FixtureBudgetScope, FixtureJournal
from scripts.selftest.io import HarnessError
from scripts.selftest.local_stack import StackBinding, _docker, verify_binding
from scripts.selftest.runtime_faults import (
    Assets,
    FrozenRuntimeBatch,
    RuntimeClients,
    StandaloneGateWitness,
    configure,
    install,
    recover_same_key,
    wait_workflow,
)


class StandaloneRuntimeGate:
    def __init__(
        self,
        binding: StackBinding,
        directory: Path,
        output: Path,
        frozen: FrozenRuntimeBatch,
        clients: RuntimeClients,
        project: UUID,
        service: UUID,
    ) -> None:
        verify_binding(binding, directory)
        script = "from app.core.config import settings; print(settings.standalone_task_concurrency)"
        slots = _docker(["exec", binding.runner_container_id, "python", "-c", script])
        if binding.runtime_profile != "standalone" or slots != "4":
            raise HarnessError("RUNTIME_FAULT_STANDALONE_SLOT_CONTRACT_CHANGED")
        self.binding, self.output, self.frozen = binding, output, frozen
        self.clients, self.project, self.service = clients, project, service
        self.witnesses: tuple[StandaloneGateWitness, ...] = ()

    def resume(self) -> None:
        # Occupants finish bounded native work; they are never suspended processes.
        return None

    async def _occupy(self, asset: Assets) -> tuple[UUID, ...]:
        path = f"/ci/projects/{asset.project_id}/workflows/{asset.workflow_id}/executions"
        identifiers = []
        for index in range(4):
            result = await recover_same_key(
                self.clients.ci,
                path,
                asset.scenario_key + ":" + str(index),
                payload={
                    "environment_id": str(asset.environment_id),
                    "version": 1,
                    "runtime_variables": {},
                    "runtime_headers": {},
                },
            )
            identifiers.append(result.id)
        if len(set(identifiers)) != 4:
            raise HarnessError("RUNTIME_FAULT_STANDALONE_OCCUPANT_IDS_CHANGED")
        return tuple(identifiers)

    async def _started(self, asset: Assets) -> FixtureJournal:
        for _ in range(200):
            journal = await _journal_snapshot(
                self.clients.observer, asset.batch_key, asset.scenario_key
            )
            if journal.metrics is not None and journal.metrics.active_count == 4:
                return journal
            if datetime.now(UTC) >= self.frozen.deadline:
                break
            await asyncio.sleep(0.05)
        raise HarnessError("RUNTIME_FAULT_STANDALONE_OCCUPANCY_NOT_OBSERVED")

    @asynccontextmanager
    async def held(self) -> AsyncIterator[None]:
        key = "standalone-gate-" + str(len(self.witnesses) + 1)
        phase = self.output / key
        phase.mkdir()
        asset = await install(
            self.clients.writer,
            project=self.project,
            service=self.service,
            fixture_url=self.binding.fixture_internal_url,
            batch=self.frozen.batch_key,
            scenario=key,
            directory=phase,
        )
        await configure(
            self.clients.observer,
            asset,
            self.frozen.pack_digest,
            slow=True,
            scope=FixtureBudgetScope(
                parent_batch_key=self.frozen.batch_key,
                nonce=self.frozen.nonce,
                limit=100,
                expires_at=self.frozen.deadline.timestamp(),
            ),
        )
        identifiers = await self._occupy(asset)
        active = await self._started(asset)
        held_at = datetime.now(UTC)
        try:
            yield
        finally:
            executions = await asyncio.gather(
                *(
                    wait_workflow(
                        self.clients.reader, self.project, identifier, self.frozen.deadline
                    )
                    for identifier in identifiers
                )
            )
            settled = await _journal_snapshot(
                self.clients.observer, asset.batch_key, asset.scenario_key
            )
            witness = StandaloneGateWitness(
                scenario_key=key,
                project_id=self.project,
                workflow_id=asset.workflow_id,
                held_at=held_at,
                completed_at=datetime.now(UTC),
                at_hold=active,
                settled=settled,
                executions=tuple(executions),
            )
            from scripts.selftest.io import write_json

            write_json(phase / "gate-witness.json", witness)
            self.witnesses = (*self.witnesses, witness)


def gate_findings(
    frozen: FrozenRuntimeBatch,
    witnesses: tuple[StandaloneGateWitness, ...],
) -> tuple[str, ...]:
    if frozen.profile != "standalone":
        return ("RUNTIME_FAULT_UNEXPECTED_SLOT_GATE",) if witnesses else ()
    if len(witnesses) != 4:
        return ("RUNTIME_FAULT_STANDALONE_GATE_SET_INCOMPLETE",)
    for index, witness in enumerate(witnesses, start=1):
        if witness.scenario_key != f"standalone-gate-{index}" or not _valid_witness(
            frozen, witness
        ):
            return ("RUNTIME_FAULT_STANDALONE_GATE_MISMATCH",)
    return ()


def _valid_witness(frozen: FrozenRuntimeBatch, witness: StandaloneGateWitness) -> bool:
    active, settled = witness.at_hold, witness.settled
    return bool(
        active.metrics is not None
        and active.metrics.active_count == 4
        and active.metrics.peak_concurrency == 4
        and active.request_count == 4
        and active.metrics.completed_count == 0
        and len(active.metrics.events) == 4
        and sorted(row.active_at_begin for row in active.metrics.events) == [1, 2, 3, 4]
        and all(row.completed_at is None for row in active.metrics.events)
        and settled.metrics is not None
        and settled.metrics.complete
        and settled.metrics.active_count == 0
        and settled.metrics.peak_concurrency == 4
        and settled.metrics.completed_count == 12
        and settled.metrics.cancelled_count == settled.metrics.failed_count == 0
        and Counter(row.marker for row in settled.entries)
        == {"first": 4, "follow": 4, "cleanup": 4}
        and settled.request_count == 12
        and not settled.truncated
        and not settled.expired
        and not settled.epoch_changed
        and settled.next_sequence is None
        and [row.sequence for row in settled.entries] == list(range(1, 13))
        and (active.batch_key, active.scenario_id, active.nonce, active.fixture_digest)
        == (settled.batch_key, settled.scenario_id, settled.nonce, settled.fixture_digest)
        and (settled.batch_key, settled.scenario_id, settled.nonce, settled.fixture_digest)
        == (frozen.batch_key, witness.scenario_key, frozen.nonce, frozen.pack_digest)
        and frozen.created_at <= witness.held_at <= witness.completed_at <= frozen.deadline
        and len({row.run.id for row in witness.executions}) == 4
        and all(
            row.run.status == "passed"
            and row.item_statuses == ("passed",)
            and row.api_versions == (1, 1, 1)
            for row in witness.executions
        )
    )
