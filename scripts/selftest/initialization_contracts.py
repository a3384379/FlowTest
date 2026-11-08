"""Finite concurrent/partial/unknown native installation proof, without a synthetic Run."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from scripts.selftest.contracts import (
    Contract,
    Identity,
    Sha256,
    TargetDisposalReceipt,
    canonical_digest,
)
from scripts.selftest.fixed_baseline import FixedInstallation
from scripts.selftest.initialization_worker import InstallWorkerReceipt

INIT_SCENARIOS = ("ST-INIT-concurrent", "ST-INIT-partial", "ST-INIT-unknown")


class InstallationInventory(Contract):
    project_id: UUID
    api_ids: tuple[UUID, ...]
    workflow_ids: tuple[UUID, ...]
    case_ids: tuple[UUID, ...]
    suite_ids: tuple[UUID, ...]
    plan_ids: tuple[UUID, ...]
    run_ids: tuple[UUID, ...]
    execution_ids: tuple[UUID, ...]
    environment_ids: tuple[UUID, ...]
    service_ids: tuple[UUID, ...]
    default_service_id: UUID | None
    complete: bool


class InitializationManifest(Contract):
    pack_id: Literal["initialization-boundaries-v1"] = "initialization-boundaries-v1"
    pack_digest: Sha256
    schema_version: Literal["flowtest-initialization-boundaries-v1"] = (
        "flowtest-initialization-boundaries-v1"
    )
    expected_scenarios: tuple[Identity, ...] = INIT_SCENARIOS
    acceptance_id: Literal["ST-INIT-003"] = "ST-INIT-003"
    verification_scope: Literal["diagnostic_subset"] = "diagnostic_subset"
    selected_native_scenarios: tuple[Identity, ...] = ("ST-CORE-echo-boundaries",)
    source_pack_digest: Identity
    project_name: Identity
    nonce: Identity
    source_digest: Identity
    profile: Identity
    target_container_id: Identity
    target_volume: Identity
    target_image: Identity
    created_at: datetime
    deadline: datetime
    provenance: Literal["local_untrusted"] = "local_untrusted"

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class InitializationObservation(Contract):
    scenario_id: Identity
    project_id: UUID
    before: InstallationInventory
    after: InstallationInventory
    repeat: InstallationInventory
    workers: tuple[InstallWorkerReceipt, ...]
    installation: FixedInstallation | None = None
    resumed_installation: FixedInstallation | None = None
    published_mapping_matches: bool
    unknown_posts_before_restart: int | None = None
    unknown_posts_after_restart: int | None = None


class InitializationEvidence(Contract):
    manifest_digest: Identity
    scenarios: tuple[InitializationObservation, ...]
    http_attempts: int
    rejected_attempts: int
    collected_at: datetime
    cleanup_status: Literal["pending", "completed"]
    target_disposal: TargetDisposalReceipt | None = None


class InitializationResult(Contract):
    manifest: InitializationManifest
    evidence: InitializationEvidence
    batch_verdict: Literal["passed", "blocked"]
    exit_code: Literal[0, 2]
    reason_codes: tuple[Identity, ...]
