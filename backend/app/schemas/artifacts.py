from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    purpose: str
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime
