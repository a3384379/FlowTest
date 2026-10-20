from dataclasses import dataclass
from typing import Literal
from uuid import UUID

APIExportScope = Literal["project", "folder", "selected"]


class InvalidAPIExportSelection(ValueError):
    """An export selection violates the catalog export policy."""


@dataclass(frozen=True, slots=True)
class APIExportSelection:
    scope: APIExportScope = "project"
    folder_id: UUID | None = None
    unfiled: bool = False
    definition_ids: tuple[UUID, ...] = ()

    def validate(self) -> None:
        if self.scope not in {"project", "folder", "selected"}:
            raise InvalidAPIExportSelection("导出范围不存在")
        has_folder = self.folder_id is not None or self.unfiled
        if self.folder_id is not None and self.unfiled:
            raise InvalidAPIExportSelection("分组与未分组范围不能同时选择")
        if len(self.definition_ids) > 1000:
            raise InvalidAPIExportSelection("所选接口超过导出上限 1000")
        if self.scope == "project" and (has_folder or self.definition_ids):
            raise InvalidAPIExportSelection("全项目导出不能附带分组或接口选择")
        if self.scope == "folder" and (not has_folder or self.definition_ids):
            raise InvalidAPIExportSelection("分组导出必须指定一个分组且不能附带接口选择")
        if self.scope == "selected" and (has_folder or not self.definition_ids):
            raise InvalidAPIExportSelection("所选导出必须指定非空接口集合且不能附带分组")
        if len(set(self.definition_ids)) != len(self.definition_ids):
            raise InvalidAPIExportSelection("所选接口不能重复")
