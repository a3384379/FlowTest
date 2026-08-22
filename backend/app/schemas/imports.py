from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.importers.contracts import ImportChange, ImportSourceKind, ImportSourceType


class ImportItemResponse(BaseModel):
    import_key: str
    name: str
    method: str
    path: str
    change: ImportChange
    definition_id: UUID | None
    version: int


class ImportRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    source_kind: ImportSourceKind
    source_key: str
    source_type: ImportSourceType
    source_name: str
    source_url: str | None
    document_url: str | None
    source_sha256: str
    added: int
    changed: int
    deleted: int
    unchanged: int
    results: list[ImportItemResponse]
    status: str
    applied_keys: list[str]
    applied_at: datetime | None
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class ImportMergeRequest(BaseModel):
    selected_keys: set[str] = Field(default_factory=set, max_length=2000)


class ImportUrlPreviewRequest(BaseModel):
    url: HttpUrl
    source_type: ImportSourceType = ImportSourceType.AUTO
    document_id: str | None = Field(default=None, min_length=64, max_length=64)


class ImportUrlDiscoveryRequest(BaseModel):
    url: HttpUrl


class ImportUrlDocumentResponse(BaseModel):
    id: str
    name: str
    url: str


class ImportUrlDiscoveryResponse(BaseModel):
    source_url: str
    source_kind: Literal["document", "swagger_ui"]
    documents: list[ImportUrlDocumentResponse]
