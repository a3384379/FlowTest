from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

ReleasePolicyName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
ReleaseCandidateRef = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]


class ReleasePolicyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ReleasePolicyName
    enabled: bool = True
    quality_gate_id: UUID | None = None
    require_quality_gate: bool = True
    require_contract_compatibility: bool = True
    require_impact_evidence: bool = True
    min_impact_coverage_percent: float = Field(default=80, ge=0, le=100)
    require_release_risk: bool = True
    max_release_risk_score: float = Field(default=50, ge=0, le=100)
    require_performance_evidence: bool = False
    require_runner_evidence: bool = False

    @model_validator(mode="after")
    def require_quality_gate_reference(self) -> "ReleasePolicyWrite":
        if self.require_quality_gate and self.quality_gate_id is None:
            raise ValueError("要求质量门禁证据时必须选择 Quality Gate")
        return self


class ReleasePolicyResponse(ReleasePolicyWrite):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class ReleaseDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_policy_id: UUID
    candidate_ref: ReleaseCandidateRef
    test_plan_run_id: UUID | None = None
    deployment_check_id: UUID | None = None
    impact_run_id: UUID | None = None
    release_risk_id: UUID | None = None
    performance_run_id: UUID | None = None
    runner_task_id: UUID | None = None


class ReleaseReasonResponse(BaseModel):
    code: str
    evidence_type: str
    status: Literal["passed", "blocked"]
    message: str
    actual: JsonValue
    expected: JsonValue


class ReleasePolicySnapshotResponse(BaseModel):
    snapshot_version: str
    policy_id: UUID
    name: str
    quality_gate_id: UUID | None
    require_quality_gate: bool
    require_contract_compatibility: bool
    require_impact_evidence: bool
    min_impact_coverage_percent: float
    require_release_risk: bool
    max_release_risk_score: float
    require_performance_evidence: bool
    require_runner_evidence: bool
    policy_updated_at: datetime


class QualityGateEvidenceResponse(BaseModel):
    test_plan_run_id: UUID
    quality_gate_id: UUID
    run_status: str
    status: str
    quality_summary: JsonValue
    metrics: JsonValue | None
    violations: JsonValue | None
    evaluated_at: datetime | None


class ContractEvidenceResponse(BaseModel):
    check_id: UUID
    provider_service_id: UUID
    provider_version: str
    decision: str
    evidence: JsonValue
    checked_at: datetime


class ImpactEvidenceResponse(BaseModel):
    run_id: UUID
    status: str
    source_ref: str
    source_fingerprint: str
    change_count: int
    summary: JsonValue
    coverage_percent: float | None
    total_changes: int | None
    covered_changes: int | None
    gaps: JsonValue | None
    created_at: datetime


class ReleaseRiskEvidenceResponse(BaseModel):
    risk_id: UUID
    impact_run_id: UUID
    algorithm_version: str
    score: float
    quality_score: float
    risk_level: str
    factors: JsonValue
    evidence: JsonValue
    fingerprint: str
    created_at: datetime


class PerformanceGateEvidenceResponse(BaseModel):
    id: UUID
    quality_gate_id: UUID
    status: str
    metrics: JsonValue
    violations: JsonValue
    evaluated_at: datetime


class PerformanceEvidenceResponse(BaseModel):
    run_id: UUID
    scenario_id: UUID
    scenario_version: int
    status: str
    summary: JsonValue
    threshold_results: JsonValue
    gate_statuses: list[str]
    gate_evaluations: list[PerformanceGateEvidenceResponse]
    completed_at: datetime | None


class RunnerLeaseEvidenceResponse(BaseModel):
    id: UUID
    runner_id: UUID
    fencing_token: int
    status: str
    completed_at: datetime | None


class RunnerEvidenceResponse(BaseModel):
    task_id: UUID
    execution_id: UUID
    status: str
    attempts: int
    fencing_token: int
    completed_lease_count: int
    leases: list[RunnerLeaseEvidenceResponse]
    completed_at: datetime | None


class ReleaseEvidenceSnapshotResponse(BaseModel):
    snapshot_version: str
    quality_gate: QualityGateEvidenceResponse | None
    contract_compatibility: ContractEvidenceResponse | None
    impact: ImpactEvidenceResponse | None
    release_risk: ReleaseRiskEvidenceResponse | None
    performance: PerformanceEvidenceResponse | None
    runner: RunnerEvidenceResponse | None


class ReleaseDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    release_policy_id: UUID
    candidate_ref: str
    status: Literal["pass", "block"]
    policy_snapshot: ReleasePolicySnapshotResponse
    evidence_snapshot: ReleaseEvidenceSnapshotResponse
    reasons: list[ReleaseReasonResponse]
    fingerprint: str
    test_plan_run_id: UUID | None
    deployment_check_id: UUID | None
    impact_run_id: UUID | None
    release_risk_id: UUID | None
    performance_run_id: UUID | None
    runner_task_id: UUID | None
    created_by_id: UUID
    created_at: datetime
