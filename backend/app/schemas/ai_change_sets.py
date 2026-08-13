from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.engine.contracts import WorkflowDefinition
from app.schemas.test_assets import AssetName, TagName, TestCaseDefinitionInput


class AITestCaseDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AssetName
    description: str = Field(max_length=4000)
    tags: list[TagName] = Field(default_factory=list, max_length=20)
    definition: TestCaseDefinitionInput


class AITestCaseDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AssetName | None = None
    description: str | None = Field(default=None, max_length=4000)
    tags: list[TagName] | None = Field(default=None, max_length=20)
    definition: TestCaseDefinitionInput | None = None


class AIWorkflowDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AssetName
    description: str = Field(max_length=4000)
    definition: WorkflowDefinition


class AIWorkflowDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AssetName | None = None
    description: str | None = Field(default=None, max_length=4000)
    definition: WorkflowDefinition | None = None


class AIChangeSetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    impact_run_id: UUID
    release_risk_id: UUID
    title: AssetName


class AIChangeItemReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, JsonValue] | None = None
    note: str = Field(default="", max_length=2000)


class AIChangeItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    position: int
    item_type: Literal["test_case", "workflow", "assertion"]
    action: Literal["create", "update"]
    title: str
    target_resource_id: UUID | None
    target_snapshot_sha256: str | None
    proposed_content: dict[str, JsonValue]
    review_status: Literal["pending", "accepted", "rejected"]
    review_note: str
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    materialized_resource_type: str | None
    materialized_resource_id: UUID | None
    created_at: datetime
    updated_at: datetime


class AIChangeSetSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    impact_run_id: UUID
    release_risk_id: UUID
    ai_job_id: UUID
    title: str
    status: str
    source_fingerprint: str
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class AIChangeSetDetailResponse(AIChangeSetSummaryResponse):
    source_snapshot: dict[str, JsonValue]
    items: list[AIChangeItemResponse]
