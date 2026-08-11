from typing import Annotated, cast

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import token_service
from app.http.oidc import HttpOIDCProvider
from app.models.access import User
from app.repositories.access import UserRepository
from app.services.oidc import OIDCConfiguration, OIDCProvider
from app.tasking.dispatch import TestPlanDispatcher, WorkflowDispatcher

SessionDependency = Annotated[AsyncSession, Depends(get_session)]
bearer_scheme = HTTPBearer(auto_error=False)


def get_oidc_provider() -> OIDCProvider:
    return HttpOIDCProvider(OIDCConfiguration.from_settings(settings))


OIDCProviderDependency = Annotated[OIDCProvider, Depends(get_oidc_provider)]


async def get_current_user(
    session: SessionDependency,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(code="AUTHENTICATION_REQUIRED", message="请先登录", status_code=401)
    try:
        claims = token_service.decode_access_token(credentials.credentials)
    except (jwt.InvalidTokenError, ValueError, KeyError) as error:
        raise AppError(
            code="INVALID_ACCESS_TOKEN", message="访问令牌无效", status_code=401
        ) from error
    user = await UserRepository(session).get(claims.user_id)
    if user is None or not user.is_active:
        raise AppError(code="INVALID_ACCESS_TOKEN", message="访问令牌无效", status_code=401)
    return user


AuthenticatedUser = Annotated[User, Depends(get_current_user)]


async def require_password_change_complete(authenticated_user: AuthenticatedUser) -> User:
    if authenticated_user.requires_password_change:
        raise AppError(
            code="PASSWORD_CHANGE_REQUIRED",
            message="首次登录必须修改密码",
            status_code=403,
        )
    return authenticated_user


CurrentUser = Annotated[User, Depends(require_password_change_complete)]


async def require_system_admin(current_user: CurrentUser) -> User:
    if not current_user.is_system_admin:
        raise AppError(code="SYSTEM_ADMIN_REQUIRED", message="需要系统管理员权限", status_code=403)
    return current_user


SystemAdministrator = Annotated[User, Depends(require_system_admin)]


def get_workflow_coordinator(request: Request) -> WorkflowDispatcher:
    coordinator = getattr(request.app.state, "workflow_run_coordinator", None)
    if coordinator is None or not callable(getattr(coordinator, "start", None)):
        raise AppError(
            code="WORKFLOW_RUNNER_UNAVAILABLE",
            message="工作流运行服务尚未就绪",
            status_code=503,
        )
    return cast(WorkflowDispatcher, coordinator)


WorkflowCoordinator = Annotated[WorkflowDispatcher, Depends(get_workflow_coordinator)]


def get_test_plan_dispatcher(request: Request) -> TestPlanDispatcher:
    dispatcher = getattr(request.app.state, "test_plan_dispatcher", None)
    if dispatcher is None or not callable(getattr(dispatcher, "start_test_plan", None)):
        raise AppError(
            code="TASK_QUEUE_UNAVAILABLE",
            message="后台任务队列尚未就绪",
            status_code=503,
        )
    return cast(TestPlanDispatcher, dispatcher)


TestPlanQueue = Annotated[TestPlanDispatcher, Depends(get_test_plan_dispatcher)]
