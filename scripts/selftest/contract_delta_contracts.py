"""Frozen contracts for real contract evolution and published-slot boundaries."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool, model_validator
from scripts.selftest.bootstrap import Installation
from scripts.selftest.contracts import (
    BatchManifest,
    Builds,
    Contract,
    FixtureBudgetScope,
    FixtureJournal,
    McpCallReceipt,
    RequiredDisposal,
    ScenarioObservation,
    Sha256,
    TargetDisposalReceipt,
)
from scripts.selftest.io import JsonObject
from scripts.selftest.mcp_generation_journey import GeneratedAsset
from scripts.selftest.start_plan import PlanSelection

Variant = Literal[
    "contract_delta",
    "regenerate_delta",
    "preview_freeze",
    "slot_foreign",
    "slot_unpublished",
    "slot_drift",
    "slot_positive",
]


class DeltaPhaseGolden(Contract):
    phase: Literal["v1", "v2"]
    api_version: int = Field(ge=1, le=2)
    marker: Literal["", "delta-v2"]
    request_schema: JsonObject
    response_schema: JsonObject
    required_mutations: tuple[str, ...]
    absent_mutations: tuple[str, ...]


class DeltaPack(Contract):
    format: Literal["flowtest-contract-delta-v1"]
    pack_id: Literal["contract-delta-v1"]
    version: Literal["1.0.0"]
    variants: tuple[Variant, ...]
    phases: tuple[DeltaPhaseGolden, ...]
    expected_codes: dict[Variant, str | None]
    max_tool_calls: Literal[100]
    max_requests: Literal[500]
    max_seconds: Literal[600]


class DeltaManifest(Contract):
    pack_digest: Sha256
    binding_fingerprint: Sha256
    binding_nonce: str
    batch_key: str
    nonce: str
    builds: Builds
    installation: Installation
    created_at: datetime
    expires_at: datetime
    scope: FixtureBudgetScope
    required_disposal: RequiredDisposal

    @model_validator(mode="after")
    def exact_window(self) -> "DeltaManifest":
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("时间必须包含时区")
        seconds = (self.expires_at - self.created_at).total_seconds()
        if not 0 < seconds <= 600:
            raise ValueError("总时间预算必须不超过600秒")
        if self.scope.model_dump() != {
            "parent_batch_key": self.batch_key,
            "nonce": self.nonce,
            "limit": 500,
            "expires_at": self.expires_at.timestamp(),
        }:
            raise ValueError("共享目标预算必须绑定本批次及绝对截止时间")
        return self


class DeltaPhaseFreeze(Contract):
    phase: Literal["v1", "v2"]
    asset: GeneratedAsset
    origin: JsonObject
    inspection: JsonObject
    coverage: JsonObject
    compilation: JsonObject
    slot: str
    selection: PlanSelection
    manifest: BatchManifest
    frozen_at: datetime


class DeltaPhaseObservation(Contract):
    phase: Literal["v1", "v2"]
    frozen_digest: Sha256
    observation: ScenarioObservation
    plan_run: JsonObject
    observed_at: datetime


class DeltaPreview(Contract):
    phase: Literal["v1", "v2"]
    preview: JsonObject
    commit: JsonObject | None = None
    merge: JsonObject | None = None
    frozen_at: datetime
    rejection: "DeltaRejection | None" = None


class DeltaRejection(Contract):
    call_id: str
    request: JsonObject
    code: str
    before_execution_ids: tuple[UUID, ...]
    after_execution_ids: tuple[UUID, ...]


class BoundaryObservation(Contract):
    variant: Variant
    project_id: UUID
    workflow_id: UUID | None = None
    case_id: UUID | None = None
    proposal_id: UUID | None = None
    workflow_project_id: UUID | None = None
    workflow_version: int | None = Field(default=None, ge=1)
    workflow_fingerprint: Sha256 | None = None
    case_current_version: int | None = Field(default=None, ge=1)
    proposal_item_id: UUID | None = None
    proposal_review_status: str | None = None
    materialized_case_id: UUID | None = None
    slot: str | None = None
    method: Literal["POST"]
    path: str
    status_code: int = Field(ge=200, le=599)
    error_code: str | None = None
    trace_present: StrictBool
    before_execution_ids: tuple[UUID, ...]
    after_execution_ids: tuple[UUID, ...]
    request_digest: Sha256
    before_fingerprint: Sha256 | None = None
    after_fingerprint: Sha256 | None = None
    observed_at: datetime


class DeltaEvidence(Contract):
    manifest_digest: Sha256
    previews: tuple[DeltaPreview, ...] = Field(default=(), max_length=2)
    phases: tuple[DeltaPhaseFreeze, ...] = Field(default=(), max_length=2)
    observations: tuple[DeltaPhaseObservation, ...] = Field(default=(), max_length=2)
    boundaries: tuple[BoundaryObservation, ...] = Field(default=(), max_length=4)
    calls: tuple[McpCallReceipt, ...] = Field(default=(), max_length=100)
    journal: FixtureJournal | None = None
    fixture_cleanup: Literal["pending", "completed", "failed"] = "pending"
    disposal: TargetDisposalReceipt | None = None
    collected_at: datetime
    failure_code: str | None = None
    admitted_request_upper_bound: int = Field(default=0, ge=0, le=500)
    rejected_requests: int = Field(default=0, ge=0)
    admitted_tool_calls: int = Field(default=0, ge=0, le=100)
    rejected_tool_calls: int = Field(default=0, ge=0)


class DeltaCheck(Contract):
    variant: Variant
    status: Literal["matched", "mismatched", "incomplete"]
    findings: tuple[str, ...]


class DeltaReport(Contract):
    pack_id: Literal["contract-delta-v1"] = "contract-delta-v1"
    pack_digest: Sha256
    manifest_digest: Sha256
    batch_key: str
    verification_scope: Literal["contract_delta_and_slot_only"] = "contract_delta_and_slot_only"
    trust: Literal["local_untrusted"] = "local_untrusted"
    verdict: Literal["passed", "failed", "blocked"]
    exit_code: Literal[0, 1, 2]
    findings: tuple[str, ...]
    scenarios: tuple[DeltaCheck, ...]
