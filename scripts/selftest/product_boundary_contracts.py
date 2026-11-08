"""Explicit finite public product-boundary observations, separate from product verdicts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field
from scripts.selftest.contracts import (
    BatchEvidence,
    BatchManifest,
    Builds,
    Contract,
    Identity,
    RequiredDisposal,
    Sha256,
    TargetDisposalReceipt,
)
from scripts.selftest.initialization_contracts import InstallationInventory
from scripts.selftest.security_boundary_contracts import DenialObservation


class ProductBoundaryRequest(Contract):
    operation: Identity
    status: int
    code: Identity | None = None


class ProductBoundarySpec(Contract):
    key: Identity
    group: Literal["installation", "refusal", "new_run", "projection", "cleanup", "retention"]
    acceptance_variants: tuple[Identity, ...]
    requests: tuple[ProductBoundaryRequest, ...] = ()


class ProductBoundaryPack(Contract):
    pack_id: Literal["product-boundaries-v1"]
    version: Literal["1.0.0"]
    scenarios: tuple[ProductBoundarySpec, ...] = Field(min_length=1, max_length=50)


class ProductBatchSnapshot(Contract):
    id: UUID
    project_id: UUID
    installation_id: UUID
    plan_run_ids: tuple[UUID, ...]
    execution_ids: tuple[UUID, ...]
    phase: Identity
    verdict: Identity
    sealed_verdict: Identity | None
    evidence_integrity: Identity
    cleanup_status: Identity
    manifest_digest: Sha256
    resource_digest: Sha256 | None
    sealed_at: datetime | None
    expected_scenario_ids: tuple[Identity, ...]
    actual_scenario_ids: tuple[Identity, ...]
    observed_statuses: tuple[Identity | None, ...]
    verification_statuses: tuple[Identity, ...]
    artifact_ids: tuple[UUID, ...]
    provenance: Literal["local_untrusted"]


class MaintenanceReceipt(Contract):
    container_id: Sha256
    ownership_nonce: Identity
    clock: datetime
    repeat: bool
    projects_scanned: int
    workflow_executions_deleted: int
    test_plan_runs_deleted: int
    artifacts_deleted: int
    storage_failures: int


class ProductBoundaryObservation(Contract):
    key: Identity
    requests: tuple[DenialObservation, ...] = Field(default=(), max_length=20)
    before: InstallationInventory | None = None
    after: InstallationInventory | None = None
    batches: tuple[ProductBatchSnapshot, ...] = Field(default=(), max_length=3)
    installation_ids: tuple[UUID, ...] = ()
    mapping_digests: tuple[Sha256, ...] = ()
    safe_fields: tuple[Identity, ...] = ()
    listed_ids: tuple[UUID, ...] = ()
    listed_total: int | None = None
    namespace_statuses: tuple[int, ...] = ()
    object_statuses: tuple[int, ...] = ()
    maintenance: tuple[MaintenanceReceipt, ...] = ()
    observed_at: datetime


class ProductNativeProof(Contract):
    manifest: BatchManifest
    evidence: BatchEvidence


class ProductBoundaryManifest(Contract):
    pack_digest: Sha256
    source_digest: Sha256
    builds: Builds
    profile: Literal["full", "compact", "standalone"]
    expected_keys: tuple[Identity, ...]
    project_id: UUID
    project_name: Identity
    ownership_nonce: Identity
    created_at: datetime
    deadline: datetime
    disposal: RequiredDisposal


class ProductBoundaryEvidence(Contract):
    manifest_digest: Sha256
    native: tuple[ProductNativeProof, ...] = Field(default=(), max_length=2)
    observations: tuple[ProductBoundaryObservation, ...] = Field(default=(), max_length=50)
    http_attempts: int = Field(ge=0, le=500)
    rejected_attempts: int = Field(ge=0)
    collected_at: datetime
    disposal: TargetDisposalReceipt | None = None


class ProductBoundaryRowReport(Contract):
    key: Identity
    reason_codes: tuple[Identity, ...]


class ProductBoundaryReport(Contract):
    pack_digest: Sha256
    manifest_digest: Sha256
    expected_keys: tuple[Identity, ...]
    scenarios: tuple[ProductBoundaryRowReport, ...]
    exit_code: Literal[0, 2]
    reason_codes: tuple[Identity, ...]
    model_calls: Literal[0] = 0
    trust: Literal["local_untrusted"] = "local_untrusted"
