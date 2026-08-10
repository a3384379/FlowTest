from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

ReviewStatus = Literal["pending", "accepted", "rejected"]
CaseName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ContractRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    baseline_run_id: UUID | None
    source_name: str
    source_type: str
    source_sha256: str
    status: str
    diff_summary: dict[str, JsonValue]
    breaking_changes: list[dict[str, JsonValue]]
    coverage: dict[str, JsonValue]
    generated_case_count: int
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class GeneratedContractCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contract_run_id: UUID
    operation_key: str
    operation_id: str
    method: str
    path: str
    generation_kind: str
    name: str
    definition: dict[str, JsonValue]
    review_status: ReviewStatus
    review_note: str
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ContractCaseReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CaseName | None = None
    definition: dict[str, JsonValue] | None = None
    note: str = Field(default="", max_length=2000)
