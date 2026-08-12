from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class AIChangeSetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    impact_run_id: UUID
    release_risk_id: UUID
    title: str = Field(min_length=1, max_length=200)


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
