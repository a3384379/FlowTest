"""Controlled MCP bootstrap of organization test assets.

The bootstrap surface is intentionally small and monotonic: it can create or
reuse project, test/sandbox environment, and service endpoint metadata, but it
never changes an existing name, policy, member list, credential, or routing
setting.  Every non-dry-run operation is idempotent and scoped to the
authenticated organization and service account.
"""

from __future__ import annotations

from typing import Literal, cast
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_tenant_context, get_trace_id
from app.core.errors import AppError
from app.domain.network import OutboundNetworkPolicy
from app.models.access import Project, User
from app.models.api_assets import Environment
from app.models.organizations import ServiceAccount
from app.models.service_targets import Service, ServiceEndpoint
from app.schemas.mcp_bootstrap import (
    MCPEnsureEnvironmentRequest,
    MCPEnsureEnvironmentResponse,
    MCPEnsureProjectRequest,
    MCPEnsureProjectResponse,
    MCPEnsureServiceTargetRequest,
    MCPEnsureServiceTargetResponse,
)
from app.services.audit import AuditService
from app.services.idempotency import (
    OrganizationIdempotencyService,
    require_idempotency_key,
)
from app.services.outbound import OutboundRequestGuard, outbound_request_guard
from app.services.projects import ProjectAccess, ProjectService

MCP_PROJECT_BOOTSTRAP_SCOPE = "mcp:project:bootstrap"
_PROJECT_OPERATION = "mcp.ensure_project"
_ENVIRONMENT_OPERATION = "mcp.ensure_test_environment"
_SERVICE_TARGET_OPERATION = "mcp.ensure_service_target"


