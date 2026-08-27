from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, cast
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.context import reset_tenant_context, set_tenant_context
from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import token_service
from app.domain.contract_hub import PactBrokerSource, ProviderInteractionVerifier
from app.domain.mcp_read import MCP_READ_SCOPE
from app.domain.runtime_profiles import RuntimeProfile
from app.domain.tenant import TenantContext
from app.http.contract_hub import HttpPactBrokerSource, HttpProviderInteractionVerifier
from app.http.imports import HttpImportDocumentFetcher
from app.http.oidc import HttpOIDCProvider
from app.importers.sources import ImportDocumentFetcher
from app.models.access import User
from app.models.organizations import ServiceAccount
from app.repositories.access import UserRepository
from app.services.mcp_controlled_write import MCP_WRITE_SCOPE
from app.services.oidc import OIDCConfiguration, OIDCProvider
from app.services.organizations import OrganizationContextService
from app.services.service_accounts import ServiceAccountService
from app.tasking.dispatch import (
    AIJobDispatcher,
    EnvironmentTaskDispatcher,
    PerformanceRunDispatcher,
    RunnerFabricDispatcher,
    TestPlanDispatcher,
    WorkflowDispatcher,
)

SessionDependency = Annotated[AsyncSession, Depends(get_session)]
bearer_scheme = HTTPBearer(auto_error=False)


def get_oidc_provider() -> OIDCProvider:
    return HttpOIDCProvider(OIDCConfiguration.from_settings(settings))


OIDCProviderDependency = Annotated[OIDCProvider, Depends(get_oidc_provider)]


def get_provider_interaction_verifier() -> ProviderInteractionVerifier:
    return HttpProviderInteractionVerifier(
        request_timeout_seconds=settings.pact_provider_request_timeout_seconds
    )


ProviderVerifier = Annotated[
    ProviderInteractionVerifier,
    Depends(get_provider_interaction_verifier),
]


def get_pact_broker_source() -> PactBrokerSource | None:
    if not settings.pact_broker_base_url:
        return None
    return HttpPactBrokerSource(
        base_url=settings.pact_broker_base_url,
        token=settings.pact_broker_token,
        request_timeout_seconds=settings.pact_broker_request_timeout_seconds,
    )


PactBroker = Annotated[PactBrokerSource | None, Depends(get_pact_broker_source)]


def get_import_document_fetcher() -> ImportDocumentFetcher:
    return HttpImportDocumentFetcher(request_timeout_seconds=settings.request_timeout_seconds)


ImportDocumentFetcherDependency = Annotated[
    ImportDocumentFetcher,
    Depends(get_import_document_fetcher),
]


