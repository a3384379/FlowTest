from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

AIGenericJobType = Literal[
    "schema_cases", "assertion_suggestions", "workflow_draft", "failure_analysis"
]
AIJobType = Literal[
    "schema_cases", "assertion_suggestions", "workflow_draft", "failure_analysis", "change_set"
]
AIJobStatus = Literal["pending", "running", "completed", "failed"]
AISuggestionType = Literal["test_case", "assertion", "workflow", "failure_analysis"]
AIReviewStatus = Literal["pending", "accepted", "rejected"]
ReviewNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class AIStatusResponse(BaseModel):
    enabled: bool
    model: str | None
    sample_sharing_enabled: bool


class AIProjectSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_sharing_enabled: bool


class AIJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    job_type: AIGenericJobType
    schema_document: dict[str, JsonValue] | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    sample: JsonValue | None = None

    @model_validator(mode="after")
    def require_context(self) -> "AIJobCreateRequest":
        if self.schema_document is None and not self.metadata:
            raise ValueError("AI 任务必须提供 Schema 或脱敏元数据")
        return self


class AIJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    job_type: AIJobType
    status: AIJobStatus
    input_sha256: str
    prompt_template_version: str
    model_name: str
    sample_included: bool
    token_usage: dict[str, int]
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class AISuggestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    position: int
    suggestion_type: AISuggestionType
    title: str
    content: dict[str, JsonValue]
    review_status: AIReviewStatus
    review_note: str
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    accepted_resource_type: str | None
    accepted_resource_id: UUID | None
    created_at: datetime
    updated_at: datetime


class AISuggestionReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, JsonValue] | None = None
    note: ReviewNote = ""
