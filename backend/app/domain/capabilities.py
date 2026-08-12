import hashlib
import json
from enum import StrEnum
from typing import Annotated

from jsonschema import SchemaError
from jsonschema.validators import validator_for
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

CapabilityId = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$", min_length=3, max_length=120),
]
SemanticVersion = Annotated[
    str,
    Field(
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
        max_length=64,
    ),
]
SchemaDocument = dict[str, JsonValue]


class CapabilityCategory(StrEnum):
    CONTROL = "control"
    PROTOCOL = "protocol"
    DATA = "data"
    ASSERTION = "assertion"
    INTEGRATION = "integration"
    PERFORMANCE = "performance"
    ENVIRONMENT = "environment"


class RunnerType(StrEnum):
    GENERAL = "general"
    DATA = "data"
    PROTOCOL = "protocol"
    PERFORMANCE = "performance"
    ENVIRONMENT = "environment"
    PLUGIN = "plugin"


class NetworkAccess(StrEnum):
    DENIED = "denied"
    PROJECT_ALLOWLIST = "project_allowlist"
    BROKER_ONLY = "broker_only"


class NetworkPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access: NetworkAccess = NetworkAccess.DENIED
    protocols: tuple[str, ...] = ()
    dns_revalidation: bool = True

    @model_validator(mode="after")
    def validate_protocols(self) -> "NetworkPolicy":
        normalized = tuple(protocol.strip().lower() for protocol in self.protocols)
        if len(normalized) != len(set(normalized)):
            raise ValueError("Network protocols must be unique")
        if self.access is NetworkAccess.DENIED and normalized:
            raise ValueError("Denied network policy cannot declare protocols")
        if self.access is not NetworkAccess.DENIED and not normalized:
            raise ValueError("Network-enabled capability must declare protocols")
        object.__setattr__(self, "protocols", normalized)
        return self


class TimeoutPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_seconds: int = Field(default=30, ge=1, le=300)
    maximum_seconds: int = Field(default=300, ge=1, le=300)

    @model_validator(mode="after")
    def validate_limits(self) -> "TimeoutPolicy":
        if self.default_seconds > self.maximum_seconds:
            raise ValueError("Default timeout cannot exceed maximum timeout")
        return self


class SnapshotPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_configuration: bool = True
    include_schema_hash: bool = True
    pin_plugin_digest: bool = True
    credential_material: str = Field(default="encrypted", pattern=r"^(encrypted|reference|none)$")


class RedactionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensitive_paths: tuple[str, ...] = ()
    redact_credentials: bool = True
    redact_headers: bool = True
    redact_artifacts: bool = True


class CapabilityManifest(BaseModel):
    """Versioned, immutable execution contract consumed by the V3 planner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: CapabilityId
    version: SemanticVersion
    category: CapabilityCategory
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    input_schema: SchemaDocument
    output_schema: SchemaDocument
    configuration_schema: SchemaDocument
    credential_types: tuple[str, ...] = ()
    network_policy: NetworkPolicy = Field(default_factory=NetworkPolicy)
    runner_type: RunnerType = RunnerType.GENERAL
    timeout_policy: TimeoutPolicy = Field(default_factory=TimeoutPolicy)
    snapshot_policy: SnapshotPolicy = Field(default_factory=SnapshotPolicy)
    redaction_policy: RedactionPolicy = Field(default_factory=RedactionPolicy)
    plugin_id: str | None = Field(default=None, min_length=3, max_length=120)
    plugin_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_contract(self) -> "CapabilityManifest":
        if len(self.credential_types) != len(set(self.credential_types)):
            raise ValueError("Credential types must be unique")
        if (self.plugin_id is None) != (self.plugin_digest is None):
            raise ValueError("Plugin ID and digest must be declared together")
        for name, schema in (
            ("input", self.input_schema),
            ("output", self.output_schema),
            ("configuration", self.configuration_schema),
        ):
            _validate_schema(name, schema)
        return self

    @property
    def schema_hash(self) -> str:
        canonical = json.dumps(
            {
                "input": self.input_schema,
                "output": self.output_schema,
                "configuration": self.configuration_schema,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class PluginResourceLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpu_millicores: int = Field(default=500, ge=100, le=8000)
    memory_megabytes: int = Field(default=256, ge=64, le=16384)
    pids: int = Field(default=64, ge=16, le=1024)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class PluginManifest(BaseModel):
    """Administrator-controlled OCI plugin declaration; never accepts user scripts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: CapabilityId
    version: SemanticVersion
    display_name: str = Field(min_length=1, max_length=120)
    oci_repository: str = Field(min_length=1, max_length=500)
    oci_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    signature_identity: str = Field(min_length=1, max_length=500)
    capabilities: tuple[CapabilityManifest, ...] = Field(min_length=1, max_length=50)
    network_policy: NetworkPolicy = Field(default_factory=NetworkPolicy)
    credential_types: tuple[str, ...] = ()
    resource_limits: PluginResourceLimits = Field(default_factory=PluginResourceLimits)
    read_only_root_filesystem: bool = True
    drop_all_capabilities: bool = True
    no_new_privileges: bool = True

    @model_validator(mode="after")
    def validate_security_contract(self) -> "PluginManifest":
        if not self.oci_repository.startswith(("ghcr.io/", "docker.io/", "registry.")):
            raise ValueError("Plugin repository must be an explicit OCI registry reference")
        if len(self.credential_types) != len(set(self.credential_types)):
            raise ValueError("Plugin credential types must be unique")
        keys = [(capability.id, capability.version) for capability in self.capabilities]
        if len(keys) != len(set(keys)):
            raise ValueError("Plugin capabilities must be unique")
        if any(
            capability.plugin_id != self.id or capability.plugin_digest != self.oci_digest
            for capability in self.capabilities
        ):
            raise ValueError("Plugin capabilities must pin the owning plugin and OCI digest")
        if not (
            self.read_only_root_filesystem and self.drop_all_capabilities and self.no_new_privileges
        ):
            raise ValueError("Plugin sandbox hardening flags cannot be disabled")
        return self


def _validate_schema(name: str, schema: SchemaDocument) -> None:
    try:
        validator_for(schema).check_schema(schema)
    except SchemaError as error:
        raise ValueError(f"Invalid {name} JSON Schema") from error
