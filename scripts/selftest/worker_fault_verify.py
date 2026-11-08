"""Independently check all four worker faults, exact native attempts and wire effects."""

import argparse
from datetime import timedelta
from pathlib import Path

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.local_stack import ROOT
from scripts.selftest.worker_fault_contracts import (
    SCENARIOS,
    WorkerEvidence,
    WorkerGolden,
    WorkerManifest,
    WorkerObservation,
    WorkerPack,
    WorkerReport,
    WorkerVariantReport,
)

PACK = ROOT / "selftest/packs/worker-faults-v1/pack.json"


def load_pack() -> tuple[WorkerPack, str]:
    raw = read_json(PACK)
    pack = WorkerPack.model_validate(raw)
    if tuple(row.variant for row in pack.scenarios) != SCENARIOS:
        raise HarnessError("WORKER_FAULT_DENOMINATOR_CHANGED")
    return pack, canonical_digest(raw)


def verify(manifest: WorkerManifest, evidence: WorkerEvidence) -> WorkerReport:
    pack, digest = load_pack()
    reasons: list[str] = []
    identity = canonical_digest(manifest.model_dump(mode="json"))
    if manifest.pack_digest != digest or evidence.manifest_digest != identity:
        reasons.append("WORKER_FAULT_FROZEN_SOURCE_CHANGED")
    if not manifest.created_at < evidence.collected_at <= manifest.deadline:
        reasons.append("WORKER_FAULT_DEADLINE_EXCEEDED")
    if manifest.deadline - manifest.created_at > timedelta(seconds=pack.max_runtime_seconds):
        reasons.append("WORKER_FAULT_DEADLINE_CHANGED")
    if tuple(row.variant for row in evidence.observations) != SCENARIOS:
        reasons.append("WORKER_FAULT_REQUIRED_SCENARIO_MISSING_OR_DUPLICATED")
    reports = _reports(pack, evidence, manifest)
    reasons.extend(_budgets(manifest, evidence))
    if evidence.disposal is None:
        reasons.append("OWNED_ASSET_DISPOSAL_PENDING")
    elif (
        evidence.disposal.model_dump(
            exclude={"removed_at", "containers_absent", "volumes_absent", "networks_absent"}
        )
        != manifest.disposal.model_dump()
        or not all(
            (
                evidence.disposal.containers_absent,
                evidence.disposal.volumes_absent,
                evidence.disposal.networks_absent,
            )
        )
        or evidence.disposal.removed_at < evidence.collected_at
    ):
        reasons.append("WORKER_FAULT_DISPOSAL_IDENTITY_CHANGED")
    return WorkerReport(
        manifest_digest=identity,
        evidence_digest=canonical_digest(evidence.model_dump(mode="json")),
        scenario_ids=tuple("ST-RUN-004/" + row.variant for row in pack.scenarios),
        exit_code=2 if reasons or any(row.reason_codes for row in reports) else 0,
        reason_codes=tuple(reasons),
        scenarios=reports,
    )


def _reports(
    pack: WorkerPack, evidence: WorkerEvidence, manifest: WorkerManifest
) -> tuple[WorkerVariantReport, ...]:
    actual = {row.variant: row for row in evidence.observations}
    return tuple(
        _scenario(golden, actual[golden.variant], manifest)
        if golden.variant in actual
        else WorkerVariantReport(
            variant=golden.variant,
            native_status=None,
            reason_codes=("WORKER_FAULT_REQUIRED_SCENARIO_MISSING",),
        )
        for golden in pack.scenarios
    )


def _budgets(manifest: WorkerManifest, evidence: WorkerEvidence) -> tuple[str, ...]:
    admitted = 0
    for observed in evidence.observations:
        budget = observed.journal.budget
        admitted += observed.journal.request_count
        if budget is None or (
            budget.parent_batch_key != manifest.batch_key
            or budget.nonce != manifest.nonce
            or budget.fixture_digest != manifest.pack_digest
            or budget.admitted_count != admitted
            or budget.rejected_count != 0
            or budget.limit != 100
            or budget.expires_at != manifest.deadline.timestamp()
            or admitted > 100
        ):
            return ("WORKER_FAULT_SHARED_BUDGET_CHANGED",)
    return ()


