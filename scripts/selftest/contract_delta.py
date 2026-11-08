"""Controlled contract v1→v2 journey and real Case-slot rejection fixtures."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from scripts.selftest.cleanup import RoundCleanup
from scripts.selftest.collect_evidence import collect_scenario, journal, wait_plan
from scripts.selftest.contract_delta_budget import DeltaAPI, DeltaBudget, DeltaProtocol
from scripts.selftest.contract_delta_contracts import (
    BoundaryObservation,
    DeltaEvidence,
    DeltaManifest,
    DeltaPack,
    DeltaPhaseFreeze,
    DeltaPhaseObservation,
    DeltaPreview,
    DeltaReport,
)
from scripts.selftest.contract_delta_generation import (
    SCENARIO,
    apply_version,
    freeze_phase,
    preview,
    stale_preview_control,
)
from scripts.selftest.contract_delta_slots import drift, foreign, unpublished
from scripts.selftest.contract_delta_verify import verify, write_reports
from scripts.selftest.contracts import FixtureJournal, canonical_digest
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import HarnessError, JsonObject, PublicAPI, objects_value, write_json
from scripts.selftest.mcp_protocol_runner import ProtocolClient
from scripts.selftest.start_plan import launch_plan


class JournalNamespace(PublicAPI):
    """Only the declared shared fixture route is adapted; returned identity stays intact."""

    def __init__(self, observer: PublicAPI, phase_key: str, fixture_key: str) -> None:
        self.observer, self.phase_key, self.fixture_key = observer, phase_key, fixture_key

    async def object(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        prefix = f"/selftest/batches/{self.phase_key}/scenarios/{SCENARIO}/journal?"
        if method != "GET" or not path.startswith(prefix) or payload is not None:
            raise HarnessError("DELTA_UNDECLARED_OBSERVER_ROUTE")
        return await self.observer.object(
            "GET",
            path.replace(
                "/batches/" + self.phase_key + "/", "/batches/" + self.fixture_key + "/", 1
            ),
        )


async def _configure(observer: DeltaAPI, frozen: DeltaManifest) -> str:
    path = f"/selftest/batches/{frozen.batch_key}/scenarios/{SCENARIO}"
    remaining = int((frozen.expires_at - datetime.now(UTC)).total_seconds())
    if remaining < 1:
        raise HarnessError("DELTA_BATCH_EXPIRED")
    await observer.request(
        "PUT",
        path,
        {
            "nonce": frozen.nonce,
            "fixture_digest": frozen.builds.fixture,
            "ttl_seconds": remaining,
            "max_entries": 10,
            "max_bytes": 262144,
            "response_statuses": [200],
            "response_body": {"actual": 1, "code": 0, "value": None},
            "budget_scope": frozen.scope.model_dump(mode="json"),
        },
    )
    empty = await journal(observer, frozen.batch_key, SCENARIO)
    if empty.request_count or empty.entries or empty.nonce != frozen.nonce:
        raise HarnessError("DELTA_FIXTURE_NOT_EMPTY")
    return empty.fixture_epoch


async def _execute(
    writer: DeltaAPI,
    reader: DeltaAPI,
    observer: DeltaAPI,
    frozen: DeltaManifest,
    phase: DeltaPhaseFreeze,
    cleanup: RoundCleanup,
    directory: Path,
) -> DeltaPhaseObservation:
    cleanup.arm_plan(phase.selection.plan_id, tuple(item.case_id for item in phase.selection.cases))
    writer.budget.admit()  # finite one-request native DAG, before its public launch
    started = await launch_plan(
        writer, selection=phase.selection, batch_key=phase.manifest.batch_key
    )
    cleanup.started_plan(started.run_id)
    raw = await wait_plan(
        reader, str(phase.selection.project_id), str(started.run_id), frozen.expires_at
    )
    cleanup.plan.observe(raw)
    items = objects_value(raw["items"])
    if len(items) != 1 or raw["test_plan_id"] != str(phase.selection.plan_id):
        raise HarnessError("DELTA_PLAN_SELECTION_CHANGED")
    observed = await collect_scenario(
        reader,
        JournalNamespace(observer, phase.manifest.batch_key, frozen.batch_key),
        asset=phase.asset,
        run=raw,
        item=items[0],
        batch_key=phase.manifest.batch_key,
        catalog_digest=phase.asset.calls[0].catalog_digest,
        expected_target_snapshot_digest=phase.selection.cases[0].target_snapshot_digest,
        selection=phase.selection,
        output_dir=directory,
        deadline=frozen.expires_at,
    )
    result = DeltaPhaseObservation(
        phase=phase.phase,
        frozen_digest=canonical_digest(phase.model_dump(mode="json")),
        observation=observed,
        plan_run=raw,
        observed_at=datetime.now(UTC),
    )
    write_json(directory / "observed-after-run.json", result)
    return result


class DeltaJourney:
    def __init__(
        self,
        frozen: DeltaManifest,
        pack: DeltaPack,
        client: ProtocolClient,
        writer: PublicAPI,
        provisioner: PublicAPI,
        reader: PublicAPI,
        viewer: PublicAPI,
        observer: PublicAPI,
        directory: Path,
        *,
        budget: DeltaBudget | None = None,
    ) -> None:
        self.frozen, self.pack, self.directory = frozen, pack, directory
        self.budget = budget or DeltaBudget(directory, frozen.expires_at)
        if self.budget.deadline != frozen.expires_at:
            raise HarnessError("DELTA_ADMISSION_DEADLINE_CHANGED")
        self.client = DeltaProtocol(client, self.budget)
        self.writer, self.provisioner = (
            DeltaAPI(writer, self.budget),
            DeltaAPI(provisioner, self.budget),
        )
        self.reader, self.viewer = DeltaAPI(reader, self.budget), DeltaAPI(viewer, self.budget)
        self.observer = DeltaAPI(observer, self.budget)
        self.cleanup = RoundCleanup(
            batch_key=frozen.batch_key,
            project_id=frozen.installation.project_id,
            output_dir=directory,
            writer=DeltaAPI(writer, self.budget, cleanup=True),
            reader=DeltaAPI(reader, self.budget, cleanup=True),
            observer=DeltaAPI(observer, self.budget, cleanup=True),
            nonce=frozen.nonce,
            fixture_digest=frozen.builds.fixture,
        )
        self.evidence = DeltaEvidence(
            manifest_digest=canonical_digest(frozen.model_dump(mode="json")),
            collected_at=datetime.now(UTC),
        )

    def checkpoint(
        self,
        *,
        previews: tuple[DeltaPreview, ...] | None = None,
        phases: tuple[DeltaPhaseFreeze, ...] | None = None,
        observations: tuple[DeltaPhaseObservation, ...] | None = None,
        boundaries: tuple[BoundaryObservation, ...] | None = None,
        journal: FixtureJournal | None = None,
        failure_code: str | None = None,
        fixture_cleanup: Literal["pending", "completed", "failed"] | None = None,
    ) -> None:
        previous = self.evidence
        self.evidence = DeltaEvidence.model_validate(
            {
                **previous.model_dump(),
                "previews": previous.previews if previews is None else previews,
                "phases": previous.phases if phases is None else phases,
                "observations": previous.observations if observations is None else observations,
                "boundaries": previous.boundaries if boundaries is None else boundaries,
                "journal": previous.journal if journal is None else journal,
                "failure_code": previous.failure_code if failure_code is None else failure_code,
                "fixture_cleanup": previous.fixture_cleanup
                if fixture_cleanup is None
                else fixture_cleanup,
                "calls": tuple(self.client.receipts),
                "collected_at": datetime.now(UTC),
                "admitted_request_upper_bound": self.budget.requests,
                "rejected_requests": self.budget.rejected_requests,
                "admitted_tool_calls": self.budget.tools,
                "rejected_tool_calls": self.budget.rejected_tools,
            }
        )
        write_json(self.directory / "evidence.json", self.evidence)

    async def phase(self, index: int, epoch: str) -> DeltaPhaseFreeze:
        golden = self.pack.phases[index]
        self.client.batch_key = self.frozen.batch_key + "-" + golden.phase
        directory = self.directory / golden.phase
        snapshot, selected = await preview(
            self.client, self.frozen.installation, golden, directory, self.frozen.batch_key
        )
        rejected = None
        if index == 0:
            rejected = await stale_preview_control(
                self.client, self.frozen.installation, snapshot, selected, self.viewer
            )
        applied, identifier, version = await apply_version(
            self.client,
            self.writer,
            self.frozen.installation,
            golden,
            snapshot,
            selected,
            directory,
            self.viewer,
        )
        if rejected is not None:
            applied = applied.model_copy(update={"rejection": rejected})
        self.checkpoint(previews=(*self.evidence.previews, applied))
        phase = await freeze_phase(
            self.client,
            self.writer,
            self.frozen,
            self.pack,
            golden,
            identifier,
            version,
            epoch,
            directory,
        )
        self.checkpoint(phases=(*self.evidence.phases, phase))
        observed = await _execute(
            self.writer, self.reader, self.observer, self.frozen, phase, self.cleanup, directory
        )
        self.checkpoint(observations=(*self.evidence.observations, observed))
        return phase

    async def run(self) -> tuple[DeltaEvidence, DeltaReport]:
        if (self.directory / "manifest.json").exists():
            raise HarnessError("DELTA_OUTPUT_ALREADY_EXISTS_NO_MUTATION_REPLAY")
        write_json(self.directory / "manifest.json", self.frozen)
        self.cleanup.register_fixture(SCENARIO)
        try:
            epoch = await _configure(self.observer, self.frozen)
            before = await self.phase(0, epoch)
            after = await self.phase(1, epoch)
            rows = [
                await foreign(
                    self.client,
                    self.writer,
                    self.provisioner,
                    self.viewer,
                    self.frozen,
                    before,
                    self.directory,
                )
            ]
            self.checkpoint(boundaries=tuple(rows))
            rows.append(
                await unpublished(self.client, self.writer, self.viewer, self.frozen, before)
            )
            self.checkpoint(boundaries=tuple(rows))
            rows.append(
                await drift(self.client, self.writer, self.viewer, self.frozen, before, after)
            )
            observed = await journal(
                self.observer, self.frozen.batch_key, SCENARIO, deadline=self.frozen.expires_at
            )
            self.checkpoint(boundaries=tuple(rows), journal=observed)
        except BaseException as error:
            # Every unknown mutation is retained; the existing PlanStopper prevents
            # fixture deletion until all launched native work is actually terminal.
            self.checkpoint(failure_code=";".join(failure_codes(error))[:200])
            raise
        finally:
            try:
                receipt = await self.cleanup.finish()
                self.checkpoint(
                    fixture_cleanup="completed" if receipt.status == "completed" else "failed"
                )
            except (HarnessError, httpx.HTTPError):
                self.checkpoint(
                    fixture_cleanup="failed", failure_code="DELTA_CLEANUP_RESULT_UNKNOWN"
                )
            report = verify(self.frozen, self.pack, self.evidence)
            write_reports(report, self.evidence, self.directory)
        return self.evidence, report
