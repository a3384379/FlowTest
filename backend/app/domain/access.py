from enum import StrEnum
from uuid import UUID


class ProjectCapability(StrEnum):
    READ = "read"
    EDIT = "edit"
    EXECUTE = "execute"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_SECURITY = "manage_security"
    VIEW_AUDIT = "view_audit"


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

    @property
    def capabilities(self) -> frozenset[ProjectCapability]:
        if self is ProjectRole.OWNER:
            return frozenset(ProjectCapability)
        if self is ProjectRole.EDITOR:
            return frozenset(
                {
                    ProjectCapability.READ,
                    ProjectCapability.EDIT,
                    ProjectCapability.EXECUTE,
                }
            )
        return frozenset({ProjectCapability.READ})

    def allows(self, capability: ProjectCapability) -> bool:
        return capability in self.capabilities


class TeamGrantRole(StrEnum):
    EDITOR = "editor"
    VIEWER = "viewer"

    @property
    def project_role(self) -> ProjectRole:
        return ProjectRole(self.value)


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
