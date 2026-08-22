from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.config import settings
from app.core.errors import AppError
from app.domain.access import ProjectRole
from app.schemas.access import (
    AuditLogResponse,
    FolderCreate,
    FolderResponse,
    FolderUpdate,
    MemberResponse,
    MemberUpsert,
    ProjectCapacityPolicy,
    ProjectCreate,
    ProjectPermissionResponse,
    ProjectResponse,
    ProjectRetentionPolicy,
    ProjectRetentionUpdate,
    ProjectSecurityPolicy,
    ProjectUpdate,
)
from app.schemas.common import Page
from app.services.projects import ProjectAccess, ProjectService

router = APIRouter(prefix="/projects")


@router.get("", response_model=Page[ProjectResponse])
async def list_projects(
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[ProjectResponse]:
    projects, total = await ProjectService(session).list_projects(
        actor=current_user, page=page, page_size=page_size
    )
    return Page(
        items=[_project_response(access) for access in projects],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate, session: SessionDependency, current_user: CurrentUser
) -> ProjectResponse:
    access = await ProjectService(session).create(
        actor=current_user,
        name=payload.name,
        description=payload.description,
    )
    return _project_response(access)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID, session: SessionDependency, current_user: CurrentUser
) -> ProjectResponse:
    return _project_response(
        await ProjectService(session).get(actor=current_user, project_id=project_id)
    )


@router.get("/{project_id}/permissions", response_model=ProjectPermissionResponse)
async def get_project_permissions(
    project_id: UUID, session: SessionDependency, current_user: CurrentUser
) -> ProjectPermissionResponse:
    access = await ProjectService(session).get(actor=current_user, project_id=project_id)
    return ProjectPermissionResponse(
        effective_role="system_admin" if current_user.is_system_admin else str(access.role),
        capabilities=sorted(access.capabilities, key=str),
        matrix={role.value: sorted(role.capabilities, key=str) for role in ProjectRole},
    )


@router.get("/{project_id}/security-policy", response_model=ProjectSecurityPolicy)
async def get_project_security_policy(
    project_id: UUID, session: SessionDependency, current_user: CurrentUser
) -> ProjectSecurityPolicy:
    policy = await ProjectService(session).get_security_policy(
        actor=current_user, project_id=project_id
    )
    return ProjectSecurityPolicy(
        enabled=policy.enabled,
        allowed_hosts=list(policy.allowed_hosts),
        allowed_private_cidrs=list(policy.allowed_private_cidrs),
    )


