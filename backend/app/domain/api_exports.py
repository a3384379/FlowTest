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
        self._validate_common()
        match self.scope:
            case "project":
                self._validate_project()
            case "folder":
                self._validate_folder()
            case "selected":
                self._validate_selected()
            case _:
                raise InvalidAPIExportSelection("导出范围不存在")

    def _validate_common(self) -> None:
        if self.folder_id is not None and self.unfiled:
            raise InvalidAPIExportSelection("分组与未分组范围不能同时选择")
        if len(self.definition_ids) > 1000:
            raise InvalidAPIExportSelection("所选接口超过导出上限 1000")
        if len(set(self.definition_ids)) != len(self.definition_ids):
            raise InvalidAPIExportSelection("所选接口不能重复")

    def _validate_project(self) -> None:
        if self.folder_id is not None or self.unfiled or self.definition_ids:
            raise InvalidAPIExportSelection("全项目导出不能附带分组或接口选择")

    def _validate_folder(self) -> None:
        if (self.folder_id is None and not self.unfiled) or self.definition_ids:
            raise InvalidAPIExportSelection("分组导出必须指定一个分组且不能附带接口选择")

    def _validate_selected(self) -> None:
        if self.folder_id is not None or self.unfiled or not self.definition_ids:
            raise InvalidAPIExportSelection("所选导出必须指定非空接口集合且不能附带分组")
