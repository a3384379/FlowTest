from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.tasking import ServiceTokenScope, TestPlanTrigger

VariableName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", max_length=160)]


class TestPlanItemInput(BaseModel):
    workflow_id: UUID
    environment_id: UUID
    workflow_version: int | None = Field(default=None, ge=1)
    max_retries: int = Field(default=0, ge=0, le=3)
    runtime_variables: dict[VariableName, str] = Field(default_factory=dict)
    runtime_headers: dict[str, str] = Field(default_factory=dict)


class TestPlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    enabled: bool = True
    schedule_interval_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    items: list[TestPlanItemInput] = Field(min_length=1, max_length=100)


class TestPlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    enabled: bool | None = None
    schedule_interval_seconds: int | None = Field(default=None, ge=60, le=2_592_000)


class TestPlanItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workflow_id: UUID
    environment_id: UUID
    workflow_version: int
    position: int
    max_retries: int
    runtime_variables: dict[str, str]
    runtime_headers: dict[str, str]


class TestPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    name: str
    description: str
    enabled: bool
    schedule_interval_seconds: int | None
    next_run_at: datetime | None
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime
    items: list[TestPlanItemResponse] = Field(default_factory=list)


class TestPlanCreatedResponse(TestPlanResponse):
    webhook_secret: str


class TestPlanRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    test_plan_id: UUID
    requested_by_id: UUID
    status: str
    trigger_type: TestPlanTrigger
    cancel_requested_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime


class TestPlanRunItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workflow_id: UUID
    environment_id: UUID
    workflow_version: int
    position: int
    max_retries: int
    attempts: int
    status: str
    workflow_execution_id: UUID | None
    error_message: str | None


class TestPlanRunDetailResponse(BaseModel):
    run: TestPlanRunResponse
    items: list[TestPlanRunItemResponse]


class ServiceTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    scopes: set[ServiceTokenScope] = Field(min_length=1)
    expires_at: datetime | None = None


class ServiceTokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    name: str
    token_prefix: str
    scopes: list[ServiceTokenScope]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ServiceTokenCreatedResponse(ServiceTokenResponse):
    token: str
