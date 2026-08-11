from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import ProjectRole, TeamGrantRole
from app.models.access import (
    AuditLog,
    Folder,
    OIDCLoginTransaction,
    Project,
    ProjectMember,
    ProjectTeamGrant,
    RefreshSession,
    Team,
    TeamMember,
    User,
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_oidc_identity(self, *, provider: str, subject: str) -> User | None:
        result = await self._session.execute(
            select(User).where(
                User.oidc_provider == provider,
                User.oidc_subject == subject,
            )
        )
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


class OIDCLoginTransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_update(self, state_hash: str) -> OIDCLoginTransaction | None:
        result = await self._session.execute(
            select(OIDCLoginTransaction)
            .where(OIDCLoginTransaction.state_hash == state_hash)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    def add(self, transaction: OIDCLoginTransaction) -> None:
        self._session.add(transaction)


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

        direct_query = (
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
        )
        direct_rows = list((await self._session.execute(direct_query)).tuples())
        team_query = (
            select(Project, ProjectTeamGrant.role)
            .join(ProjectTeamGrant, ProjectTeamGrant.project_id == Project.id)
            .join(TeamMember, TeamMember.team_id == ProjectTeamGrant.team_id)
            .where(TeamMember.user_id == user_id)
        )
        team_rows = list((await self._session.execute(team_query)).tuples())
        direct_ids = {project.id for project, _role in direct_rows}
        accessible: dict[UUID, tuple[Project, ProjectRole]] = {
            project.id: (project, ProjectRole(role)) for project, role in direct_rows
        }
        for project, grant_role in team_rows:
            if project.id in direct_ids:
                continue
            role = TeamGrantRole(grant_role).project_role
            current = accessible.get(project.id)
            if current is None or role is ProjectRole.EDITOR:
                accessible[project.id] = (project, role)
        ordered = sorted(accessible.values(), key=lambda item: item[0].created_at, reverse=True)
        return list(ordered[offset : offset + limit]), len(ordered)

    async def get_role(self, *, project_id: UUID, user_id: UUID) -> ProjectRole | None:
        role = await self._session.scalar(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        if role is not None:
            return ProjectRole(role)
        grants = list(
            (
                await self._session.scalars(
                    select(ProjectTeamGrant.role)
                    .join(TeamMember, TeamMember.team_id == ProjectTeamGrant.team_id)
                    .where(
                        ProjectTeamGrant.project_id == project_id,
                        TeamMember.user_id == user_id,
                    )
                )
            ).all()
        )
        if TeamGrantRole.EDITOR in grants:
            return ProjectRole.EDITOR
        if grants:
            return ProjectRole.VIEWER
        return None

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


class TeamRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, team_id: UUID) -> Team | None:
        return await self._session.get(Team, team_id)

    async def get_by_name(self, name: str) -> Team | None:
        result = await self._session.execute(select(Team).where(Team.name == name))
        return result.scalar_one_or_none()

    async def list_teams(self, *, offset: int, limit: int) -> tuple[list[Team], int]:
        teams = list(
            (
                await self._session.scalars(
                    select(Team).order_by(Team.name).offset(offset).limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(select(func.count()).select_from(Team))
        return teams, int(total or 0)

    async def get_member(self, *, team_id: UUID, user_id: UUID) -> TeamMember | None:
        result = await self._session.execute(
            select(TeamMember).where(
                TeamMember.team_id == team_id,
                TeamMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_members(self, team_id: UUID) -> list[TeamMember]:
        return list(
            (
                await self._session.scalars(
                    select(TeamMember)
                    .where(TeamMember.team_id == team_id)
                    .order_by(TeamMember.created_at)
                )
            ).all()
        )

    async def get_grant(self, *, project_id: UUID, team_id: UUID) -> ProjectTeamGrant | None:
        result = await self._session.execute(
            select(ProjectTeamGrant).where(
                ProjectTeamGrant.project_id == project_id,
                ProjectTeamGrant.team_id == team_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_grants(self, project_id: UUID) -> list[ProjectTeamGrant]:
        return list(
            (
                await self._session.scalars(
                    select(ProjectTeamGrant)
                    .where(ProjectTeamGrant.project_id == project_id)
                    .order_by(ProjectTeamGrant.created_at)
                )
            ).all()
        )

    def add(self, entity: Team | TeamMember | ProjectTeamGrant) -> None:
        self._session.add(entity)

    async def delete(self, entity: TeamMember | ProjectTeamGrant) -> None:
        await self._session.delete(entity)
