from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from app.engine.contracts import NodeStatus, NodeType, WorkflowPhase
from app.schemas.workflows import WorkflowExecutionResponse


class ExecutionCommandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    execution_id: UUID
    command_type: str
    status: str
    idempotency_key: str | None
    request_hash: str
    fencing_token: int | None
    accepted_at: datetime
    dispatched_at: datetime | None
    completed_at: datetime | None


class ExecutionCommandDetailResponse(BaseModel):
    command: ExecutionCommandResponse
    execution: WorkflowExecutionResponse


class ExecutionCheckpointSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    execution_id: UUID
    node_id: str
    node_type: NodeType
    node_name: str
    phase: WorkflowPhase
    attempt: int
    status: NodeStatus
    started_at: datetime | None
    finished_at: datetime


class ExecutionCheckpointResponse(ExecutionCheckpointSummaryResponse):
    model_config = ConfigDict(from_attributes=True)

    best_effort: bool
    input_hash: str
    output_digest: str
    output: JsonValue
    result: dict[str, JsonValue]
    extracted_variables: dict[str, JsonValue]
    snapshot_revision: int
    fencing_token: int
    lease_id: UUID | None
    runner_id: UUID | None
    created_at: datetime
