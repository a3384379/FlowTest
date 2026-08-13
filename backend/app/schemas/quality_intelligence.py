from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.quality_intelligence import RiskFactor


class ReleaseRiskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    impact_run_id: UUID
    title: str = Field(min_length=1, max_length=200)
    window_days: int = Field(default=30, ge=7, le=90)


class FailureClusterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    release_risk_id: UUID
    fingerprint: str
    title: str
    failure_category: str
    error_code: str | None
    node_type: str | None
    occurrence_count: int
    baseline_count: int
    affected_workflow_ids: list[str]
    affected_workflow_names: list[str]
    sample_execution_ids: list[str]
    confidence: float
    regression_percent: float | None
    recommendation: str
    created_at: datetime


class ReleaseRiskSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    impact_run_id: UUID
    title: str
    algorithm_version: str
    window_days: int
    score: float
    quality_score: float
    risk_level: str
    fingerprint: str
    created_by_id: UUID
    created_at: datetime


class ReleaseRiskDetailResponse(ReleaseRiskSummaryResponse):
    window_started_at: datetime
    window_ended_at: datetime
    baseline_started_at: datetime
    baseline_ended_at: datetime
    factors: list[RiskFactor]
    evidence_snapshot: dict[str, Any]
    quality_trend: list[dict[str, Any]]
    recommended_tests: list[dict[str, Any]]
    failure_clusters: list[FailureClusterResponse]
