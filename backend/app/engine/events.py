from collections.abc import AsyncIterator
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.engine.contracts import NodeStatus, WorkflowRunStatus
from app.engine.results import NodeResult


class ExecutionEventType(StrEnum):
    EXECUTION_STARTED = "execution.started"
    NODE_STATUS = "node.status"
    NODE_RESULT = "node.result"
    EXECUTION_COMPLETED = "execution.completed"


class ExecutionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(default=0, ge=0)
    type: ExecutionEventType
    execution_id: UUID
    emitted_at: datetime
    node_id: str | None = None
    node_name: str | None = None
    node_type: str | None = None
    node_status: NodeStatus | None = None
    result: NodeResult | None = None
    attempt: int = Field(default=0, ge=0)
    attempts: int = Field(default=0, ge=0)
    fencing_token: int = Field(default=0, ge=0)
    error_code: str | None = None
    error_message: str | None = None
    execution_status: WorkflowRunStatus | None = None

    @field_validator("emitted_at")
    @classmethod
    def require_utc_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Execution event timestamp must include a UTC offset")
        return value

    @model_validator(mode="after")
    def validate_node_result_event(self) -> "ExecutionEvent":
        if self.type is not ExecutionEventType.NODE_RESULT:
            return self
        if self.node_id is None or self.result is None:
            raise ValueError("Node result event must identify a node and include its result")
        if self.node_status is not self.result.status:
            raise ValueError("Node result event status must match the result envelope")
        return self


class ExecutionEventBus(Protocol):
    async def publish(self, event: ExecutionEvent) -> ExecutionEvent: ...

    def subscribe(
        self, execution_id: UUID, *, after_sequence: int = 0
    ) -> AsyncIterator[ExecutionEvent]: ...
