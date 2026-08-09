from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.errors import AppError
from app.schemas.access import (
    ProjectTeamGrantResponse,
    ProjectTeamGrantWrite,
    TeamCreate,
    TeamMemberResponse,
    TeamMemberWrite,
    TeamResponse,
    TeamUpdate,
)
from app.schemas.common import Page
from app.services.teams import TeamService

router = APIRouter()


@router.get("/teams", response_model=Page[TeamResponse])
async def list_teams(
    session: SessionDependency,
    _current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[TeamResponse]:
    teams, total = await TeamService(session).list_teams(page=page, page_size=page_size)
    return Page(
        items=[TeamResponse.model_validate(team) for team in teams],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/teams", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: TeamCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TeamResponse:
    team = await TeamService(session).create(
        actor=current_user,
        name=payload.name,
        description=payload.description,
    )
    return TeamResponse.model_validate(team)


@router.patch("/teams/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: UUID,
    payload: TeamUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TeamResponse:
    team = await TeamService(session).update(
        actor=current_user,
        team_id=team_id,
        name=payload.name,
        description=payload.description,
    )
    return TeamResponse.model_validate(team)


@router.get("/teams/{team_id}/members", response_model=list[TeamMemberResponse])
async def list_team_members(
    team_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[TeamMemberResponse]:
    members = await TeamService(session).list_members(actor=current_user, team_id=team_id)
    return [TeamMemberResponse.model_validate(member) for member in members]


@router.put("/teams/{team_id}/members/{user_id}", response_model=TeamMemberResponse)
async def add_team_member(
    team_id: UUID,
    user_id: UUID,
    payload: TeamMemberWrite,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TeamMemberResponse:
    if payload.user_id != user_id:
        raise AppError(code="USER_ID_MISMATCH", message="成员 ID 不一致", status_code=422)
    member = await TeamService(session).add_member(
        actor=current_user,
        team_id=team_id,
        user_id=user_id,
    )
    return TeamMemberResponse.model_validate(member)


@router.delete("/teams/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_member(
    team_id: UUID,
    user_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> None:
    await TeamService(session).remove_member(
        actor=current_user,
        team_id=team_id,
        user_id=user_id,
    )


@router.get(
    "/projects/{project_id}/team-grants",
    response_model=list[ProjectTeamGrantResponse],
)
async def list_project_team_grants(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[ProjectTeamGrantResponse]:
    grants = await TeamService(session).list_project_grants(
        actor=current_user, project_id=project_id
    )
    return [ProjectTeamGrantResponse.model_validate(grant) for grant in grants]


@router.put(
    "/projects/{project_id}/team-grants/{team_id}",
    response_model=ProjectTeamGrantResponse,
)
async def upsert_project_team_grant(
    project_id: UUID,
    team_id: UUID,
    payload: ProjectTeamGrantWrite,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ProjectTeamGrantResponse:
    if payload.team_id != team_id:
        raise AppError(code="TEAM_ID_MISMATCH", message="团队 ID 不一致", status_code=422)
    grant = await TeamService(session).upsert_project_grant(
        actor=current_user,
        project_id=project_id,
        team_id=team_id,
        role=payload.role,
    )
    return ProjectTeamGrantResponse.model_validate(grant)


@router.delete(
    "/projects/{project_id}/team-grants/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_project_team_grant(
    project_id: UUID,
    team_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> None:
    await TeamService(session).remove_project_grant(
        actor=current_user,
        project_id=project_id,
        team_id=team_id,
    )
