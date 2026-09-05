from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.domain.flow_spec import (
    FlowSpec,
    FlowSpecCompatibilityResult,
    FlowSpecDiffItem,
    FlowSpecValidationResult,
)
from app.domain.flow_spec_v2 import FlowSpecV2
from app.domain.integration_plans import IntegrationPlan, IntegrationPlanCompilation
from app.domain.proposal_provenance import FlowSpecProposalOrigin as FlowSpecProposalOrigin
from app.engine.contracts import WorkflowDefinition


class FlowSpecValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: FlowSpec | FlowSpecV2


class FlowSpecImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: FlowSpec | FlowSpecV2
    workflow_id: UUID | None = None
    source_ref: str | None = Field(default=None, max_length=512)
    service_mappings: dict[str, UUID] = Field(default_factory=dict, max_length=500)
    operation_mappings: dict[str, UUID] = Field(default_factory=dict, max_length=1000)
    operation_version_mappings: dict[str, int] = Field(default_factory=dict, max_length=1000)


class FlowSpecExportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: UUID
    version: int | None
    draft_revision: int | None
    fingerprint: str
    spec: FlowSpec | FlowSpecV2
    validation: FlowSpecValidationResult
    compatibility: FlowSpecCompatibilityResult


class FlowSpecValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fingerprint: str
    spec: FlowSpec | FlowSpecV2
    validation: FlowSpecValidationResult
    compatibility: FlowSpecCompatibilityResult


class FlowSpecDiffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    before: FlowSpec | FlowSpecV2 | None = None
    after: FlowSpec | FlowSpecV2


class FlowSpecDiffResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    before_fingerprint: str | None
    after_fingerprint: str
    changes: list[FlowSpecDiffItem]


class FlowSpecChangeSetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    status: str
    source_type: Literal["flow_spec"]
    source_ref: str | None
    source_fingerprint: str
    target_workflow_id: UUID | None
    target_revision: int | None
    target_snapshot_sha256: str | None
    review_status: Literal["pending", "accepted", "rejected"]
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    applied_at: datetime | None
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class FlowSpecChangeSetDetailResponse(FlowSpecChangeSetResponse):
    spec: FlowSpec | FlowSpecV2
    validation: FlowSpecValidationResult
    compatibility: FlowSpecCompatibilityResult
    diff: list[FlowSpecDiffItem]


class FlowSpecVisualProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-visual-flow-proposal-v1"] = "flowtest-visual-flow-proposal-v1"
    proposal: FlowSpecChangeSetDetailResponse
    existing_definition: WorkflowDefinition | None
    proposed_definition: WorkflowDefinition
    integration_plan: IntegrationPlan | None
    compilation: IntegrationPlanCompilation | None
    service_mappings: dict[str, UUID]
    operation_mappings: dict[str, UUID]
    operation_version_mappings: dict[str, int]


class FlowSpecReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accept: bool
    note: str = Field(default="", max_length=2000)


class FlowSpecApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_set_id: UUID
    workflow_id: UUID
    draft_revision: int
    fingerprint: str
    applied_at: datetime


class FlowSpecChangeSetListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FlowSpecChangeSetResponse]
    total: int
    page: int
    page_size: int


class FlowSpecChangeSetCursorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_at: datetime
    id: UUID


class FlowSpecProposalResponse(FlowSpecChangeSetResponse):
    proposal_origin: FlowSpecProposalOrigin


class FlowSpecProposalListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FlowSpecProposalResponse]
    next_cursor: FlowSpecChangeSetCursorResponse | None
    page_size: int


class FlowSpecMcpProposalListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FlowSpecChangeSetResponse]
    next_cursor: FlowSpecChangeSetCursorResponse | None
    page_size: int


def flow_spec_payload(value: FlowSpec | FlowSpecV2) -> dict[str, JsonValue]:
    return value.model_dump(mode="json", by_alias=True)
