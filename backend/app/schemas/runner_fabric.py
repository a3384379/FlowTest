from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.runner.results import RunnerExecutionResult


class RunnerPoolCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    runner_type: Literal["general", "data", "protocol", "performance", "environment"]
    runtime: Literal["docker", "kubernetes"] = "docker"
    network_zone: str = Field(default="default", min_length=1, max_length=100)
    labels: list[str] = Field(default_factory=list, max_length=50)
    capabilities: list[str] = Field(default_factory=lambda: ["flow.workflow"], max_length=100)
    max_concurrency: int = Field(default=20, ge=1, le=500)
    lease_timeout_seconds: int = Field(default=30, ge=10, le=300)
    heartbeat_timeout_seconds: int = Field(default=90, ge=15, le=600)

    @model_validator(mode="after")
    def validate_timeouts(self) -> "RunnerPoolCreate":
        if self.heartbeat_timeout_seconds <= self.lease_timeout_seconds:
            raise ValueError("心跳超时必须大于 Lease 时长")
        return self


class RunnerPoolUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_concurrency: int | None = Field(default=None, ge=1, le=500)
    lease_timeout_seconds: int | None = Field(default=None, ge=10, le=300)
    heartbeat_timeout_seconds: int | None = Field(default=None, ge=15, le=600)
    enabled: bool | None = None


class RunnerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pool_id: UUID
    name: str
    status: str
    runtime: str
    agent_version: str
    architecture: str
    labels: list[str]
    capabilities: list[str]
    max_concurrency: int
    current_load: int
    last_seen_at: datetime | None
    draining_requested_at: datetime | None
    disabled_at: datetime | None


class RunnerPoolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    runner_type: str
    runtime: str
    network_zone: str
    labels: list[str]
    capabilities: list[str]
    max_concurrency: int
    lease_timeout_seconds: int
    heartbeat_timeout_seconds: int
    enabled: bool
    created_at: datetime
    runners: list[RunnerResponse] = Field(default_factory=list)


class RunnerRegistrationTokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expires_in_seconds: int = Field(default=900, ge=60, le=86400)


class RunnerRegistrationTokenResponse(BaseModel):
    id: UUID
    pool_id: UUID
    token: str
    expires_at: datetime


class RunnerRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    instance_id: str = Field(min_length=16, max_length=300)
    runtime: Literal["docker", "kubernetes"]
    agent_version: str = Field(min_length=1, max_length=64)
    architecture: str = Field(min_length=1, max_length=32)
    labels: list[str] = Field(default_factory=list, max_length=50)
    capabilities: list[str] = Field(default_factory=lambda: ["flow.workflow"], max_length=100)
    max_concurrency: int = Field(default=1, ge=1, le=500)


class RunnerRegisterResponse(BaseModel):
    runner_id: UUID
    pool_id: UUID
    token: str
    lease_timeout_seconds: int
    heartbeat_timeout_seconds: int


class RunnerHeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_load: int = Field(ge=0, le=500)


class RunnerLeaseTaskResponse(BaseModel):
    task_id: UUID
    execution_id: UUID
    attempt: int
    fencing_token: int
    plan: str
    plan_sha256: str
    outbound_policy_enabled: bool = True
    allowed_hosts: list[str]
    allowed_private_cidrs: list[str]


class RunnerLeaseResponse(BaseModel):
    lease_id: UUID
    runner_id: UUID
    acquired_at: datetime
    expires_at: datetime
    task: RunnerLeaseTaskResponse


class RunnerRenewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fencing_token: int = Field(ge=1)


class RunnerProgressRequest(RunnerRenewRequest):
    progress_percent: float = Field(ge=0, le=100)
    message: str = Field(default="", max_length=300)


class RunnerCompleteRequest(RunnerRenewRequest):
    result: RunnerExecutionResult


class RunnerFailRequest(RunnerRenewRequest):
    error_code: str = Field(min_length=1, max_length=100)
    error_message: str = Field(min_length=1, max_length=1000)
    retryable: bool = True


class RunnerLeaseAckResponse(BaseModel):
    accepted: bool = True
    task_status: str
    expires_at: datetime | None = None
    cancel_requested: bool = False


class RunnerTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    execution_id: UUID
    project_id: UUID
    required_runner_type: str
    required_labels: list[str]
    required_capabilities: list[str]
    status: str
    priority: int
    attempts: int
    max_attempts: int
    fencing_token: int
    available_at: datetime
    selected_runner_id: UUID | None
    last_lease_id: UUID | None
    error_code: str | None
    error_message: str | None
    completed_at: datetime | None
    created_at: datetime


class RunnerLeaseAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    runner_id: UUID
    fencing_token: int
    status: str
    acquired_at: datetime
    expires_at: datetime
    last_renewed_at: datetime
    completed_at: datetime | None


class RunnerEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pool_id: UUID
    runner_id: UUID | None
    task_id: UUID | None
    lease_id: UUID | None
    kind: str
    message: str
    details: dict[str, JsonValue]
    created_at: datetime


class RunnerFabricOverviewResponse(BaseModel):
    pools: int
    runners_online: int
    runners_offline: int
    runners_draining: int
    queued_tasks: int
    active_leases: int
    completed_tasks: int
    failed_tasks: int


class RunnerActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["drain", "resume", "disable"]


class RunnerAgentConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    control_plane_url: str
    registration_token: str = ""
    runner_token: str = ""
    runner_token_file: str = ""
    name: str = Field(min_length=1, max_length=120)
    instance_id: str = Field(min_length=16, max_length=300)
    runtime: Literal["docker", "kubernetes"]
    agent_version: str = Field(min_length=1, max_length=64)
    architecture: str = Field(min_length=1, max_length=32)
    labels: list[str] = Field(default_factory=list, max_length=50)
    capabilities: list[str] = Field(default_factory=lambda: ["flow.workflow"], max_length=100)
    max_concurrency: int = Field(default=1, ge=1, le=500)
    poll_seconds: float = Field(default=1.0, ge=0.1, le=30)
    production: bool = False

    @field_validator("control_plane_url")
    @classmethod
    def validate_control_plane_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("Runner 控制面地址必须使用 HTTP/HTTPS")
        return normalized

    @model_validator(mode="after")
    def validate_tokens_and_transport(self) -> "RunnerAgentConfiguration":
        if not self.registration_token and not self.runner_token:
            raise ValueError("Runner 必须配置注册令牌或已签发身份令牌")
        if self.production and not self.control_plane_url.startswith("https://"):
            raise ValueError("生产环境 Runner 控制面必须使用 HTTPS")
        return self
