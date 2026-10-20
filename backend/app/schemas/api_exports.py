from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.api_exports import APIExportScope


class APIExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["har", "curl", "bruno", "excel"]
    scope: APIExportScope = "project"
    folder_id: UUID | None = None
    unfiled: bool = False
    definition_ids: list[UUID] = Field(default_factory=list)
