from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.importers.contracts import ImportChange, ImportSourceType


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
    source_type: ImportSourceType
    source_name: str
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
