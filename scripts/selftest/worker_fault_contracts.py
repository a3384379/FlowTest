"""Frozen worker fault requirements and bounded native observations."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field
from scripts.selftest.contracts import (
    Builds,
    Contract,
    FixtureJournal,
    RequiredDisposal,
    Sha256,
    TargetDisposalReceipt,
)
from scripts.selftest.runtime_faults import Assets, Snapshot

Variant = Literal["double_claim", "duplicate_delivery", "worker_death", "recovery"]
SCENARIOS: tuple[Variant, ...] = ("double_claim", "duplicate_delivery", "worker_death", "recovery")


class WorkerGolden(Contract):
    variant: Variant
    status: Literal["passed", "failed"]
    markers: tuple[Literal["first", "follow", "cleanup"], ...]
    minimum_actor_processes: int = Field(ge=0, le=2)
    worker_killed: bool


class WorkerPack(Contract):
    schema_version: Literal["flowtest-worker-fault-pack-v1"]
    pack_id: Literal["worker-faults-v1"]
    pack_version: Literal["1.0.0"]
    max_requests: Literal[100]
    max_runtime_seconds: Literal[300]
    lease_seconds: Literal[60]
    scenarios: tuple[WorkerGolden, ...] = Field(min_length=4, max_length=4)


class WorkerManifest(Contract):
    schema_version: Literal["flowtest-worker-fault-manifest-v1"] = (
        "flowtest-worker-fault-manifest-v1"
    )
    pack_digest: Sha256
    profile: Literal["full", "compact"]
    builds: Builds
    source_digest: Sha256
    batch_key: str = Field(min_length=1, max_length=80)
    nonce: str = Field(min_length=16, max_length=160)
    created_at: datetime
    deadline: datetime
    disposal: RequiredDisposal
    worker_container_ids: tuple[Sha256, ...] = Field(min_length=1, max_length=2)
    assets: tuple[Assets, ...] = Field(min_length=4, max_length=4)


class WorkerProcess(Contract):
    pid: int = Field(ge=1)
    start_ticks: int = Field(ge=1)
    exit_code: Literal[0]


class WorkerFaultReceipt(Contract):
    container_id: Sha256
    actor_processes: tuple[WorkerProcess, ...] = Field(default=(), max_length=2)
    queued_before_claim: bool = False
    killed_signal: Literal[9] | None = None
    exact_container_restarted: bool = False
    duplicate_tasks: tuple[UUID, ...] = Field(default=(), max_length=2)
    duplicate_tasks_completed: bool = False


class WorkerObservation(Contract):
    variant: Variant
    run_id: UUID
    native: Snapshot
    native_error_codes: tuple[str | None, ...] = Field(max_length=2)
    journal: FixtureJournal
    fault: WorkerFaultReceipt
    source_case_id: UUID
    source_workflow_id: UUID
    source_workflow_fingerprint: Sha256
    pre_kill_journal: FixtureJournal | None = None


class WorkerEvidence(Contract):
    schema_version: Literal["flowtest-worker-fault-evidence-v1"] = (
        "flowtest-worker-fault-evidence-v1"
    )
    manifest_digest: Sha256
    collected_at: datetime
    observations: tuple[WorkerObservation, ...] = Field(max_length=4)
    disposal: TargetDisposalReceipt | None = None


class WorkerVariantReport(Contract):
    variant: Variant
    native_status: str | None
    reason_codes: tuple[str, ...]


class WorkerReport(Contract):
    schema_version: Literal["flowtest-worker-fault-verification-v1"] = (
        "flowtest-worker-fault-verification-v1"
    )
    manifest_digest: Sha256
    evidence_digest: Sha256
    scenario_ids: tuple[str, ...]
    exit_code: Literal[0, 2]
    reason_codes: tuple[str, ...]
    scenarios: tuple[WorkerVariantReport, ...]
    model_calls: Literal[0] = 0
    trust: Literal["local_untrusted"] = "local_untrusted"
