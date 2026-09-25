from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.sandbox_preview import WorkflowRunPurpose
from app.engine.contracts import (
    NodeStatus,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowPhase,
    WorkflowRegion,
    WorkflowRunStatus,
)

RuntimeVariableName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", max_length=160)]


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    folder_id: UUID | None = None
    definition: WorkflowDefinition


class WorkflowDraftUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    folder_id: UUID | None = None
    definition: WorkflowDefinition | None = None


class WorkflowControlBlockInsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    edge_id: str = Field(min_length=1, max_length=128)
    node: WorkflowNode
    regions: list[WorkflowRegion] = Field(default_factory=list, max_length=500)
    request_budget: int | None = Field(default=None, ge=1, le=10_000)
    cleanup_request_budget: int | None = Field(default=None, ge=1, le=1000)


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    folder_id: UUID | None
    name: str
    description: str
    draft_definition: WorkflowDefinition
    draft_revision: int
    current_version: int | None
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class WorkflowVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID
    version: int
    definition: WorkflowDefinition
    fingerprint: str
    created_by_id: UUID
    published_at: datetime


class WorkflowVersionChangeResponse(BaseModel):
    path: str
    before: JsonValue
    after: JsonValue


class WorkflowVersionDiffResponse(BaseModel):
    from_version: int
    to_version: int
    changes: list[WorkflowVersionChangeResponse]


class WorkflowExecuteRequest(BaseModel):
    environment_id: UUID
    version: int | None = Field(default=None, ge=1)
    runtime_variables: dict[RuntimeVariableName, str] = Field(default_factory=dict)
    runtime_headers: dict[str, str] = Field(default_factory=dict)


class WorkflowCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False
    reason: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def require_force_reason(self) -> "WorkflowCancelRequest":
        if self.force and (self.reason is None or not self.reason.strip()):
            raise ValueError("强制取消必须提供审计原因")
        if not self.force and self.reason is not None:
            raise ValueError("普通取消不接受强制取消原因")
        return self


class WorkflowDebugRequest(WorkflowExecuteRequest):
    breakpoint_node_id: str = Field(min_length=1, max_length=128)


class WorkflowFailedItemRerunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loop_node_id: str = Field(min_length=1, max_length=128)
    input_indices: list[int] = Field(min_length=1, max_length=1000)
    write_retry_strategy: Literal["reject", "verified_safe_to_retry"] = "reject"
    upstream_resource_status: Literal["unverified", "confirmed_valid", "expired"] = "unverified"
    verification_note: str | None = Field(default=None, min_length=8, max_length=2000)

    @model_validator(mode="after")
    def validate_selection(self) -> "WorkflowFailedItemRerunRequest":
        if any(index < 0 for index in self.input_indices):
            raise ValueError("轮次索引不能小于零")
        if len(set(self.input_indices)) != len(self.input_indices):
            raise ValueError("轮次索引不能重复")
        if (
            self.write_retry_strategy == "verified_safe_to_retry"
            or self.upstream_resource_status == "confirmed_valid"
        ) and self.verification_note is None:
            raise ValueError("确认外部状态时必须填写查证说明")
        return self


class WorkflowExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    redaction_mode: str | None = None
    redaction_policy_version: int | None = None
    workflow_id: UUID | None
    workflow_version_id: UUID | None
    environment_id: UUID
    triggered_by_id: UUID
    parent_execution_id: UUID | None
    dataset_row_index: int | None
    derived_from_execution_id: UUID | None = None
    rerun_loop_node_id: str | None = None
    rerun_input_indices: list[int] | None = None
    run_purpose: WorkflowRunPurpose
    source_change_set_id: UUID | None
    preview_approval_id: UUID | None
    preview_budget: dict[str, JsonValue]
    preview_evidence: dict[str, JsonValue]
    status: WorkflowRunStatus
    main_status: WorkflowRunStatus | None
    cleanup_status: WorkflowRunStatus | None
    cleanup_report: dict[str, JsonValue]
    snapshot: dict[str, JsonValue]
    context: dict[str, JsonValue]
    error_code: str | None
    error_message: str | None
    cancel_requested_at: datetime | None
    force_cancel_requested_at: datetime | None
    force_cancel_reason: str | None
    started_at: datetime
    completed_at: datetime | None


class WorkflowNodeExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_execution_id: UUID
    node_id: str
    node_type: str
    name: str
    phase: WorkflowPhase
    best_effort: bool
    status: NodeStatus
    attempts: int
    output: JsonValue
    result: dict[str, JsonValue] | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime


class WorkflowExecutionDetailResponse(BaseModel):
    execution: WorkflowExecutionResponse
    nodes: list[WorkflowNodeExecutionResponse]
    children: list[WorkflowExecutionResponse] = Field(default_factory=list)


class WorkflowControlRecordSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ordinal: int
    status: str
    test_verdict: str


class WorkflowControlRecordDetailResponse(WorkflowControlRecordSummaryResponse):
    kind: str
    payload: dict[str, JsonValue]


class WorkflowDebugNodeResponse(BaseModel):
    node_id: str
    node_type: str
    name: str
    status: NodeStatus
    attempts: int
    output: JsonValue
    result: dict[str, JsonValue]
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime


class WorkflowDebugResponse(BaseModel):
    status: WorkflowRunStatus
    mode: str
    target_node_id: str
    context: dict[str, JsonValue]
    nodes: list[WorkflowDebugNodeResponse]
