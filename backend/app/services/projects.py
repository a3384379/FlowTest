from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.domain.access import (
    FolderMoveError,
    ProjectCapability,
    ProjectRole,
    validate_folder_parent,
)
from app.domain.network import OutboundNetworkPolicy, OutboundPolicyError, validate_policy_values
from app.models.access import AuditLog, Folder, Project, ProjectMember, User
from app.repositories.access import ProjectRepository, UserRepository
from app.services.audit import AuditService


@dataclass(frozen=True, slots=True)
class ProjectAccess:
    project: Project
    role: ProjectRole | None

    @property
    def capabilities(self) -> frozenset[ProjectCapability]:
        return frozenset(ProjectCapability) if self.role is None else self.role.capabilities


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectRepository(session)
        self._users = UserRepository(session)
        self._audit = AuditService(session)

    async def list_projects(
        self, *, actor: User, page: int, page_size: int
    ) -> tuple[list[ProjectAccess], int]:
        rows, total = await self._projects.list_for_user(
            user_id=actor.id,
            system_admin=actor.is_system_admin,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return [ProjectAccess(project=project, role=role) for project, role in rows], total

    async def create(self, *, actor: User, name: str, description: str) -> ProjectAccess:
        project = Project(
            name=name.strip(),
            description=description.strip(),
            retention_days=settings.retention_default_days,
            created_by_id=actor.id,
        )
        self._projects.add(project)
        await self._session.flush()
        self._projects.add(
            ProjectMember(project_id=project.id, user_id=actor.id, role=ProjectRole.OWNER)
        )
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project.id,
            action="project.created",
            resource_type="project",
            resource_id=project.id,
        )
        await self._session.commit()
        await self._session.refresh(project)
        return ProjectAccess(project=project, role=ProjectRole.OWNER)

    async def get(self, *, actor: User, project_id: UUID) -> ProjectAccess:
        return await self.authorize(actor=actor, project_id=project_id, editing=False)

    async def update(
        self,
        *,
        actor: User,
        project_id: UUID,
        name: str | None,
        description: str | None,
    ) -> ProjectAccess:
        access = await self.authorize(actor=actor, project_id=project_id, editing=True)
        if name is not None:
            access.project.name = name.strip()
        if description is not None:
            access.project.description = description.strip()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="project.updated",
            resource_type="project",
            resource_id=project_id,
        )
        await self._session.commit()
        await self._session.refresh(access.project)
        return access

    async def list_members(self, *, actor: User, project_id: UUID) -> list[ProjectMember]:
        await self.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._projects.list_members(project_id)

    async def get_security_policy(self, *, actor: User, project_id: UUID) -> OutboundNetworkPolicy:
        access = await self.authorize(
            actor=actor,
            project_id=project_id,
            capability=ProjectCapability.READ,
        )
        return _project_network_policy(access.project)

    async def load_runtime_security_policy(self, project_id: UUID) -> OutboundNetworkPolicy:
        project = await self._projects.get(project_id)
        if project is None:
            raise AppError(code="PROJECT_NOT_FOUND", message="项目不存在", status_code=404)
        return _project_network_policy(project)

    async def update_security_policy(
        self,
        *,
        actor: User,
        project_id: UUID,
        allowed_hosts: list[str],
        allowed_private_cidrs: list[str],
    ) -> OutboundNetworkPolicy:
        access = await self.authorize(
            actor=actor,
            project_id=project_id,
            capability=ProjectCapability.MANAGE_SECURITY,
        )
        try:
            validate_policy_values(allowed_hosts, allowed_private_cidrs)
            policy = OutboundNetworkPolicy(
                tuple(allowed_hosts), tuple(allowed_private_cidrs)
            ).normalized()
        except (OutboundPolicyError, ValueError) as error:
            raise AppError(
                code="INVALID_OUTBOUND_POLICY",
                message=str(error),
                status_code=422,
            ) from error
        access.project.outbound_allowed_hosts = list(policy.allowed_hosts)
        access.project.outbound_allowed_private_cidrs = list(policy.allowed_private_cidrs)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="project.security_policy_updated",
            resource_type="project",
            resource_id=project_id,
            details={
                "allowed_hosts": list(policy.allowed_hosts),
                "allowed_private_cidrs": list(policy.allowed_private_cidrs),
            },
        )
        await self._session.commit()
        return policy

    async def get_retention_policy(self, *, actor: User, project_id: UUID) -> int:
        access = await self.authorize(
            actor=actor,
            project_id=project_id,
            capability=ProjectCapability.READ,
        )
        return access.project.retention_days

    async def update_retention_policy(
        self,
        *,
        actor: User,
        project_id: UUID,
        retention_days: int,
    ) -> int:
        access = await self.authorize(
            actor=actor,
            project_id=project_id,
            capability=ProjectCapability.MANAGE_SECURITY,
        )
        if not 1 <= retention_days <= settings.retention_max_days:
            raise AppError(
                code="INVALID_RETENTION_POLICY",
                message=f"保留天数必须在 1 到 {settings.retention_max_days} 之间",
                status_code=422,
            )
        access.project.retention_days = retention_days
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="project.retention_policy_updated",
            resource_type="project",
            resource_id=project_id,
            details={"retention_days": retention_days},
        )
        await self._session.commit()
        return retention_days

    async def get_capacity_policy(self, *, actor: User, project_id: UUID) -> tuple[int, int]:
        access = await self.authorize(
            actor=actor,
            project_id=project_id,
            capability=ProjectCapability.READ,
        )
        return (
            access.project.execution_concurrency_limit,
            access.project.queued_run_limit,
        )

    async def update_capacity_policy(
        self,
        *,
        actor: User,
        project_id: UUID,
        execution_concurrency_limit: int,
        queued_run_limit: int,
    ) -> tuple[int, int]:
        access = await self.authorize(
            actor=actor,
            project_id=project_id,
            capability=ProjectCapability.MANAGE_SECURITY,
        )
        access.project.execution_concurrency_limit = execution_concurrency_limit
        access.project.queued_run_limit = queued_run_limit
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="project.capacity_policy_updated",
            resource_type="project",
            resource_id=project_id,
            details={
                "execution_concurrency_limit": execution_concurrency_limit,
                "queued_run_limit": queued_run_limit,
            },
        )
        await self._session.commit()
        return execution_concurrency_limit, queued_run_limit

    async def list_audit_logs(
        self,
        *,
        actor: User,
        project_id: UUID,
        action: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AuditLog], int]:
        await self.authorize(
            actor=actor,
            project_id=project_id,
            capability=ProjectCapability.VIEW_AUDIT,
        )
        return await self._projects.list_audit_logs(
            project_id=project_id,
            action=action,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def upsert_member(
        self, *, actor: User, project_id: UUID, user_id: UUID, role: ProjectRole
    ) -> ProjectMember:
        await self._authorize_owner(actor=actor, project_id=project_id)
        target = await self._users.get(user_id)
        if target is None or not target.is_active:
            raise AppError(code="USER_NOT_FOUND", message="用户不存在", status_code=404)
        member = await self._projects.get_member(project_id=project_id, user_id=user_id)
        if member is None:
            member = ProjectMember(project_id=project_id, user_id=user_id, role=role)
            self._projects.add(member)
        elif member.role == ProjectRole.OWNER and role != ProjectRole.OWNER:
            await self._ensure_another_owner(project_id)
            member.role = role
        else:
            member.role = role
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="project.member_upserted",
            resource_type="project_member",
            resource_id=member.id,
            details={"user_id": str(user_id), "role": role.value},
        )
        await self._session.commit()
        await self._session.refresh(member)
        return member

    async def remove_member(self, *, actor: User, project_id: UUID, user_id: UUID) -> None:
        await self._authorize_owner(actor=actor, project_id=project_id)
        member = await self._projects.get_member(project_id=project_id, user_id=user_id)
        if member is None:
            raise AppError(code="MEMBER_NOT_FOUND", message="项目成员不存在", status_code=404)
        if member.role == ProjectRole.OWNER:
            await self._ensure_another_owner(project_id)
        resource_id = member.id
        await self._projects.delete(member)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="project.member_removed",
            resource_type="project_member",
            resource_id=resource_id,
            details={"user_id": str(user_id)},
        )
        await self._session.commit()

    async def list_folders(self, *, actor: User, project_id: UUID) -> list[Folder]:
        await self.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._projects.list_folders(project_id)

    async def create_folder(
        self, *, actor: User, project_id: UUID, name: str, parent_id: UUID | None
    ) -> Folder:
        await self.authorize(actor=actor, project_id=project_id, editing=True)
        await self._validate_parent(project_id=project_id, parent_id=parent_id)
        normalized_name = name.strip()
        await self._ensure_unique_folder_name(
            project_id=project_id, parent_id=parent_id, name=normalized_name
        )
        folder = Folder(
            project_id=project_id,
            parent_id=parent_id,
            name=normalized_name,
            created_by_id=actor.id,
        )
        self._projects.add(folder)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="folder.created",
            resource_type="folder",
            resource_id=folder.id,
        )
        await self._session.commit()
        await self._session.refresh(folder)
        return folder

    async def update_folder(
        self,
        *,
        actor: User,
        project_id: UUID,
        folder_id: UUID,
        name: str | None,
        parent_id: UUID | None,
        change_parent: bool,
    ) -> Folder:
        await self.authorize(actor=actor, project_id=project_id, editing=True)
        folder = await self._get_project_folder(project_id=project_id, folder_id=folder_id)
        next_parent_id = folder.parent_id
        if change_parent:
            await self._validate_parent(project_id=project_id, parent_id=parent_id)
            descendants = await self._projects.descendant_ids(folder_id)
            try:
                validate_folder_parent(
                    folder_id=folder_id,
                    new_parent_id=parent_id,
                    ancestor_ids=descendants,
                )
            except FolderMoveError as error:
                raise AppError(
                    code="INVALID_FOLDER_MOVE", message=str(error), status_code=409
                ) from error
            next_parent_id = parent_id
        next_name = name.strip() if name is not None else folder.name
        await self._ensure_unique_folder_name(
            project_id=project_id,
            parent_id=next_parent_id,
            name=next_name,
            excluding_id=folder_id,
        )
        folder.parent_id = next_parent_id
        folder.name = next_name
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="folder.updated",
            resource_type="folder",
            resource_id=folder.id,
        )
        await self._session.commit()
        await self._session.refresh(folder)
        return folder

    async def delete_folder(self, *, actor: User, project_id: UUID, folder_id: UUID) -> None:
        await self.authorize(actor=actor, project_id=project_id, editing=True)
        folder = await self._get_project_folder(project_id=project_id, folder_id=folder_id)
        await self._projects.delete(folder)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="folder.deleted",
            resource_type="folder",
            resource_id=folder_id,
        )
        await self._session.commit()

    async def authorize(
        self,
        *,
        actor: User,
        project_id: UUID,
        editing: bool = False,
        capability: ProjectCapability | None = None,
    ) -> ProjectAccess:
        project = await self._projects.get(project_id)
        if project is None:
            raise AppError(code="PROJECT_NOT_FOUND", message="项目不存在", status_code=404)
        if actor.is_system_admin:
            return ProjectAccess(project=project, role=None)
        role = await self._projects.get_role(project_id=project_id, user_id=actor.id)
        if role is None:
            raise AppError(code="PROJECT_NOT_FOUND", message="项目不存在", status_code=404)
        required = capability or (ProjectCapability.EDIT if editing else ProjectCapability.READ)
        if not role.allows(required):
            raise AppError(code="PROJECT_FORBIDDEN", message="没有所需的项目权限", status_code=403)
        return ProjectAccess(project=project, role=role)

    async def _authorize_owner(self, *, actor: User, project_id: UUID) -> None:
        await self.authorize(
            actor=actor,
            project_id=project_id,
            capability=ProjectCapability.MANAGE_MEMBERS,
        )

    async def authorize_owner(self, *, actor: User, project_id: UUID) -> None:
        await self._authorize_owner(actor=actor, project_id=project_id)

    async def _validate_parent(self, *, project_id: UUID, parent_id: UUID | None) -> None:
        if parent_id is None:
            return
        parent = await self._projects.get_folder(parent_id)
        if parent is None or parent.project_id != project_id:
            raise AppError(code="PARENT_FOLDER_NOT_FOUND", message="父目录不存在", status_code=404)

    async def _get_project_folder(self, *, project_id: UUID, folder_id: UUID) -> Folder:
        folder = await self._projects.get_folder(folder_id)
        if folder is None or folder.project_id != project_id:
            raise AppError(code="FOLDER_NOT_FOUND", message="目录不存在", status_code=404)
        return folder

    async def _ensure_unique_folder_name(
        self,
        *,
        project_id: UUID,
        parent_id: UUID | None,
        name: str,
        excluding_id: UUID | None = None,
    ) -> None:
        if await self._projects.folder_name_exists(
            project_id=project_id,
            parent_id=parent_id,
            name=name,
            excluding_id=excluding_id,
        ):
            raise AppError(code="FOLDER_NAME_EXISTS", message="同级目录名称已存在", status_code=409)

    async def _ensure_another_owner(self, project_id: UUID) -> None:
        if await self._projects.count_owners(project_id) <= 1:
            raise AppError(
                code="LAST_PROJECT_OWNER",
                message="项目至少需要保留一名 Owner",
                status_code=409,
            )


def _project_network_policy(project: Project) -> OutboundNetworkPolicy:
    return OutboundNetworkPolicy(
        allowed_hosts=tuple(project.outbound_allowed_hosts),
        allowed_private_cidrs=tuple(project.outbound_allowed_private_cidrs),
    )
