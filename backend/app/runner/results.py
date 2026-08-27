from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, model_validator

from app.engine.contracts import NodeStatus, NodeType, WorkflowRunStatus
from app.engine.results import NodeResult
from app.engine.scheduler import NodeRunRecord, WorkflowRunResult


class RunnerNodeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(min_length=1, max_length=128)
    node_type: NodeType
    name: str = Field(min_length=1, max_length=200)
    status: NodeStatus
    attempts: int = Field(ge=0, le=100)
    output: JsonValue = None
    result: NodeResult
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = Field(default=None, max_length=1000)
    started_at: datetime | None
    completed_at: datetime
    input_hash: str | None = None

    @classmethod
    def from_domain(cls, record: NodeRunRecord) -> "RunnerNodeRecord":
        return cls(
            node_id=record.node_id,
            node_type=record.node_type,
            name=record.name,
            status=record.status,
            attempts=record.attempts,
            output=record.output,
            result=record.result,
            error_code=record.error_code,
            error_message=record.error_message,
            started_at=record.started_at,
            completed_at=record.completed_at,
            input_hash=record.input_hash,
        )

    def to_domain(self) -> NodeRunRecord:
        return NodeRunRecord(
            node_id=self.node_id,
            node_type=self.node_type,
            name=self.name,
            status=self.status,
            attempts=self.attempts,
            output=self.output,
            result=self.result,
            error_code=self.error_code,
            error_message=self.error_message,
            started_at=self.started_at,
            completed_at=self.completed_at,
            input_hash=self.input_hash,
        )


class RunnerWorkflowResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: WorkflowRunStatus
    records: tuple[RunnerNodeRecord, ...] = Field(max_length=2000)
    context: dict[str, JsonValue]

    @model_validator(mode="after")
    def require_terminal_status(self) -> "RunnerWorkflowResult":
        if self.status in {WorkflowRunStatus.QUEUED, WorkflowRunStatus.RUNNING}:
            raise ValueError("Runner workflow result must be terminal")
        return self

    @classmethod
    def from_domain(cls, result: WorkflowRunResult) -> "RunnerWorkflowResult":
        return cls(
            status=result.status,
            records=tuple(RunnerNodeRecord.from_domain(record) for record in result.records),
            context=result.context,
        )

    def to_domain(self) -> WorkflowRunResult:
        return WorkflowRunResult(
            status=self.status,
            records=tuple(record.to_domain() for record in self.records),
            context=self.context,
        )


class RunnerSingleExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["run"] = "run"
    execution_id: UUID
    result: RunnerWorkflowResult


class RunnerBatchChildResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: UUID
    result: RunnerWorkflowResult


class RunnerBatchExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["batch"] = "batch"
    execution_id: UUID
    children: tuple[RunnerBatchChildResult, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_unique_children(self) -> "RunnerBatchExecutionResult":
        identifiers = tuple(child.execution_id for child in self.children)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Runner batch result child executions must be unique")
        return self


RunnerExecutionResult = Annotated[
    RunnerSingleExecutionResult | RunnerBatchExecutionResult,
    Field(discriminator="kind"),
]
RUNNER_EXECUTION_RESULT_ADAPTER: TypeAdapter[RunnerExecutionResult] = TypeAdapter(
    RunnerExecutionResult
)
