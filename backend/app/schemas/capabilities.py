from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.capabilities import CapabilityManifest, PluginManifest


class V3FeatureFlagsResponse(BaseModel):
    capability_sdk: bool
    plugin_registry: bool
    runner_fabric: bool
    multi_protocol: bool
    event_protocols: bool
    performance_lab: bool
    environment_lab: bool


class CapabilityResponse(BaseModel):
    id: str
    version: str
    category: str
    display_name: str
    description: str
    runner_type: str
    network_access: str
    schema_hash: str
    source: str
    enabled: bool
    plugin_id: str | None
    plugin_digest: str | None
    manifest: CapabilityManifest


class PluginResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plugin_key: str
    version: str
    display_name: str
    oci_repository: str
    oci_digest: str
    signature_identity: str
    status: str
    created_at: datetime
    updated_at: datetime


class RunnerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pool_id: UUID
    name: str
    status: str
    labels: list[str]
    capabilities: list[str]
    current_load: int
    last_seen_at: datetime | None


class RunnerPoolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    runner_type: str
    network_zone: str
    labels: list[str]
    max_concurrency: int
    enabled: bool
    runners: list[RunnerResponse]


class PluginManifestValidationRequest(BaseModel):
    manifest: dict[str, object]


class PluginManifestValidationResponse(BaseModel):
    valid: bool = True
    manifest: PluginManifest