async def get_current_user(
    request: Request,
    session: SessionDependency,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AsyncIterator[User]:
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
    requested_organization_id = _organization_header(request)
    tenant = await OrganizationContextService(session).resolve(
        actor=user,
        requested_organization_id=requested_organization_id,
    )
    context_token = set_tenant_context(tenant)
    try:
        yield user
    finally:
        reset_tenant_context(context_token)


AuthenticatedUser = Annotated[User, Depends(get_current_user)]


async def require_password_change_complete(authenticated_user: AuthenticatedUser) -> User:
    if (
        authenticated_user.requires_password_change
        and settings.runtime_profile is not RuntimeProfile.STANDALONE
    ):
        raise AppError(
            code="PASSWORD_CHANGE_REQUIRED",
            message="首次登录必须修改密码",
            status_code=403,
        )
    return authenticated_user


CurrentUser = Annotated[User, Depends(require_password_change_complete)]


@dataclass(frozen=True, slots=True)
class MCPAuthenticatedPrincipal:
    actor: User
    account: ServiceAccount
    tenant: TenantContext


async def get_mcp_authenticated_principal(
    session: SessionDependency,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AsyncIterator[MCPAuthenticatedPrincipal]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(
            code="MCP_AUTHENTICATION_REQUIRED",
            message="MCP 需要服务账号令牌",
            status_code=401,
        )
    account, tenant = await ServiceAccountService(session).authenticate(
        credentials.credentials,
        touch_last_used=False,
    )
    if MCP_READ_SCOPE not in tenant.scopes:
        raise AppError(
            code="MCP_SCOPE_REQUIRED",
            message="服务账号缺少 MCP 只读权限",
            status_code=403,
        )
    actor = await UserRepository(session).get(tenant.actor_id)
    if actor is None or not actor.is_active:
        raise AppError(
            code="MCP_AUTHENTICATION_REQUIRED",
            message="MCP 服务账号关联用户不可用",
            status_code=401,
        )
    context_token = set_tenant_context(tenant)
    try:
        yield MCPAuthenticatedPrincipal(actor=actor, account=account, tenant=tenant)
    finally:
        reset_tenant_context(context_token)


async def get_mcp_write_principal(
    session: SessionDependency,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AsyncIterator[MCPAuthenticatedPrincipal]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(
            code="MCP_AUTHENTICATION_REQUIRED",
            message="MCP 需要服务账号令牌",
            status_code=401,
        )
    account, tenant = await ServiceAccountService(session).authenticate(
        credentials.credentials,
        touch_last_used=False,
    )
    if MCP_WRITE_SCOPE not in tenant.scopes:
        raise AppError(
            code="MCP_SCOPE_REQUIRED",
            message="服务账号缺少 MCP 受控写入权限",
            status_code=403,
        )
    actor = await UserRepository(session).get(tenant.actor_id)
    if actor is None or not actor.is_active:
        raise AppError(
            code="MCP_AUTHENTICATION_REQUIRED",
            message="MCP 服务账号关联用户不可用",
            status_code=401,
        )
    context_token = set_tenant_context(tenant)
    try:
        yield MCPAuthenticatedPrincipal(actor=actor, account=account, tenant=tenant)
    finally:
        reset_tenant_context(context_token)


MCPCurrent = Annotated[
    MCPAuthenticatedPrincipal,
    Depends(get_mcp_authenticated_principal),
]

MCPWriteCurrent = Annotated[
    MCPAuthenticatedPrincipal,
    Depends(get_mcp_write_principal),
]


async def require_system_admin(current_user: CurrentUser) -> User:
    if not current_user.is_system_admin:
        raise AppError(code="SYSTEM_ADMIN_REQUIRED", message="需要系统管理员权限", status_code=403)
    return current_user


SystemAdministrator = Annotated[User, Depends(require_system_admin)]


def get_workflow_coordinator(request: Request, session: SessionDependency) -> WorkflowDispatcher:
    if settings.feature_runner_fabric_enabled:
        return RunnerFabricDispatcher(session)
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


def get_ai_job_dispatcher(request: Request) -> AIJobDispatcher:
    dispatcher = getattr(request.app.state, "ai_job_dispatcher", None)
    if dispatcher is None or not callable(getattr(dispatcher, "start_ai_job", None)):
        raise AppError(
            code="AI_QUEUE_UNAVAILABLE",
            message="AI 任务队列尚未就绪",
            status_code=503,
        )
    return cast(AIJobDispatcher, dispatcher)


AIJobQueue = Annotated[AIJobDispatcher, Depends(get_ai_job_dispatcher)]


def get_performance_dispatcher(request: Request) -> PerformanceRunDispatcher:
    dispatcher = getattr(request.app.state, "performance_dispatcher", None)
    if dispatcher is None or not callable(getattr(dispatcher, "start_performance_run", None)):
        raise AppError(
            code="PERFORMANCE_QUEUE_UNAVAILABLE",
            message="性能任务队列尚未就绪",
            status_code=503,
        )
    return cast(PerformanceRunDispatcher, dispatcher)


PerformanceQueue = Annotated[PerformanceRunDispatcher, Depends(get_performance_dispatcher)]


def get_environment_dispatcher(request: Request) -> EnvironmentTaskDispatcher:
    dispatcher = getattr(request.app.state, "environment_dispatcher", None)
    required = callable(getattr(dispatcher, "start_environment_provision", None)) and callable(
        getattr(dispatcher, "start_environment_cleanup", None)
    )
    if not required:
        raise AppError(
            code="ENVIRONMENT_QUEUE_UNAVAILABLE",
            message="环境任务队列尚未就绪",
            status_code=503,
        )
    return cast(EnvironmentTaskDispatcher, dispatcher)


EnvironmentQueue = Annotated[EnvironmentTaskDispatcher, Depends(get_environment_dispatcher)]


def _organization_header(request: Request) -> UUID | None:
    value = request.headers.get("X-Organization-Id", "").strip()
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError as error:
        raise AppError(
            code="INVALID_ORGANIZATION_ID",
            message="组织 ID 无效",
            status_code=400,
        ) from error
