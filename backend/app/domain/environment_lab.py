import hashlib
import json
import re
from enum import StrEnum
from typing import Annotated, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

OCIImageReference = Annotated[
    str,
    Field(
        min_length=80,
        max_length=500,
        pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?/"
        r"[a-z0-9]+(?:[._/-][a-z0-9]+)*"
        r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?@sha256:[0-9a-f]{64}$",
    ),
]
ServiceName = Annotated[
    str,
    Field(min_length=1, max_length=63, pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"),
]

_SENSITIVE_ENVIRONMENT_NAME = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|private[_-]?key)",
    re.IGNORECASE,
)


class HealthCheckKind(StrEnum):
    HTTP = "http"
    TCP = "tcp"


class SeedProfile(StrEnum):
    HTTP_GET_V1 = "http_get_v1"


class EnvironmentVariable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    value: str = Field(max_length=1000)

    @field_validator("name")
    @classmethod
    def reject_sensitive_name(cls, value: str) -> str:
        if _SENSITIVE_ENVIRONMENT_NAME.search(value):
            raise ValueError("Environment templates cannot embed sensitive variables")
        return value


class ServiceHealthCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: HealthCheckKind
    path: str | None = Field(default=None, min_length=1, max_length=256, pattern=r"^/[^\s]*$")
    expected_status: int = Field(default=200, ge=100, le=599)
    interval_seconds: float = Field(default=1.0, ge=0.1, le=10)
    timeout_seconds: float = Field(default=2.0, ge=0.1, le=10)
    maximum_attempts: int = Field(default=30, ge=1, le=120)

    @model_validator(mode="after")
    def validate_kind(self) -> "ServiceHealthCheck":
        if self.kind is HealthCheckKind.HTTP and self.path is None:
            raise ValueError("HTTP health checks require a path")
        if self.kind is HealthCheckKind.TCP and self.path is not None:
            raise ValueError("TCP health checks cannot declare a path")
        return self


class EnvironmentServiceDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: ServiceName
    image: OCIImageReference
    internal_port: int = Field(ge=1024, le=65535)
    environment: tuple[EnvironmentVariable, ...] = Field(default=(), max_length=32)
    depends_on: tuple[ServiceName, ...] = Field(default=(), max_length=4)
    health_check: ServiceHealthCheck
    cpu_millicores: int = Field(default=250, ge=100, le=2000)
    memory_megabytes: int = Field(default=128, ge=64, le=2048)
    pids_limit: int = Field(default=64, ge=16, le=256)
    user_id: int = Field(default=65532, ge=1, le=65535)
    group_id: int = Field(default=65532, ge=1, le=65535)
    read_only_root_filesystem: bool = True
    drop_all_capabilities: bool = True
    no_new_privileges: bool = True

    @model_validator(mode="after")
    def validate_security_boundary(self) -> "EnvironmentServiceDefinition":
        variable_names = [variable.name for variable in self.environment]
        if len(variable_names) != len(set(variable_names)):
            raise ValueError("Environment variable names must be unique")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("Service dependencies must be unique")
        if self.name in self.depends_on:
            raise ValueError("A service cannot depend on itself")
        if not (
            self.read_only_root_filesystem and self.drop_all_capabilities and self.no_new_privileges
        ):
            raise ValueError("Environment sandbox hardening flags cannot be disabled")
        return self


class EnvironmentSeedDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: SeedProfile
    service: ServiceName
    path: str = Field(default="/", min_length=1, max_length=256, pattern=r"^/[^\s]*$")


class EnvironmentTemplateManifest(BaseModel):
    """Administrator-owned declarative template; raw Compose and scripts are not accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    services: tuple[EnvironmentServiceDefinition, ...] = Field(min_length=1, max_length=5)
    seeds: tuple[EnvironmentSeedDefinition, ...] = Field(default=(), max_length=10)
    default_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    maximum_ttl_seconds: int = Field(default=14400, ge=60, le=86400)

    @model_validator(mode="after")
    def validate_topology(self) -> "EnvironmentTemplateManifest":
        names = [service.name for service in self.services]
        if len(names) != len(set(names)):
            raise ValueError("Environment service names must be unique")
        known = set(names)
        if any(
            dependency not in known
            for service in self.services
            for dependency in service.depends_on
        ):
            raise ValueError("Environment service dependency does not exist")
        if _has_dependency_cycle(self.services):
            raise ValueError("Environment service dependencies cannot contain a cycle")
        if any(seed.service not in known for seed in self.seeds):
            raise ValueError("Environment seed service does not exist")
        if self.default_ttl_seconds > self.maximum_ttl_seconds:
            raise ValueError("Default TTL cannot exceed maximum TTL")
        return self

    @property
    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json.encode()).hexdigest()

    @property
    def images(self) -> frozenset[str]:
        return frozenset(service.image for service in self.services)


class EnvironmentEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    service: ServiceName
    url: str = Field(pattern=r"^http://[a-z0-9.-]+:[0-9]{1,5}$", max_length=500)
    internal_port: int = Field(ge=1024, le=65535)


class ProvisionedEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_name: str = Field(pattern=r"^flowtest-env-[0-9a-f]{32}$")
    endpoints: tuple[EnvironmentEndpoint, ...] = Field(min_length=1, max_length=5)
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


class EnvironmentSeedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: SeedProfile
    service: ServiceName
    path: str
    status_code: int = Field(ge=100, le=599)


class EnvironmentRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class EnvironmentRuntime(Protocol):
    async def provision(
        self, instance_id: UUID, manifest: EnvironmentTemplateManifest
    ) -> ProvisionedEnvironment: ...

    async def apply_seeds(
        self,
        provisioned: ProvisionedEnvironment,
        seeds: tuple[EnvironmentSeedDefinition, ...],
    ) -> tuple[EnvironmentSeedEvidence, ...]: ...

    async def cleanup(self, instance_id: UUID) -> None: ...


def _has_dependency_cycle(services: tuple[EnvironmentServiceDefinition, ...]) -> bool:
    dependencies = {service.name: service.depends_on for service in services}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> bool:
        if name in visiting:
            return True
        if name in visited:
            return False
        visiting.add(name)
        if any(visit(dependency) for dependency in dependencies[name]):
            return True
        visiting.remove(name)
        visited.add(name)
        return False

    return any(visit(name) for name in dependencies)
