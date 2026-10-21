from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QualityGateWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    min_pass_rate: float = Field(default=100, ge=0, le=100)
    max_failed: int = Field(default=0, ge=0, le=100_000)
    max_flaky: int = Field(default=0, ge=0, le=100_000)
    max_duration_regression_percent: float = Field(default=20, ge=0, le=10_000)
    require_no_breaking_changes: bool = True


class QualityGateResponse(QualityGateWrite):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class FlakyRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    target_type: str
    target_id: UUID
    target_version: int
    total_runs: int
    passed_runs: int
    failed_runs: int
    transitions: int
    flaky_score: float
    quarantined: bool
    last_status: str | None
    last_run_id: UUID | None
    last_run_at: datetime | None
    updated_at: datetime


class FlakySummaryResponse(BaseModel):
    project_id: UUID
    scope: Literal["project_cumulative"] = "project_cumulative"
    asset_total: int = Field(ge=0)
    record_total: int = Field(ge=0)
    flaky_total: int = Field(ge=0)
    flaky_version_total: int = Field(ge=0)
    quarantined_total: int = Field(ge=0)
    quarantined_version_total: int = Field(ge=0)
    oldest_updated_at: datetime | None
    latest_updated_at: datetime | None
    observed_at: datetime


class FlakyQuarantineUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quarantined: bool


class QualityGateEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    quality_gate_id: UUID
    test_plan_run_id: UUID
    status: str
    metrics: dict[str, Any]
    violations: list[str]
    evaluated_at: datetime


class RunQualityResponse(BaseModel):
    run_id: UUID
    baseline_run_id: UUID | None
    summary: dict[str, Any]
    evaluations: list[QualityGateEvaluationResponse]
