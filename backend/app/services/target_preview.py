"""Resolve unsaved routing candidates without persistence, DNS, HTTP or secret reads."""

from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_trace_id
from app.core.errors import AppError
from app.domain.api_assets import QueryParameterSpec
from app.domain.import_execution import render_import_query
from app.domain.scopes import HeaderScope, ResolvedValue
from app.domain.target_preview import (
    PreviewAPIChange,
    PreviewEndpointChange,
    PreviewEnvironmentChange,
    PreviewResolution,
    PreviewResolutionError,
    PreviewServiceChange,
    TargetPreviewCommand,
    TargetPreviewResult,
)
from app.models.access import User
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.service_targets import Service, ServiceEndpoint
from app.repositories.api_assets import APIAssetRepository
from app.repositories.service_targets import ServiceTargetRepository
from app.services.projects import ProjectService
from app.services.request_targets import RequestTargetResolver


class _CandidateTargets(ServiceTargetRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        service: Service | None,
        endpoint: ServiceEndpoint | None,
    ) -> None:
        super().__init__(session)
        self._candidate_service = service
        self._candidate_endpoint = endpoint

    async def get_service(self, service_id: UUID) -> Service | None:
        if self._candidate_service is not None and self._candidate_service.id == service_id:
            return self._candidate_service
        return await super().get_service(service_id)

    async def find_service_by_key(self, *, project_id: UUID, service_key: str) -> Service | None:
        service = self._candidate_service
        if service is not None and (service.project_id, service.service_key) == (
            project_id,
            service_key,
        ):
            return service
        return await super().find_service_by_key(project_id=project_id, service_key=service_key)

    async def find_endpoint(
        self, *, environment_id: UUID, service_id: UUID, variant: str
    ) -> ServiceEndpoint | None:
        candidate = self._candidate_endpoint
        if candidate is not None and (candidate.environment_id, candidate.service_id) == (
            environment_id,
            service_id,
        ):
            if candidate.variant == variant:
                return candidate
            stored = await super().find_endpoint(
                environment_id=environment_id, service_id=service_id, variant=variant
            )
            return None if stored is not None and stored.id == candidate.id else stored
        return await super().find_endpoint(
            environment_id=environment_id, service_id=service_id, variant=variant
        )


class _RoutingOnlyResolver(RequestTargetResolver):
    def __init__(
        self,
        session: AsyncSession,
        *,
        service: Service | None = None,
        endpoint: ServiceEndpoint | None = None,
    ) -> None:
        super().__init__(session)
        self._targets = _CandidateTargets(session, service=service, endpoint=endpoint)

    async def _load_secret_values(
        self, *, project_id: UUID, environment_id: UUID, allowed_refs: tuple[str, ...]
    ) -> dict[str, str]:
        # Configuration preview is not an authorized secret diagnostic capture.
        return {}

    @staticmethod
    def _render_headers(
        layers: dict[HeaderScope, dict[str, str]], variables: dict[str, ResolvedValue]
    ) -> dict[str, ResolvedValue]:
        return {}


