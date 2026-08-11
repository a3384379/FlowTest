from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.domain.capabilities import RunnerType
from app.engine.results import NodeResult


class RunnerTaskStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunnerIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    runner_id: UUID
    pool_id: UUID
    runner_type: RunnerType
    labels: tuple[str, ...] = ()
    network_zone: str = Field(default="default", min_length=1, max_length=100)


class RunnerTaskEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: UUID
    execution_id: UUID
    node_id: str = Field(min_length=1, max_length=128)
    attempt: int = Field(ge=1, le=100)
    fencing_token: int = Field(ge=1)
    capability_id: str = Field(min_length=3, max_length=120)
    capability_version: str = Field(min_length=5, max_length=64)
    schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot: dict[str, JsonValue]
    priority: int = Field(default=5, ge=0, le=9)
    available_at: datetime

    @field_validator("available_at")
    @classmethod
    def require_available_at_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Runner task availability must include a UTC offset")
        return value


class RunnerLease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lease_id: UUID
    task: RunnerTaskEnvelope
    runner_id: UUID
    acquired_at: datetime
    expires_at: datetime

    @field_validator("acquired_at", "expires_at")
    @classmethod
    def require_lease_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Runner lease timestamp must include a UTC offset")
        return value

    @model_validator(mode="after")
    def validate_lease_window(self) -> "RunnerLease":
        if self.expires_at <= self.acquired_at:
            raise ValueError("Runner lease expiration must be after acquisition")
        return self


class RunnerProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lease_id: UUID
    fencing_token: int = Field(ge=1)
    progress_percent: float = Field(ge=0, le=100)
    message: str = Field(default="", max_length=500)


class RunnerControlPlane(Protocol):
    async def claim(self, identity: RunnerIdentity) -> RunnerLease | None: ...

    async def renew(self, identity: RunnerIdentity, lease: RunnerLease) -> RunnerLease: ...

    async def report_progress(self, identity: RunnerIdentity, progress: RunnerProgress) -> None: ...

    async def complete(
        self,
        identity: RunnerIdentity,
        lease: RunnerLease,
        result: NodeResult,
    ) -> None: ...
