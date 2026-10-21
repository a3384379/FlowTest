from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

AISourceKind = Literal["api", "schema", "execution"]


class AISourceSummary(BaseModel):
    id: UUID
    kind: AISourceKind
    name: str
    version: int | None = None
    protocol: str | None = None
    status: str | None = None
    created_at: datetime


class AIPublicSourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: AISourceKind
    source_id: UUID
    name: str
    version: int | None = None
    protocol: str | None = None
    method: str | None = None
    path: str | None = None
    status: str | None = None
    workflow_id: UUID | None = None
    workflow_version_id: UUID | None = None
    error_code: str | None = None
    error_message: str | None = None
    content_fingerprint: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class AIPublicSource(BaseModel):
    project_id: UUID
    metadata: AIPublicSourceMetadata
    schema_document: dict[str, JsonValue] | None = None
    notices: list[str]
