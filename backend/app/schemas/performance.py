from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.performance import PerformanceScenarioDefinition


class PerformanceScenarioWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    definition: PerformanceScenarioDefinition


class PerformanceScenarioVersionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(default="", max_length=2000)
    definition: PerformanceScenarioDefinition


class PerformanceScenarioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    description: str
    version: int
    status: str
    target_type: str
    definition: PerformanceScenarioDefinition
    compiled_sha256: str
    published_at: datetime | None
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class PerformanceGateEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    quality_gate_id: UUID
    performance_run_id: UUID
    status: str
    metrics: dict[str, object]
    violations: list[str]
    evaluated_at: datetime


class PerformanceRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    scenario_id: UUID
    scenario_version: int
    status: str
    definition_snapshot: PerformanceScenarioDefinition
    compiled_sha256: str
    summary: dict[str, object]
    threshold_results: list[dict[str, object]]
    baseline_run_id: UUID | None
    raw_metrics_artifact_id: UUID | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime
    gate_evaluations: list[PerformanceGateEvaluationResponse] = Field(default_factory=list)