def _scenario(
    golden: WorkerGolden, actual: WorkerObservation, manifest: WorkerManifest
) -> WorkerVariantReport:
    reasons: list[str] = []
    asset = manifest.assets[SCENARIOS.index(golden.variant)]
    if actual.variant != golden.variant or actual.run_id != actual.native.run.id:
        reasons.append("WORKER_FAULT_NATIVE_IDENTITY_CHANGED")
    if (
        actual.native.run.status != golden.status
        or actual.native.item_statuses != (golden.status,)
        or len(actual.native.execution_ids) != 1
        or actual.native.api_versions != (1, 1, 1)
        or (actual.source_case_id, actual.source_workflow_id, actual.source_workflow_fingerprint)
        != (asset.case_id, asset.workflow_id, asset.workflow_fingerprint)
    ):
        reasons.append("WORKER_FAULT_NATIVE_RESULT_OR_ATTEMPT_CHANGED")
    expected_code = "TEST_PLAN_WORKER_LOST" if golden.worker_killed else None
    if actual.native_error_codes != (expected_code,):
        reasons.append("WORKER_FAULT_WRONG_FAILURE_CODE")
    journal = actual.journal
    if (
        journal.truncated
        or journal.expired
        or journal.epoch_changed
        or journal.request_count != len(golden.markers)
        or tuple(row.marker for row in journal.entries) != golden.markers
        or journal.batch_key != manifest.batch_key
        or journal.scenario_id != asset.scenario_key
        or journal.nonce != manifest.nonce
        or journal.fixture_digest != manifest.pack_digest
        or journal.next_sequence is not None
    ):
        reasons.append("WORKER_FAULT_REPEATED_OR_MISSING_SIDE_EFFECT")
    fault = actual.fault
    if golden.worker_killed and (
        fault.killed_signal != 9
        or not fault.exact_container_restarted
        or fault.container_id not in manifest.worker_container_ids
    ):
        reasons.append("WORKER_FAULT_KILL_NOT_OBSERVED")
    if golden.minimum_actor_processes and (
        len(fault.actor_processes) != 2
        or len({(p.pid, p.start_ticks) for p in fault.actor_processes}) != 2
        or not fault.queued_before_claim
    ):
        reasons.append("WORKER_FAULT_PARALLEL_CLAIM_NOT_OBSERVED")
    if golden.variant == "duplicate_delivery" and (
        len(set(fault.duplicate_tasks)) != 2 or not fault.duplicate_tasks_completed
    ):
        reasons.append("WORKER_FAULT_DUPLICATE_DELIVERY_NOT_OBSERVED")
    reasons.extend(_pre_kill(golden, actual))
    return WorkerVariantReport(
        variant=actual.variant, native_status=actual.native.run.status, reason_codes=tuple(reasons)
    )


def _pre_kill(golden: WorkerGolden, actual: WorkerObservation) -> tuple[str, ...]:
    if not golden.worker_killed:
        return ()
    before = actual.pre_kill_journal
    if before is None or before.metrics is None:
        return ("WORKER_FAULT_PRE_KILL_EVIDENCE_MISSING",)
    if (
        tuple(row.marker for row in before.entries) != golden.markers
        or before.metrics.active_count != 1
        or before.metrics.completed_count != len(golden.markers) - 1
    ):
        return ("WORKER_FAULT_KILL_STAGE_CHANGED",)
    return ()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(
        WorkerManifest.model_validate(read_json(args.output / "manifest.json")),
        WorkerEvidence.model_validate(read_json(args.output / "evidence.json")),
    )
    write_json(args.output / "verification.json", report)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
