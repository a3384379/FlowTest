from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import ProjectRole
from app.models.access import AuditLog, Folder, Project, ProjectMember, RefreshSession, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def list(self, *, offset: int, limit: int) -> tuple[list[User], int]:
        users = list(
            (
                await self._session.scalars(
                    select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(select(func.count()).select_from(User))
        return users, int(total or 0)

    def add(self, user: User) -> None:
        self._session.add(user)


class RefreshSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hash(self, token_hash: str) -> RefreshSession | None:
        result = await self._session.execute(
            select(RefreshSession).where(RefreshSession.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    def add(self, refresh_session: RefreshSession) -> None:
        self._session.add(refresh_session)

    async def revoke_all(self, *, user_id: UUID, revoked_at: datetime) -> None:
        sessions = await self._session.scalars(
            select(RefreshSession).where(
                RefreshSession.user_id == user_id,
                RefreshSession.revoked_at.is_(None),
            )
        )
        for refresh_session in sessions:
            refresh_session.revoked_at = revoked_at


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, project_id: UUID) -> Project | None:
        return await self._session.get(Project, project_id)

    async def list_for_user(
        self, *, user_id: UUID, system_admin: bool, offset: int, limit: int
    ) -> tuple[list[tuple[Project, ProjectRole | None]], int]:
        if system_admin:
            projects = list(
                (
                    await self._session.scalars(
                        select(Project)
                        .order_by(Project.created_at.desc())
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
            total = await self._session.scalar(select(func.count()).select_from(Project))
            return [(project, None) for project in projects], int(total or 0)

        base = (
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
        )
        rows = list(
            (
                await self._session.execute(
                    base.order_by(Project.created_at.desc()).offset(offset).limit(limit)
                )
            ).tuples()
        )
        count_query = (
            select(func.count()).select_from(ProjectMember).where(ProjectMember.user_id == user_id)
        )
        total = await self._session.scalar(count_query)
        accessible_rows: list[tuple[Project, ProjectRole | None]] = list(rows)
        return accessible_rows, int(total or 0)

    async def get_role(self, *, project_id: UUID, user_id: UUID) -> ProjectRole | None:
        role = await self._session.scalar(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        return ProjectRole(role) if role is not None else None

    async def get_member(self, *, project_id: UUID, user_id: UUID) -> ProjectMember | None:
        result = await self._session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_members(self, project_id: UUID) -> list[ProjectMember]:
        return list(
            (
                await self._session.scalars(
                    select(ProjectMember)
                    .where(ProjectMember.project_id == project_id)
                    .order_by(ProjectMember.created_at)
                )
            ).all()
        )

    async def count_owners(self, project_id: UUID) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.role == ProjectRole.OWNER,
            )
        )
        return int(total or 0)

    def add(self, entity: Project | ProjectMember | Folder) -> None:
        self._session.add(entity)

    async def delete(self, entity: ProjectMember | Folder) -> None:
        await self._session.delete(entity)

    async def get_folder(self, folder_id: UUID) -> Folder | None:
        return await self._session.get(Folder, folder_id)

    async def list_folders(self, project_id: UUID) -> list[Folder]:
        return list(
            (
                await self._session.scalars(
                    select(Folder)
                    .where(Folder.project_id == project_id)
                    .order_by(Folder.created_at)
                )
            ).all()
        )

    async def folder_name_exists(
        self,
        *,
        project_id: UUID,
        parent_id: UUID | None,
        name: str,
        excluding_id: UUID | None = None,
    ) -> bool:
        query = select(Folder.id).where(
            Folder.project_id == project_id,
            Folder.parent_id == parent_id,
            Folder.name == name,
        )
        if excluding_id is not None:
            query = query.where(Folder.id != excluding_id)
        return await self._session.scalar(query) is not None

    async def descendant_ids(self, folder_id: UUID) -> set[UUID]:
        descendants = (
            select(Folder.id)
            .where(Folder.parent_id == folder_id)
            .cte(name="folder_descendants", recursive=True)
        )
        descendants = descendants.union_all(
            select(Folder.id).join(descendants, Folder.parent_id == descendants.c.id)
        )
        return set((await self._session.scalars(select(descendants.c.id))).all())

    async def list_audit_logs(
        self,
        *,
        project_id: UUID,
        action: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[AuditLog], int]:
        filters = [AuditLog.project_id == project_id]
        if action:
            filters.append(AuditLog.action == action)
        query = select(AuditLog).where(*filters)
        logs = list(
            (
                await self._session.scalars(
                    query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(AuditLog).where(*filters)
        )
        return logs, int(total or 0)
