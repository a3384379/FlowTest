"""Bounded product projections; raw observer payloads remain authorized artifacts."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.self_tests import Digest, Identity, Reason, ScenarioKey, SelfTestDTO


class SelfTestMetric(SelfTestDTO):
    key: Identity
    label: Identity
    numerator: int = Field(ge=0, le=100000)
    denominator: int = Field(ge=0, le=100000)
    basis: Annotated[str, Field(min_length=1, max_length=500)]
    exclusions: tuple[Reason, ...] = Field(default=(), max_length=10)


class SelfTestDiagnostic(SelfTestDTO):
    code: Identity
    severity: Literal["blocker", "review", "input", "unsupported"]
    scenario_id: Identity | None = None
    oracle_id: Identity | None = None
    field_path: Annotated[str, Field(max_length=500)] | None = None
    repair_hint: Annotated[str, Field(max_length=1000)]


class SelfTestCaseSlot(ScenarioKey):
    workflow_slot: Identity | None
    case_id: UUID
    case_version: int = Field(ge=1)
    environment_id: UUID | None = None


class SelfTestComparison(SelfTestDTO):
    field: Identity
    expected: Annotated[str, Field(max_length=4000)]
    observed: Annotated[str, Field(max_length=4000)]
    difference: Literal["equal", "different", "not_recorded", "not_required"]
    # Receipt outcome is not recomputed by this read model.
    verification_status: Literal[
        "pending", "matched", "mismatched", "incomplete", "error", "unsupported"
    ]
    reason_codes: tuple[Reason, ...] = Field(default=(), max_length=30)


class SelfTestScenarioComparison(ScenarioKey):
    execution_id: UUID | None
    items: tuple[SelfTestComparison, ...] = Field(max_length=100)


class SelfTestInsights(SelfTestDTO):
    batch_id: UUID
    manifest_digest: Digest
    task_set_digest: Digest
    template_version: Identity
    scope: Literal["full_pack", "selected_suites", "diagnostic_subset"]
    assisted_before_batch_id: UUID | None
    metrics: tuple[SelfTestMetric, ...] = Field(max_length=11)
    diagnostics: tuple[SelfTestDiagnostic, ...] = Field(max_length=500)
    case_slots: tuple[SelfTestCaseSlot, ...] = Field(max_length=100)
    comparisons: tuple[SelfTestScenarioComparison, ...] = Field(max_length=100)
    reason_codes: tuple[Reason, ...] = Field(default=(), max_length=30)


class InstallationResume(SelfTestDTO):
    expected_revision: int = Field(ge=0, strict=True)
    environment_fingerprint: Digest
    confirmed: Literal[True]