class MCPBootstrapService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        outbound_guard: OutboundRequestGuard = outbound_request_guard,
    ) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._audit = AuditService(session)
        self._outbound_guard = outbound_guard

    async def ensure_project(
        self,
        *,
        actor: User,
        account: ServiceAccount,
        payload: MCPEnsureProjectRequest,
        idempotency_key: str | None,
    ) -> MCPEnsureProjectResponse:
        organization_id = self._require_scope(account)
        idempotency = OrganizationIdempotencyService(self._session)
        request_payload = payload.model_dump(mode="json")
        if payload.dry_run:
            existing = await self._resolve_project(
                organization_id=organization_id,
                payload=payload,
            )
            return self._project_response(
                organization_id=organization_id,
                operation="dry_run",
                project=existing,
            )
        key = require_idempotency_key(idempotency_key)
        cached = await idempotency.completed_response(
            key=key,
            organization_id=organization_id,
            actor_key=f"service-account:{account.id}",
            operation=_PROJECT_OPERATION,
            request_payload=request_payload,
        )
        if cached is not None:
            return MCPEnsureProjectResponse.model_validate(cached)
        # Validate the current target before claiming a new receipt.  A
        # completed receipt above intentionally bypasses this mutable-state
        # check so historical recovery remains available.
        await self._resolve_project(
            organization_id=organization_id,
            payload=payload,
        )

        async def action() -> MCPEnsureProjectResponse:
            project = await self._resolve_project(
                organization_id=organization_id,
                payload=payload,
            )
            created = False
            if project is None:
                try:
                    async with self._session.begin_nested():
                        access = await self._projects.create_bootstrap(
                            actor=actor,
                            organization_id=organization_id,
                            name=payload.name,
                            description=payload.description,
                            external_key=payload.external_key,
                            service_account_id=account.id,
                        )
                    project = access.project
                    created = True
                except IntegrityError:
                    # A different idempotency key may win the organization
                    # external-key race.  Re-read and return that project;
                    # the savepoint keeps the receipt transaction usable.
                    project = await self._resolve_project(
                        organization_id=organization_id,
                        payload=payload,
                    )
                    if project is None:
                        raise
                    return self._project_response(
                        organization_id=organization_id,
                        operation="reused",
                        project=project,
                    )
            return self._project_response(
                organization_id=organization_id,
                operation="created" if created else "reused",
                project=project,
            )

        result = await idempotency.run(
            key=key,
            organization_id=organization_id,
            actor_key=f"service-account:{account.id}",
            operation=_PROJECT_OPERATION,
            request_payload=request_payload,
            action=action,
            atomic_action=True,
        )
        return MCPEnsureProjectResponse.model_validate(result)

    async def ensure_test_environment(
        self,
        *,
        actor: User,
        account: ServiceAccount,
        payload: MCPEnsureEnvironmentRequest,
        idempotency_key: str | None,
    ) -> MCPEnsureEnvironmentResponse:
        organization_id = self._require_scope(account)
        idempotency = OrganizationIdempotencyService(self._session)
        request_payload = payload.model_dump(mode="json")
        if not payload.dry_run:
            key = require_idempotency_key(idempotency_key)
            cached = await idempotency.completed_response(
                key=key,
                organization_id=organization_id,
                actor_key=f"service-account:{account.id}",
                operation=_ENVIRONMENT_OPERATION,
                request_payload=request_payload,
            )
            if cached is not None:
                return MCPEnsureEnvironmentResponse.model_validate(cached)
        access = await self._projects.authorize_bootstrap(project_id=payload.project_id)
        base_url = _normalize_base_url(str(payload.base_url))
        await self._validate_target_url(access, base_url)
        existing = await self._find_environment(payload.project_id, payload.name)
        self._validate_environment_match(existing, payload, base_url)
        if payload.dry_run:
            return self._environment_response(
                organization_id=organization_id,
                project_id=payload.project_id,
                operation="dry_run",
                environment=existing,
                classification=payload.classification,
                base_url=base_url,
            )
        key = require_idempotency_key(idempotency_key)

        async def action() -> MCPEnsureEnvironmentResponse:
            current = await self._find_environment(payload.project_id, payload.name)
            self._validate_environment_match(current, payload, base_url)
            if current is not None:
                return self._environment_response(
                    organization_id=organization_id,
                    project_id=payload.project_id,
                    operation="reused",
                    environment=current,
                    classification=payload.classification,
                    base_url=base_url,
                )
            try:
                async with self._session.begin_nested():
                    environment = await self._create_environment(
                        actor=actor,
                        account=account,
                        project=access.project,
                        name=payload.name,
                        base_url=base_url,
                        classification=payload.classification,
                    )
                return self._environment_response(
                    organization_id=organization_id,
                    project_id=payload.project_id,
                    operation="created",
                    environment=environment,
                    classification=payload.classification,
                    base_url=base_url,
                )
            except IntegrityError:
                current = await self._find_environment(payload.project_id, payload.name)
                self._validate_environment_match(current, payload, base_url)
                if current is None:
                    raise
                return self._environment_response(
                    organization_id=organization_id,
                    project_id=payload.project_id,
                    operation="reused",
                    environment=current,
                    classification=payload.classification,
                    base_url=base_url,
                )

        result = await idempotency.run(
            key=key,
            organization_id=organization_id,
            actor_key=f"service-account:{account.id}",
            operation=_ENVIRONMENT_OPERATION,
            request_payload=request_payload,
            action=action,
            atomic_action=True,
        )
        return MCPEnsureEnvironmentResponse.model_validate(result)

    async def ensure_service_target(
        self,
        *,
        actor: User,
        account: ServiceAccount,
        payload: MCPEnsureServiceTargetRequest,
        idempotency_key: str | None,
    ) -> MCPEnsureServiceTargetResponse:
        organization_id = self._require_scope(account)
        idempotency = OrganizationIdempotencyService(self._session)
        request_payload = payload.model_dump(mode="json")
        if not payload.dry_run:
            key = require_idempotency_key(idempotency_key)
            cached = await idempotency.completed_response(
                key=key,
                organization_id=organization_id,
                actor_key=f"service-account:{account.id}",
                operation=_SERVICE_TARGET_OPERATION,
                request_payload=request_payload,
            )
            if cached is not None:
                return MCPEnsureServiceTargetResponse.model_validate(cached)
        access = await self._projects.authorize_bootstrap(project_id=payload.project_id)
        environment = await self._session.get(Environment, payload.environment_id)
        if (
            environment is None
            or environment.project_id != payload.project_id
            or environment.classification not in {"test", "sandbox"}
        ):
            raise AppError(
                code="ENVIRONMENT_NOT_ALLOWED",
                message="Service Target 只能绑定测试或 Sandbox 环境",
                status_code=422 if environment is not None else 404,
            )
        base_url = _normalize_base_url(str(payload.base_url))
        await self._validate_target_url(access, base_url)
        service = await self._find_service(payload.project_id, payload.service_key)
        self._validate_service_match(service, payload)
        endpoint = (
            await self._find_endpoint(environment.id, service.id, payload.variant)
            if service is not None
            else None
        )
        self._validate_endpoint_match(endpoint, payload, base_url)
        if payload.dry_run:
            return self._service_target_response(
                organization_id=organization_id,
                project_id=payload.project_id,
                environment_id=environment.id,
                operation="dry_run",
                service=service,
                endpoint=endpoint,
                service_key=payload.service_key,
                variant=payload.variant,
                base_url=base_url,
            )
        key = require_idempotency_key(idempotency_key)

        async def action() -> MCPEnsureServiceTargetResponse:
            return await self._ensure_service_target_action(
                actor=actor,
                account=account,
                payload=payload,
                environment=environment,
                organization_id=organization_id,
                base_url=base_url,
            )

        result = await idempotency.run(
            key=key,
            organization_id=organization_id,
            actor_key=f"service-account:{account.id}",
            operation=_SERVICE_TARGET_OPERATION,
            request_payload=request_payload,
            action=action,
            atomic_action=True,
        )
        return MCPEnsureServiceTargetResponse.model_validate(result)

    async def _ensure_service_target_action(
        self,
        *,
        actor: User,
        account: ServiceAccount,
        payload: MCPEnsureServiceTargetRequest,
        environment: Environment,
        organization_id: UUID,
        base_url: str,
    ) -> MCPEnsureServiceTargetResponse:
        current_service = await self._find_service(payload.project_id, payload.service_key)
        self._validate_service_match(current_service, payload)
        created_service = current_service is None
        if current_service is None:
            try:
                async with self._session.begin_nested():
                    current_service = await self._create_service(
                        actor=actor,
                        account=account,
                        project_id=payload.project_id,
                        service_key=payload.service_key,
                        name=payload.name,
                        service_type=payload.service_type,
                    )
            except IntegrityError:
                current_service = await self._find_service(payload.project_id, payload.service_key)
                if current_service is None:
                    raise
                self._validate_service_match(current_service, payload)
                created_service = False
        current_endpoint = await self._find_endpoint(
            environment.id,
            current_service.id,
            payload.variant,
        )
        self._validate_endpoint_match(current_endpoint, payload, base_url)
        created_endpoint = current_endpoint is None
        if current_endpoint is None:
            try:
                async with self._session.begin_nested():
                    current_endpoint = await self._create_endpoint(
                        actor=actor,
                        account=account,
                        project_id=payload.project_id,
                        environment=environment,
                        service=current_service,
                        variant=payload.variant,
                        base_url=base_url,
                    )
            except IntegrityError:
                current_endpoint = await self._find_endpoint(
                    environment.id,
                    current_service.id,
                    payload.variant,
                )
                if current_endpoint is None:
                    raise
                self._validate_endpoint_match(current_endpoint, payload, base_url)
                created_endpoint = False
        if environment.default_service_id is None:
            environment.default_service_id = current_service.id
        return self._service_target_response(
            organization_id=organization_id,
            project_id=payload.project_id,
            environment_id=environment.id,
            operation="created" if created_service or created_endpoint else "reused",
            service=current_service,
            endpoint=current_endpoint,
            service_key=payload.service_key,
            variant=payload.variant,
            base_url=base_url,
        )

    def _require_scope(self, account: ServiceAccount) -> UUID:
        context = get_tenant_context()
        if (
            context is None
            or context.service_account_id != account.id
            or context.organization_id != account.organization_id
        ):
            raise AppError(
                code="MCP_AUTHENTICATION_REQUIRED",
                message="MCP 初始化需要有效的服务账号令牌",
                status_code=401,
            )
        if MCP_PROJECT_BOOTSTRAP_SCOPE not in context.scopes:
            raise AppError(
                code="MCP_SCOPE_REQUIRED",
                message="服务账号缺少项目初始化权限范围",
                status_code=403,
            )
        return context.organization_id

    async def _resolve_project(
        self,
        *,
        organization_id: UUID,
        payload: MCPEnsureProjectRequest,
    ) -> Project | None:
        if payload.project_id is not None:
            project = await self._session.get(Project, payload.project_id)
            if (
                project is None
                or project.organization_id is None
                or project.organization_id != organization_id
            ):
                raise AppError(code="PROJECT_NOT_FOUND", message="项目不存在", status_code=404)
            if payload.external_key is not None:
                keyed_project = cast(
                    Project | None,
                    await self._session.scalar(
                        select(Project).where(
                            Project.organization_id == organization_id,
                            Project.external_key == payload.external_key,
                        )
                    ),
                )
                if keyed_project is not None and keyed_project.id != project.id:
                    raise AppError(
                        code="PROJECT_IDENTITY_CONFLICT",
                        message="project_id 与 external_key 指向不同项目",
                        status_code=409,
                    )
                if project.external_key not in {None, payload.external_key}:
                    raise AppError(
                        code="PROJECT_IDENTITY_CONFLICT",
                        message="project_id 与 external_key 指向不同项目",
                        status_code=409,
                    )
            return project
        if payload.external_key is not None:
            project = cast(
                Project | None,
                await self._session.scalar(
                    select(Project).where(
                        Project.organization_id == organization_id,
                        Project.external_key == payload.external_key,
                    )
                ),
            )
            if project is not None:
                return project
        projects = list(
            (
                await self._session.scalars(
                    select(Project).where(
                        Project.organization_id == organization_id,
                        Project.name == payload.name,
                    )
                )
            ).all()
        )
        if len(projects) > 1:
            raise AppError(
                code="AMBIGUOUS_PROJECT",
                message="项目名称匹配到多个项目, 请提供 external_key 或 project_id",
                status_code=409,
            )
        return projects[0] if projects else None

    async def _find_environment(self, project_id: UUID, name: str) -> Environment | None:
        return cast(
            Environment | None,
            await self._session.scalar(
                select(Environment).where(
                    Environment.project_id == project_id,
                    Environment.name == name,
                )
            ),
        )

    async def _find_service(self, project_id: UUID, service_key: str) -> Service | None:
        return cast(
            Service | None,
            await self._session.scalar(
                select(Service).where(
                    Service.project_id == project_id,
                    Service.service_key == service_key,
                )
            ),
        )

    async def _find_endpoint(
        self,
        environment_id: UUID,
        service_id: UUID,
        variant: str,
    ) -> ServiceEndpoint | None:
        return cast(
            ServiceEndpoint | None,
            await self._session.scalar(
                select(ServiceEndpoint).where(
                    ServiceEndpoint.environment_id == environment_id,
                    ServiceEndpoint.service_id == service_id,
                    ServiceEndpoint.variant == variant,
                )
            ),
        )

    async def _create_environment(
        self,
        *,
        actor: User,
        account: ServiceAccount,
        project: Project,
        name: str,
        base_url: str,
        classification: Literal["test", "sandbox"],
    ) -> Environment:
        environment = Environment(
            project_id=project.id,
            name=name,
            base_url=base_url,
            classification=classification,
            variables={},
            headers={},
            created_by_id=actor.id,
        )
        self._session.add(environment)
        await self._session.flush()
        service = await self._find_service(project.id, "default")
        if service is None:
            service = Service(
                project_id=project.id,
                service_key="default",
                name="Default Service",
                description="MCP bootstrap default target",
                service_type="http",
                created_by_id=actor.id,
            )
            self._session.add(service)
            await self._session.flush()
            self._audit.record(
                actor_user_id=actor.id,
                organization_id=account.organization_id,
                project_id=project.id,
                action="service_target.bootstrap_created",
                resource_type="service",
                resource_id=service.id,
                details={"service_account_id": str(account.id), "service_key": "default"},
            )
        environment.default_service_id = service.id
        endpoint = ServiceEndpoint(
            project_id=project.id,
            environment_id=environment.id,
            service_id=service.id,
            variant="default",
            base_url=base_url,
            tls_verify=True,
            headers={},
            variables={},
            secret_refs=[],
            created_by_id=actor.id,
        )
        self._session.add(endpoint)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=account.organization_id,
            project_id=project.id,
            action="service_endpoint.bootstrap_created",
            resource_type="service_endpoint",
            resource_id=endpoint.id,
            details={"service_account_id": str(account.id), "variant": "default"},
        )
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=account.organization_id,
            project_id=project.id,
            action="environment.bootstrap_created",
            resource_type="environment",
            resource_id=environment.id,
            details={"service_account_id": str(account.id)},
        )
        await self._session.flush()
        return environment

    async def _create_service(
        self,
        *,
        actor: User,
        account: ServiceAccount,
        project_id: UUID,
        service_key: str,
        name: str,
        service_type: str,
    ) -> Service:
        service = Service(
            project_id=project_id,
            service_key=service_key,
            name=name,
            description="MCP bootstrap service target",
            service_type=service_type,
            created_by_id=actor.id,
        )
        self._session.add(service)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=account.organization_id,
            project_id=project_id,
            action="service_target.bootstrap_created",
            resource_type="service",
            resource_id=service.id,
            details={"service_account_id": str(account.id), "service_key": service_key},
        )
        return service

    async def _create_endpoint(
        self,
        *,
        actor: User,
        account: ServiceAccount,
        project_id: UUID,
        environment: Environment,
        service: Service,
        variant: str,
        base_url: str,
    ) -> ServiceEndpoint:
        endpoint = ServiceEndpoint(
            project_id=project_id,
            environment_id=environment.id,
            service_id=service.id,
            variant=variant,
            base_url=base_url,
            tls_verify=True,
            headers={},
            variables={},
            secret_refs=[],
            created_by_id=actor.id,
        )
        self._session.add(endpoint)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=account.organization_id,
            project_id=project_id,
            action="service_endpoint.bootstrap_created",
            resource_type="service_endpoint",
            resource_id=endpoint.id,
            details={"service_account_id": str(account.id), "variant": variant},
        )
        return endpoint

    async def _validate_target_url(self, access: ProjectAccess, base_url: str) -> None:
        policy = OutboundNetworkPolicy(
            allowed_hosts=tuple(access.project.outbound_allowed_hosts),
            allowed_private_cidrs=tuple(access.project.outbound_allowed_private_cidrs),
            enabled=access.project.outbound_policy_enabled,
        )
        try:
            await self._outbound_guard.enforce(base_url, policy)
        except AppError as error:
            raise AppError(
                code="NETWORK_APPROVAL_REQUIRED",
                message="目标地址未获得项目出站网络批准",
                status_code=422,
            ) from error

    @staticmethod
    def _validate_environment_match(
        existing: Environment | None,
        payload: MCPEnsureEnvironmentRequest,
        base_url: str,
    ) -> None:
        if existing is None:
            return
        if (
            _normalize_base_url(existing.base_url) != base_url
            or existing.classification != payload.classification
        ):
            raise AppError(
                code="ENVIRONMENT_CONFIGURATION_CONFLICT",
                message="同名环境已存在但目标地址或分类不同, 不会覆盖现有配置",
                status_code=409,
            )

    @staticmethod
    def _validate_service_match(
        existing: Service | None,
        payload: MCPEnsureServiceTargetRequest,
    ) -> None:
        if existing is not None and not existing.enabled:
            raise AppError(
                code="SERVICE_DISABLED",
                message="同一 Service Key 的 Service 已停用, 不会自动重新启用",
                status_code=409,
            )
        if existing is not None and existing.service_type != payload.service_type:
            raise AppError(
                code="SERVICE_CONFIGURATION_CONFLICT",
                message="同一 Service Key 的类型不同, 不会覆盖现有配置",
                status_code=409,
            )

    @staticmethod
    def _validate_endpoint_match(
        existing: ServiceEndpoint | None,
        payload: MCPEnsureServiceTargetRequest,
        base_url: str,
    ) -> None:
        if existing is None:
            return
        if not existing.enabled:
            raise AppError(
                code="ENDPOINT_DISABLED",
                message="同一 Endpoint Variant 的 Endpoint 已停用, 不会自动重新启用",
                status_code=409,
            )
        if _normalize_base_url(existing.base_url) != base_url or not existing.tls_verify:
            raise AppError(
                code="SERVICE_ENDPOINT_CONFIGURATION_CONFLICT",
                message="同一 Endpoint Variant 的目标或 TLS 策略不同, 不会覆盖现有配置",
                status_code=409,
            )

    @staticmethod
    def _project_response(
        *,
        organization_id: UUID,
        operation: Literal["created", "reused", "dry_run"],
        project: Project | None,
    ) -> MCPEnsureProjectResponse:
        return MCPEnsureProjectResponse(
            operation=operation,
            organization_id=organization_id,
            project_id=None if operation == "dry_run" or project is None else project.id,
            project_name=None if operation == "dry_run" or project is None else project.name,
            external_key=(
                None if operation == "dry_run" or project is None else project.external_key
            ),
            trace_id=get_trace_id(),
        )

    @staticmethod
    def _environment_response(
        *,
        organization_id: UUID,
        project_id: UUID,
        operation: Literal["created", "reused", "dry_run"],
        environment: Environment | None,
        classification: Literal["test", "sandbox"],
        base_url: str,
    ) -> MCPEnsureEnvironmentResponse:
        return MCPEnsureEnvironmentResponse(
            operation=operation,
            organization_id=organization_id,
            project_id=project_id,
            environment_id=(
                None if operation == "dry_run" or environment is None else environment.id
            ),
            environment_name=None
            if operation == "dry_run" or environment is None
            else environment.name,
            classification=classification,
            base_url=None if operation == "dry_run" else base_url,
            trace_id=get_trace_id(),
        )

    @staticmethod
    def _service_target_response(
        *,
        organization_id: UUID,
        project_id: UUID,
        environment_id: UUID,
        operation: Literal["created", "reused", "dry_run"],
        service: Service | None,
        endpoint: ServiceEndpoint | None,
        service_key: str,
        variant: str,
        base_url: str,
    ) -> MCPEnsureServiceTargetResponse:
        return MCPEnsureServiceTargetResponse(
            operation=operation,
            organization_id=organization_id,
            project_id=project_id,
            environment_id=environment_id,
            service_id=None if operation == "dry_run" or service is None else service.id,
            endpoint_id=None if operation == "dry_run" or endpoint is None else endpoint.id,
            service_key=service_key,
            variant=variant,
            base_url=None if operation == "dry_run" else base_url,
            trace_id=get_trace_id(),
        )


def _normalize_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    # Keep a canonical representation for equality checks without changing
    # path semantics (``/api`` remains ``/api``).
    return value.strip().rstrip("/") if parsed.path != "/" else value.strip()[:-1]
