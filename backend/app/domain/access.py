from enum import StrEnum
from uuid import UUID


class ProjectRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"

    @property
    def can_edit(self) -> bool:
        return self in {ProjectRole.OWNER, ProjectRole.EDITOR}

    @property
    def can_manage_members(self) -> bool:
        return self is ProjectRole.OWNER


class FolderMoveError(ValueError):
    """Raised when a folder move would violate tree invariants."""


def validate_folder_parent(
    *, folder_id: UUID, new_parent_id: UUID | None, ancestor_ids: set[UUID]
) -> None:
    if new_parent_id is None:
        return
    if new_parent_id == folder_id:
        raise FolderMoveError("目录不能移动到自身")
    if new_parent_id in ancestor_ids:
        raise FolderMoveError("目录不能移动到其子目录")