@router.put("/{project_id}/security-policy", response_model=ProjectSecurityPolicy)
async def update_project_security_policy(
    project_id: UUID,
    payload: ProjectSecurityPolicy,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ProjectSecurityPolicy:
    policy = await ProjectService(session).update_security_policy(
        actor=current_user,
        project_id=project_id,
        enabled=payload.enabled,
        allowed_hosts=payload.allowed_hosts,
        allowed_private_cidrs=payload.allowed_private_cidrs,
    )
    return ProjectSecurityPolicy(
        enabled=policy.enabled,
        allowed_hosts=list(policy.allowed_hosts),
        allowed_private_cidrs=list(policy.allowed_private_cidrs),
    )


@router.get("/{project_id}/retention-policy", response_model=ProjectRetentionPolicy)
async def get_project_retention_policy(
    project_id: UUID, session: SessionDependency, current_user: CurrentUser
) -> ProjectRetentionPolicy:
    days = await ProjectService(session).get_retention_policy(
        actor=current_user, project_id=project_id
    )
    return ProjectRetentionPolicy(retention_days=days, maximum_days=settings.retention_max_days)


@router.put("/{project_id}/retention-policy", response_model=ProjectRetentionPolicy)
async def update_project_retention_policy(
    project_id: UUID,
    payload: ProjectRetentionUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ProjectRetentionPolicy:
    days = await ProjectService(session).update_retention_policy(
        actor=current_user,
        project_id=project_id,
        retention_days=payload.retention_days,
    )
    return ProjectRetentionPolicy(retention_days=days, maximum_days=settings.retention_max_days)


@router.get("/{project_id}/capacity-policy", response_model=ProjectCapacityPolicy)
async def get_project_capacity_policy(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ProjectCapacityPolicy:
    concurrency, queued = await ProjectService(session).get_capacity_policy(
        actor=current_user, project_id=project_id
    )
    return ProjectCapacityPolicy(
        execution_concurrency_limit=concurrency,
        queued_run_limit=queued,
    )


@router.put("/{project_id}/capacity-policy", response_model=ProjectCapacityPolicy)
async def update_project_capacity_policy(
    project_id: UUID,
    payload: ProjectCapacityPolicy,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ProjectCapacityPolicy:
    concurrency, queued = await ProjectService(session).update_capacity_policy(
        actor=current_user,
        project_id=project_id,
        execution_concurrency_limit=payload.execution_concurrency_limit,
        queued_run_limit=payload.queued_run_limit,
    )
    return ProjectCapacityPolicy(
        execution_concurrency_limit=concurrency,
        queued_run_limit=queued,
    )


@router.get("/{project_id}/audit-logs", response_model=Page[AuditLogResponse])
async def list_project_audit_logs(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    action: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[AuditLogResponse]:
    logs, total = await ProjectService(session).list_audit_logs(
        actor=current_user,
        project_id=project_id,
        action=action,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[AuditLogResponse.model_validate(item) for item in logs],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ProjectResponse:
    access = await ProjectService(session).update(
        actor=current_user,
        project_id=project_id,
        name=payload.name,
        description=payload.description,
    )
    return _project_response(access)


@router.get("/{project_id}/members", response_model=list[MemberResponse])
async def list_members(
    project_id: UUID, session: SessionDependency, current_user: CurrentUser
) -> list[MemberResponse]:
    members = await ProjectService(session).list_members(actor=current_user, project_id=project_id)
    return [MemberResponse.model_validate(member) for member in members]


@router.put("/{project_id}/members/{user_id}", response_model=MemberResponse)
async def upsert_member(
    project_id: UUID,
    user_id: UUID,
    payload: MemberUpsert,
    session: SessionDependency,
    current_user: CurrentUser,
) -> MemberResponse:
    if payload.user_id != user_id:
        raise AppError(code="USER_ID_MISMATCH", message="成员 ID 不一致", status_code=422)
    member = await ProjectService(session).upsert_member(
        actor=current_user,
        project_id=project_id,
        user_id=user_id,
        role=payload.role,
    )
    return MemberResponse.model_validate(member)


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    project_id: UUID,
    user_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> None:
    await ProjectService(session).remove_member(
        actor=current_user, project_id=project_id, user_id=user_id
    )


@router.get("/{project_id}/folders", response_model=list[FolderResponse])
async def list_folders(
    project_id: UUID, session: SessionDependency, current_user: CurrentUser
) -> list[FolderResponse]:
    folders = await ProjectService(session).list_folders(actor=current_user, project_id=project_id)
    return [FolderResponse.model_validate(folder) for folder in folders]


@router.post(
    "/{project_id}/folders",
    response_model=FolderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder(
    project_id: UUID,
    payload: FolderCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> FolderResponse:
    folder = await ProjectService(session).create_folder(
        actor=current_user,
        project_id=project_id,
        name=payload.name,
        parent_id=payload.parent_id,
    )
    return FolderResponse.model_validate(folder)


@router.patch("/{project_id}/folders/{folder_id}", response_model=FolderResponse)
async def update_folder(
    project_id: UUID,
    folder_id: UUID,
    payload: FolderUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> FolderResponse:
    folder = await ProjectService(session).update_folder(
        actor=current_user,
        project_id=project_id,
        folder_id=folder_id,
        name=payload.name,
        parent_id=payload.parent_id,
        change_parent="parent_id" in payload.model_fields_set,
    )
    return FolderResponse.model_validate(folder)


@router.delete("/{project_id}/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    project_id: UUID,
    folder_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> None:
    await ProjectService(session).delete_folder(
        actor=current_user, project_id=project_id, folder_id=folder_id
    )


def _project_response(access: ProjectAccess) -> ProjectResponse:
    response = ProjectResponse.model_validate(access.project)
    return response.model_copy(update={"role": access.role})
