from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.access import TeamGrantRole
from app.models.access import ProjectTeamGrant, Team, TeamMember, User
from app.repositories.access import TeamRepository, UserRepository
from app.services.audit import AuditService
from app.services.projects import ProjectService


class TeamService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._teams = TeamRepository(session)
        self._users = UserRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def list_teams(self, *, page: int, page_size: int) -> tuple[list[Team], int]:
        return await self._teams.list_teams(offset=(page - 1) * page_size, limit=page_size)

    async def create(self, *, actor: User, name: str, description: str) -> Team:
        self._require_administrator(actor)
        normalized_name = name.strip()
        if await self._teams.get_by_name(normalized_name) is not None:
            raise AppError(code="TEAM_NAME_EXISTS", message="团队名称已存在", status_code=409)
        team = Team(
            name=normalized_name,
            description=description.strip(),
            created_by_id=actor.id,
        )
        self._teams.add(team)
        await self._session.flush()
        self._record_team_audit(actor=actor, team=team, action="team.created")
        await self._commit()
        await self._session.refresh(team)
        return team

    async def update(
        self,
        *,
        actor: User,
        team_id: UUID,
        name: str | None,
        description: str | None,
    ) -> Team:
        self._require_administrator(actor)
        team = await self._get_team(team_id)
        if name is not None:
            normalized_name = name.strip()
            duplicate = await self._teams.get_by_name(normalized_name)
            if duplicate is not None and duplicate.id != team_id:
                raise AppError(code="TEAM_NAME_EXISTS", message="团队名称已存在", status_code=409)
            team.name = normalized_name
        if description is not None:
            team.description = description.strip()
        self._record_team_audit(actor=actor, team=team, action="team.updated")
        await self._commit()
        await self._session.refresh(team)
        return team

    async def list_members(self, *, actor: User, team_id: UUID) -> list[TeamMember]:
        self._require_administrator(actor)
        await self._get_team(team_id)
        return await self._teams.list_members(team_id)

    async def add_member(self, *, actor: User, team_id: UUID, user_id: UUID) -> TeamMember:
        self._require_administrator(actor)
        team = await self._get_team(team_id)
        user = await self._users.get(user_id)
        if user is None or not user.is_active:
            raise AppError(code="USER_NOT_FOUND", message="用户不存在", status_code=404)
        existing = await self._teams.get_member(team_id=team_id, user_id=user_id)
        if existing is not None:
            return existing
        member = TeamMember(team_id=team_id, user_id=user_id)
        self._teams.add(member)
        await self._session.flush()
        self._record_team_audit(
            actor=actor,
            team=team,
            action="team.member_added",
            resource_id=member.id,
            details={"user_id": str(user_id)},
        )
        await self._commit()
        await self._session.refresh(member)
        return member

    async def remove_member(self, *, actor: User, team_id: UUID, user_id: UUID) -> None:
        self._require_administrator(actor)
        team = await self._get_team(team_id)
        member = await self._teams.get_member(team_id=team_id, user_id=user_id)
        if member is None:
            raise AppError(code="TEAM_MEMBER_NOT_FOUND", message="团队成员不存在", status_code=404)
        resource_id = member.id
        await self._teams.delete(member)
        self._record_team_audit(
            actor=actor,
            team=team,
            action="team.member_removed",
            resource_id=resource_id,
            details={"user_id": str(user_id)},
        )
        await self._commit()

    async def list_project_grants(self, *, actor: User, project_id: UUID) -> list[ProjectTeamGrant]:
        await self._projects.get(actor=actor, project_id=project_id)
        return await self._teams.list_grants(project_id)

    async def upsert_project_grant(
        self,
        *,
        actor: User,
        project_id: UUID,
        team_id: UUID,
        role: TeamGrantRole,
    ) -> ProjectTeamGrant:
        await self._projects.authorize_owner(actor=actor, project_id=project_id)
        await self._get_team(team_id)
        grant = await self._teams.get_grant(project_id=project_id, team_id=team_id)
        if grant is None:
            grant = ProjectTeamGrant(
                project_id=project_id,
                team_id=team_id,
                role=role,
                created_by_id=actor.id,
            )
            self._teams.add(grant)
        else:
            grant.role = role
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="project.team_grant_upserted",
            resource_type="project_team_grant",
            resource_id=grant.id,
            details={"team_id": str(team_id), "role": role.value},
        )
        await self._commit()
        await self._session.refresh(grant)
        return grant

    async def remove_project_grant(self, *, actor: User, project_id: UUID, team_id: UUID) -> None:
        await self._projects.authorize_owner(actor=actor, project_id=project_id)
        grant = await self._teams.get_grant(project_id=project_id, team_id=team_id)
        if grant is None:
            raise AppError(code="TEAM_GRANT_NOT_FOUND", message="团队授权不存在", status_code=404)
        resource_id = grant.id
        await self._teams.delete(grant)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="project.team_grant_removed",
            resource_type="project_team_grant",
            resource_id=resource_id,
            details={"team_id": str(team_id)},
        )
        await self._commit()

    async def _get_team(self, team_id: UUID) -> Team:
        team = await self._teams.get(team_id)
        if team is None:
            raise AppError(code="TEAM_NOT_FOUND", message="团队不存在", status_code=404)
        return team

    @staticmethod
    def _require_administrator(actor: User) -> None:
        if not actor.is_system_admin:
            raise AppError(
                code="SYSTEM_ADMIN_REQUIRED", message="需要系统管理员权限", status_code=403
            )

    def _record_team_audit(
        self,
        *,
        actor: User,
        team: Team,
        action: str,
        resource_id: UUID | None = None,
        details: dict[str, str] | None = None,
    ) -> None:
        self._audit.record(
            actor_user_id=actor.id,
            project_id=None,
            action=action,
            resource_type="team",
            resource_id=resource_id or team.id,
            details={"team_id": str(team.id), **(details or {})},
        )

    async def _commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise AppError(code="TEAM_CONFLICT", message="团队数据冲突", status_code=409) from error