class TargetPreviewService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._targets = ServiceTargetRepository(session)
        self._assets = APIAssetRepository(session)

    async def preview(
        self, *, actor: User, project_id: UUID, command: TargetPreviewCommand
    ) -> TargetPreviewResult:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        service, endpoint = await self._candidate_targets(project_id, command)
        environment = await self._environment(project_id, command.environment_id)
        version = await self._version(project_id, command.api_id, command.api_version)
        before = await self._resolve(actor, project_id, command, environment, version)
        after_environment = _candidate_environment(environment, command)
        after_version = _candidate_version(version, command)
        after = await self._resolve(
            actor,
            project_id,
            command,
            after_environment,
            after_version,
            service=service,
            endpoint=endpoint,
        )
        return TargetPreviewResult(before=before, after=after)

    async def _candidate_targets(
        self, project_id: UUID, command: TargetPreviewCommand
    ) -> tuple[Service | None, ServiceEndpoint | None]:
        change = command.change
        if isinstance(change, PreviewServiceChange):
            stored = await self._service(project_id, change.service_id)
            return Service(
                id=stored.id,
                project_id=stored.project_id,
                service_key=stored.service_key,
                name=stored.name,
                enabled=change.enabled if change.enabled is not None else stored.enabled,
            ), None
        if isinstance(change, PreviewEndpointChange):
            endpoint = await self._targets.get_endpoint(change.endpoint_id)
            if endpoint is None or endpoint.project_id != project_id:
                raise _not_found("SERVICE_ENDPOINT_NOT_FOUND", "服务地址不存在")
            conflict = await self._targets.find_endpoint(
                environment_id=endpoint.environment_id,
                service_id=endpoint.service_id,
                variant=change.variant or endpoint.variant,
            )
            if conflict is not None and conflict.id != endpoint.id:
                raise AppError(
                    code="SERVICE_ENDPOINT_EXISTS",
                    message="该环境中的地址变体已存在",
                    status_code=409,
                )
            return None, _candidate_endpoint(endpoint, change)
        if isinstance(change, PreviewEnvironmentChange):
            await self._environment(project_id, change.environment_id)
        else:
            await self._definition(project_id, change.api_id)
        if change.service_id is not None:
            await self._service(project_id, change.service_id)
            if isinstance(change, PreviewEnvironmentChange):
                await self._require_default_endpoint(change.environment_id, change.service_id)
        return None, None

    async def _require_default_endpoint(self, environment_id: UUID, service_id: UUID) -> None:
        endpoint = await self._targets.find_endpoint(
            environment_id=environment_id,
            service_id=service_id,
            variant="default",
        )
        if endpoint is None:
            raise AppError(
                code="SERVICE_ENDPOINT_NOT_FOUND",
                message="默认服务尚未配置 default 地址变体",
                status_code=422,
            )

    async def _service(self, project_id: UUID, service_id: UUID) -> Service:
        service = await self._targets.get_service(service_id)
        if service is None or service.project_id != project_id:
            raise _not_found("SERVICE_NOT_FOUND", "服务不存在")
        return service

    async def _environment(
        self, project_id: UUID, environment_id: UUID | None
    ) -> Environment | None:
        if environment_id is None:
            return None
        environment = await self._session.get(Environment, environment_id)
        if (
            environment is None
            or environment.project_id != project_id
            or environment.archived_at is not None
        ):
            raise _not_found("ENVIRONMENT_NOT_FOUND", "环境不存在")
        return environment

    async def _definition(self, project_id: UUID, api_id: UUID) -> APIDefinition:
        definition = await self._assets.get_definition(api_id)
        if definition is None or definition.project_id != project_id or not definition.is_active:
            raise _not_found("API_DEFINITION_NOT_FOUND", "接口不存在")
        return definition

    async def _version(
        self, project_id: UUID, api_id: UUID | None, version_number: int | None
    ) -> APIVersion | None:
        if api_id is None:
            return None
        definition = await self._definition(project_id, api_id)
        version = await self._assets.get_version(
            definition_id=api_id, version=version_number or definition.current_version
        )
        if version is None:
            raise _not_found("API_VERSION_NOT_FOUND", "接口版本不存在")
        return version

    async def _resolve(
        self,
        actor: User,
        project_id: UUID,
        command: TargetPreviewCommand,
        environment: Environment | None,
        version: APIVersion | None,
        *,
        service: Service | None = None,
        endpoint: ServiceEndpoint | None = None,
    ) -> PreviewResolution:
        if environment is None or version is None:
            return _unavailable(
                "PREVIEW_CONTEXT_MISSING", "请选择预览环境和接口; 没有上下文无法计算地址"
            )
        if version.auth_kind == "api_key" and version.auth_config.get("in") == "query":
            return _unavailable(
                "PREVIEW_AUTH_QUERY_UNAVAILABLE", "地址依赖认证查询参数, 配置预览不读取或返回认证值"
            )
        try:
            resolver = _RoutingOnlyResolver(self._session, service=service, endpoint=endpoint)
            target = await resolver.resolve(
                actor=actor,
                project_id=project_id,
                environment=environment,
                version=version,
                path=version.path,
                node_service_override=command.service_override,
                endpoint_variant=command.endpoint_variant,
                runtime_variables={},
                runtime_headers={},
                workflow_variables={},
                dataset_variables={},
            )
            query = render_import_query(
                tuple(
                    QueryParameterSpec(
                        name=str(item["name"]),
                        value=str(item["value"]),
                        enabled=bool(item.get("enabled", True)),
                    )
                    for item in version.query_parameters
                ),
                target.variables,
                version.canonical_contract or {},
            )
            target = resolver.finalize(target, api_headers={}, query=query)
            _validate_routing_url(target.effective_url)
        except AppError as error:
            return _unavailable(error.code, error.message)
        except ValueError:
            return _unavailable(
                "PREVIEW_ROUTING_UNAVAILABLE",
                "地址缺少变量或接口参数, 无法完整解析; 请在执行上下文中配置",
            )
        return PreviewResolution(
            status="resolved",
            url=target.effective_url,
            service_key=target.service_key,
            endpoint_variant=target.endpoint_variant,
            endpoint_revision=target.endpoint_revision,
            api_version=version.version,
        )


