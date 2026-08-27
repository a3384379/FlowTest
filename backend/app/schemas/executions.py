from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.api_assets import JsonValue
from app.domain.assertions import AssertionKind, ComparisonOperator
from app.domain.execution import ExecutionStatus
from app.schemas.api_assets import VariableName


class AssertionInput(BaseModel):
    kind: AssertionKind
    operator: ComparisonOperator = ComparisonOperator.EQUALS
    target: str | None = Field(default=None, max_length=2048)
    expected: JsonValue = None


class ExecuteAPIRequest(BaseModel):
    environment_id: UUID
    service_override: str | None = Field(default=None, max_length=160)
    endpoint_variant: str | None = Field(default=None, max_length=80)
    runtime_variables: dict[VariableName, str] = Field(default_factory=dict)
    runtime_headers: dict[str, str] = Field(default_factory=dict)
    body_override: JsonValue = None
    use_body_override: bool = False
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    assertions: list[AssertionInput] = Field(default_factory=list, max_length=100)


class AssertionResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    execution_id: UUID
    kind: AssertionKind
    operator: ComparisonOperator
    target: str | None
    expected: JsonValue
    actual: JsonValue
    passed: bool
    message: str
    created_at: datetime
    updated_at: datetime


class ExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    api_definition_id: UUID
    api_version_id: UUID
    environment_id: UUID
    triggered_by_id: UUID
    status: ExecutionStatus
    request_method: str
    request_url: str
    request_headers: dict[str, str]
    request_body: JsonValue
    target_snapshot: dict[str, JsonValue]
    response_status: int | None
    response_headers: dict[str, str]
    response_body: JsonValue
    response_artifact_id: UUID | None
    response_size_bytes: int | None
    elapsed_ms: float | None
    error_code: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ExecutionDetailResponse(BaseModel):
    execution: ExecutionResponse
    assertions: list[AssertionResultResponse]
