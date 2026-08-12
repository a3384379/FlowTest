import hashlib
from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.capabilities import CapabilityId, RunnerType


class RunnerRuntime(StrEnum):
    DOCKER = "docker"
    KUBERNETES = "kubernetes"


class RunnerStatus(StrEnum):
    OFFLINE = "offline"
    ONLINE = "online"
    DRAINING = "draining"
    DISABLED = "disabled"


class RunnerTaskStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LeaseStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"
    RELEASED = "released"


class RunnerEventKind(StrEnum):
    REGISTERED = "registered"
    ONLINE = "online"
    OFFLINE = "offline"
    DRAINING = "draining"
    RESUMED = "resumed"
    DISABLED = "disabled"
    LEASE_ACQUIRED = "lease_acquired"
    LEASE_RENEWED = "lease_renewed"
    LEASE_EXPIRED = "lease_expired"
    LEASE_COMPLETED = "lease_completed"
    LEASE_FENCED = "lease_fenced"
    TASK_CANCELLED = "task_cancelled"
    TASK_FAILED = "task_failed"


class RunnerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    runner_type: RunnerType
    runtime: RunnerRuntime
    network_zone: str = Field(min_length=1, max_length=100)
    labels: tuple[str, ...] = Field(default=(), max_length=50)
    capabilities: tuple[CapabilityId, ...] = Field(min_length=1, max_length=100)
    max_concurrency: int = Field(ge=1, le=500)
    lease_seconds: int = Field(ge=10, le=300)
    heartbeat_timeout_seconds: int = Field(ge=15, le=600)

    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return normalize_labels(values)

    @field_validator("capabilities")
    @classmethod
    def normalize_capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({value.strip() for value in values}))
        if len(normalized) != len(values):
            raise ValueError("Runner capabilities must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_heartbeat_window(self) -> "RunnerProfile":
        if self.heartbeat_timeout_seconds <= self.lease_seconds:
            raise ValueError("Runner heartbeat timeout must exceed lease duration")
        return self


def normalize_labels(values: Iterable[str]) -> tuple[str, ...]:
    raw_labels = tuple(value.strip().lower() for value in values)
    labels = tuple(sorted(set(raw_labels)))
    if len(labels) != len(raw_labels):
        raise ValueError("Runner labels must be unique")
    if any(
        not label
        or len(label) > 64
        or not label[0].isalnum()
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for character in label)
        for label in labels
    ):
        raise ValueError(
            "Runner labels must use lowercase letters, numbers, dot, dash or underscore"
        )
    return labels


def select_runner_type(types: Iterable[RunnerType]) -> RunnerType:
    specialized = {item for item in types if item is not RunnerType.GENERAL}
    if len(specialized) == 1:
        return specialized.pop()
    return RunnerType.GENERAL


def identity_fingerprint(instance_id: str) -> str:
    return hashlib.sha256(instance_id.encode()).hexdigest()
