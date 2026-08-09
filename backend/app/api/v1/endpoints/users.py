from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import SessionDependency, SystemAdministrator
from app.schemas.access import UserCreate, UserResponse, UserUpdate
from app.schemas.common import Page
from app.services.auth import UserService

router = APIRouter(prefix="/users")


@router.get("", response_model=Page[UserResponse])
async def list_users(
    session: SessionDependency,
    _administrator: SystemAdministrator,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[UserResponse]:
    users, total = await UserService(session).list(page=page, page_size=page_size)
    return Page(
        items=[UserResponse.model_validate(user) for user in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    session: SessionDependency,
    administrator: SystemAdministrator,
) -> UserResponse:
    user = await UserService(session).create(
        actor=administrator,
        email=payload.email,
        display_name=payload.display_name,
        password=payload.password,
        is_system_admin=payload.is_system_admin,
    )
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    session: SessionDependency,
    administrator: SystemAdministrator,
) -> UserResponse:
    user = await UserService(session).update(
        actor=administrator,
        user_id=user_id,
        display_name=payload.display_name,
        is_active=payload.is_active,
        is_system_admin=payload.is_system_admin,
    )
    return UserResponse.model_validate(user)
