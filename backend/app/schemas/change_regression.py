from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.impact import OpenApiDiffReference, SchemaDiffReference

ChangeRegressionStatus = Literal[
    "review_required",
    "approved",
    "queued",
    "running",
    "evidence_ready",
    "passed",
    "blocked",
    "failed",
]


class ChangeRegressionRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    source_ref: str = Field(default="", max_length=200)
    candidate_ref: str = Field(min_length=1, max_length=200)
    git_diff: str | None = Field(default=None, max_length=2 * 1024 * 1024)
    openapi_diffs: list[OpenApiDiffReference] = Field(default_factory=list, max_length=20)
    schema_diffs: list[SchemaDiffReference] = Field(default_factory=list, max_length=20)
    test_plan_id: UUID
    release_policy_id: UUID
    release_risk_id: UUID | None = None
    deployment_check_id: UUID | None = None
    generate_missing_tests: bool = True

    @model_validator(mode="after")
    def require_change_source(self) -> "ChangeRegressionRunCreate":
        if not self.git_diff and not self.openapi_diffs and not self.schema_diffs:
            raise ValueError("至少提供一种 Git 或 Schema 变更来源")
        return self


class ChangeRegressionMaterializationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_definition_id: UUID
    environment_id: UUID
    endpoint_variant: str | None = Field(default=None, min_length=1, max_length=80)
    scenario_ids: list[str] = Field(default_factory=list, max_length=1000)


class ChangeRegressionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, JsonValue] | None = None
    note: str = Field(default="", max_length=2000)
    materialization: ChangeRegressionMaterializationInput | None = None


class ChangeRegressionApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(default="", max_length=2000)


class ChangeRegressionStageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sequence: int
    stage: str
    status: str
    details: dict[str, JsonValue]
    actor_id: UUID | None
    created_at: datetime


class ChangeRegressionMissingTestResponse(BaseModel):
    item_id: UUID
    title: str
    proposed_content: dict[str, JsonValue]
    review_status: Literal["pending", "accepted", "rejected"]
    review_note: str
    materialized_resource_type: str | None
    materialized_resource_id: UUID | None


class ChangeRegressionRunSummaryResponse(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    source_ref: str
    source_fingerprint: str
    candidate_ref: str
    status: ChangeRegressionStatus
    impact_run_id: UUID
    test_plan_id: UUID
    test_plan_run_id: UUID | None
    release_policy_id: UUID
    change_set_id: UUID | None
    release_decision_id: UUID | None
    selected_asset_count: int
    missing_test_count: int
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class ChangeRegressionRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    source_ref: str
    source_fingerprint: str
    candidate_ref: str
    status: ChangeRegressionStatus
    impact_run_id: UUID
    test_plan_id: UUID
    test_plan_run_id: UUID | None
    release_policy_id: UUID
    release_risk_id: UUID | None
    deployment_check_id: UUID | None
    change_set_id: UUID | None
    release_decision_id: UUID | None
    selected_assets: list[dict[str, JsonValue]]
    selection_summary: dict[str, JsonValue]
    missing_tests: list[ChangeRegressionMissingTestResponse]
    evidence: dict[str, JsonValue]
    failure_triage: dict[str, JsonValue]
    approved_by_id: UUID | None
    approved_at: datetime | None
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime
    stages: list[ChangeRegressionStageResponse]
