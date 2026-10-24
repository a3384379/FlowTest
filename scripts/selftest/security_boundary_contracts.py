"""Safe, finite security-governance probe contracts; no native execution is claimed."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool
from scripts.selftest.contracts import (
    Contract,
    Identity,
    Sha256,
    TargetDisposalReceipt,
    canonical_digest,
)

SECURITY_SCENARIOS = (
    "ST-SECURITY-owner-self-sign",
    "ST-SECURITY-editor-self-sign",
    "ST-SECURITY-manual-report",
    "ST-SECURITY-write-only-export",
    "ST-SECURITY-project-redaction",
)


class BoundaryManifest(Contract):
    pack_id: Literal["security-boundaries-v1"] = "security-boundaries-v1"
    pack_digest: Sha256
    schema_version: Literal["flowtest-security-boundaries-v1"] = "flowtest-security-boundaries-v1"
    purpose: Literal["governance_negative_and_secret_boundary_only"] = (
        "governance_negative_and_secret_boundary_only"
    )
    expected_scenarios: tuple[Identity, ...] = SECURITY_SCENARIOS
    project_name: Identity
    nonce: Identity
    profile: Identity
    source_digest: Identity
    target_container_id: Identity
    target_image: Identity
    target_volume: Identity
    created_at: datetime
    deadline: datetime
    provenance: Literal["local_untrusted"] = "local_untrusted"

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class BoundaryIdentity(Contract):
    organization_id: UUID
    project_ids: tuple[UUID, UUID]
    owner_id: UUID
    editor_id: UUID
    observer_id: UUID


class DenialObservation(Contract):
    operation: Identity
    status: int = Field(ge=100, le=599)
    code: Identity | None = None
    trace_id: Identity | None = None
    response_digest: Sha256


class BoundaryObservation(Contract):
    scenario_id: Identity
    role: Literal["owner", "editor", "observer"]
    actor_id: UUID
    is_system_admin: StrictBool
    permission_role: Literal["owner", "editor", "viewer"]
    denials: tuple[DenialObservation, ...] = Field(default=(), max_length=20)
    sentinel_present: tuple[StrictBool, ...] = ()
    forbidden_secret_keys: tuple[Identity, ...] = ()
    observation_digests: tuple[Sha256, ...] = ()
    artifact_id: UUID | None = None
    artifact_purpose: Identity | None = None
    native_run_ids: tuple[UUID, ...] = ()
    native_executions: tuple[UUID, ...] = ()
    complete: StrictBool


class BoundaryEvidence(Contract):
    manifest_digest: Sha256
    identities: BoundaryIdentity
    scenarios: tuple[BoundaryObservation, ...] = Field(min_length=5, max_length=5)
    http_attempts: int = Field(ge=1, le=500)
    rejected_attempts: int = Field(ge=0)
    cleanup_status: Literal["pending", "completed"]
    target_disposal: TargetDisposalReceipt | None = None
    collected_at: datetime


class BoundaryResult(Contract):
    manifest: BoundaryManifest
    evidence: BoundaryEvidence
    batch_verdict: Literal["passed", "blocked"]
    exit_code: Literal[0, 2]
    reason_codes: tuple[Identity, ...]