def _candidate_environment(
    environment: Environment | None, command: TargetPreviewCommand
) -> Environment | None:
    change = command.change
    if (
        environment is None
        or not isinstance(change, PreviewEnvironmentChange)
        or change.environment_id != environment.id
    ):
        return environment
    return Environment(
        id=environment.id,
        project_id=environment.project_id,
        name=environment.name,
        base_url=environment.base_url,
        default_service_id=change.service_id,
        variables=environment.variables,
        headers=environment.headers,
    )


def _candidate_version(
    version: APIVersion | None, command: TargetPreviewCommand
) -> APIVersion | None:
    change = command.change
    if (
        version is None
        or not isinstance(change, PreviewAPIChange)
        or change.api_id != version.api_definition_id
        or command.api_version is not None
    ):
        return version
    return APIVersion(
        api_definition_id=version.api_definition_id,
        version=version.version + (change.service_id != version.service_id),
        service_id=change.service_id,
        path=version.path,
        query_parameters=version.query_parameters,
        headers=version.headers,
        variables=version.variables,
        body=version.body,
        auth_kind=version.auth_kind,
        auth_config=version.auth_config,
        canonical_contract=version.canonical_contract,
    )


def _candidate_endpoint(
    endpoint: ServiceEndpoint, change: PreviewEndpointChange
) -> ServiceEndpoint:
    return ServiceEndpoint(
        id=endpoint.id,
        project_id=endpoint.project_id,
        environment_id=endpoint.environment_id,
        service_id=endpoint.service_id,
        variant=change.variant if change.variant is not None else endpoint.variant,
        base_url=change.base_url.rstrip("/") if change.base_url is not None else endpoint.base_url,
        enabled=change.enabled if change.enabled is not None else endpoint.enabled,
        variables=change.variables if change.variables is not None else endpoint.variables,
        headers=endpoint.headers,
        secret_refs=endpoint.secret_refs,
        connect_timeout_ms=endpoint.connect_timeout_ms,
        read_timeout_ms=endpoint.read_timeout_ms,
        tls_verify=endpoint.tls_verify,
        proxy_ref=endpoint.proxy_ref,
        revision=endpoint.revision + 1,
    )


def _validate_routing_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise AppError(
            code="PREVIEW_TARGET_INVALID",
            message="目标必须是有效的 HTTP(S) 地址且不能包含用户凭据",
            status_code=422,
        )
    _ = parsed.port


def _not_found(code: str, message: str) -> AppError:
    return AppError(code=code, message=message, status_code=404)


def _unavailable(code: str, message: str) -> PreviewResolution:
    return PreviewResolution(
        status="unavailable",
        error=PreviewResolutionError(code=code, message=message, trace_id=get_trace_id()),
    )
