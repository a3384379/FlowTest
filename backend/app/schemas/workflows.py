from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.engine.contracts import NodeStatus, WorkflowDefinition, WorkflowRunStatus

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


class WorkflowDebugRequest(WorkflowExecuteRequest):
    breakpoint_node_id: str = Field(min_length=1, max_length=128)


class WorkflowExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    environment_id: UUID
    triggered_by_id: UUID
    parent_execution_id: UUID | None
    dataset_row_index: int | None
    status: WorkflowRunStatus
    snapshot: dict[str, JsonValue]
    context: dict[str, JsonValue]
    error_code: str | None
    error_message: str | None
    cancel_requested_at: datetime | None
    started_at: datetime
    completed_at: datetime | None


class WorkflowNodeExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_execution_id: UUID
    node_id: str
    node_type: str
    name: str
    status: NodeStatus
    attempts: int
    output: JsonValue
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime


class WorkflowExecutionDetailResponse(BaseModel):
    execution: WorkflowExecutionResponse
    nodes: list[WorkflowNodeExecutionResponse]
    children: list[WorkflowExecutionResponse] = Field(default_factory=list)


class WorkflowDebugNodeResponse(BaseModel):
    node_id: str
    node_type: str
    name: str
    status: NodeStatus
    attempts: int
    output: JsonValue
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
