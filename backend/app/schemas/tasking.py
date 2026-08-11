from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.api_assets import JsonValue
from app.domain.tasking import ServiceTokenScope, TestPlanTrigger
from app.domain.test_assets import TestTargetType

VariableName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", max_length=160)]


class TestPlanItemInput(BaseModel):
    target_type: TestTargetType = TestTargetType.WORKFLOW
    target_id: UUID | None = None
    target_version: int | None = Field(default=None, ge=1)
    workflow_id: UUID | None = None
    environment_id: UUID | None = None
    workflow_version: int | None = Field(default=None, ge=1)
    max_retries: int = Field(default=0, ge=0, le=3)
    runtime_variables: dict[VariableName, str] = Field(default_factory=dict)
    runtime_headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_target(self) -> "TestPlanItemInput":
        if self.target_type is TestTargetType.WORKFLOW:
            if self.target_id is None and self.workflow_id is None:
                raise ValueError("workflow target requires target_id or workflow_id")
            if self.environment_id is None:
                raise ValueError("workflow target requires environment_id")
        elif self.target_id is None:
            raise ValueError("case/suite target requires target_id")
        return self


class TestPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    enabled: bool = True
    schedule_interval_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    schedule_cron: str | None = Field(default=None, min_length=1, max_length=120)
    schedule_timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    queue_priority: int = Field(default=5, ge=0, le=9)
    items: list[TestPlanItemInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_schedule_kind(self) -> "TestPlanCreate":
        if self.schedule_interval_seconds is not None and self.schedule_cron is not None:
            raise ValueError("interval and cron schedule cannot be combined")
        return self


class TestPlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    enabled: bool | None = None
    schedule_interval_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    schedule_cron: str | None = Field(default=None, min_length=1, max_length=120)
    schedule_timezone: str | None = Field(default=None, min_length=1, max_length=64)
    queue_priority: int | None = Field(default=None, ge=0, le=9)


class TestPlanItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    target_type: TestTargetType
    target_id: UUID
    target_version: int
    workflow_id: UUID | None
    environment_id: UUID | None
    workflow_version: int | None
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
    schedule_cron: str | None
    schedule_timezone: str
    queue_priority: int
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
    queue_priority: int
    queue_name: str
    baseline_run_id: UUID | None
    quality_summary: dict[str, object]
    cancel_requested_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime


class TestPlanRunItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    target_type: TestTargetType
    target_id: UUID
    target_version: int
    target_snapshot: dict[str, JsonValue]
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
