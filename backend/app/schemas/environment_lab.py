from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.environment_lab import EnvironmentEndpoint, EnvironmentTemplateManifest


class EnvironmentTemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_key: str = Field(
        min_length=3,
        max_length=120,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$",
    )
    display_name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    manifest: EnvironmentTemplateManifest


class EnvironmentTemplateVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: EnvironmentTemplateManifest


class EnvironmentTemplateVersionResponse(BaseModel):
    id: UUID
    template_id: UUID
    template_key: str
    display_name: str
    description: str
    status: str
    version: int
    manifest: EnvironmentTemplateManifest
    manifest_sha256: str
    signature: str
    signature_algorithm: str
    signed_by_id: UUID
    created_at: datetime


class EnvironmentProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_version_id: UUID
    ttl_seconds: int | None = Field(default=None, ge=60, le=86400)


class EnvironmentInstanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    template_version_id: UUID
    template_key: str
    template_version: int
    status: str
    cleanup_status: str
    runtime_name: str
    ttl_seconds: int
    fencing_token: int
    endpoints: list[EnvironmentEndpoint]
    seed_evidence: list[dict[str, object]]
    error_code: str | None
    error_message: str | None
    cleanup_error_code: str | None
    cleanup_attempts: int
    queued_at: datetime
    started_at: datetime | None
    ready_at: datetime | None
    expires_at: datetime
    cancellation_requested_at: datetime | None
    cleanup_started_at: datetime | None
    cleaned_at: datetime | None
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime
