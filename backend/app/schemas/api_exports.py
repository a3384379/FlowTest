from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class APIExportSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["project", "folder", "selected"] = "project"
    folder_id: UUID | None = None
    unfiled: bool = False
    definition_ids: list[UUID] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        has_folder = self.folder_id is not None or self.unfiled
        if self.folder_id is not None and self.unfiled:
            raise ValueError("分组与未分组范围不能同时选择")
        if self.scope == "project" and (has_folder or self.definition_ids):
            raise ValueError("全项目导出不能附带分组或接口选择")
        if self.scope == "folder" and (not has_folder or self.definition_ids):
            raise ValueError("分组导出必须指定一个分组且不能附带接口选择")
        if self.scope == "selected" and (has_folder or not self.definition_ids):
            raise ValueError("所选导出必须指定非空接口集合且不能附带分组")
        if len(set(self.definition_ids)) != len(self.definition_ids):
            raise ValueError("所选接口不能重复")
        return self


class APIExportRequest(APIExportSelection):
    format: Literal["har", "curl", "bruno", "excel"]
