import asyncio
import json
from dataclasses import dataclass
from time import monotonic
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import redact
from app.domain.mock_services import (
    MockRequestContext,
    MockTemplateError,
    compile_mock_path,
    match_mock_conditions,
    normalize_mock_path,
    render_mock_template,
)
from app.models.access import User
from app.models.data_sources import MockRequestLog, MockRoute, MockService
from app.repositories.data_sources import DataSourceRepository
from app.schemas.data_sources import MockRouteWrite
from app.services.audit import AuditService
from app.services.projects import ProjectService

_FORBIDDEN_RESPONSE_HEADERS = frozenset(
    {
        "connection",
        "content-encoding",
        "content-length",
        "content-type",
        "location",
        "refresh",
        "server",
        "set-cookie",
        "transfer-encoding",
        "upgrade",
        "www-authenticate",
    }
)


@dataclass(frozen=True, slots=True)
class MockDispatchRequest:
    slug: str
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: JsonValue


@dataclass(frozen=True, slots=True)
class MockDispatchResult:
    status_code: int
    headers: dict[str, str]
    body: JsonValue


class MockServiceManager:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = DataSourceRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def create_service(
        self,
        *,
        actor: User,
        project_id: UUID,
        name: str,
        slug: str,
        description: str,
    ) -> MockService:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        await self._ensure_service_unique(project_id, name.strip(), slug)
        service = MockService(
            project_id=project_id,
            name=name.strip(),
            slug=slug,
            description=description.strip(),
            is_enabled=True,
            created_by_id=actor.id,
        )
        self._repository.add(service)
        await self._session.flush()
        self._record(actor, service, "mock_service.created")
        await self._session.commit()
        await self._session.refresh(service)
        return service

    async def list_services(self, *, actor: User, project_id: UUID) -> list[MockService]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_mock_services(project_id)

    async def update_service(
        self,
        *,
        actor: User,
        project_id: UUID,
        service_id: UUID,
        name: str | None,
        description: str | None,
        is_enabled: bool | None,
    ) -> MockService:
        service = await self._get_project_service(project_id, service_id)
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        if name is not None:
            normalized = name.strip()
            existing = await self._repository.find_mock_service_by_name(
                project_id=project_id,
                name=normalized,
                excluding_id=service.id,
            )
            if existing is not None:
                raise AppError(
                    code="MOCK_SERVICE_NAME_EXISTS",
                    message="Mock 服务名称已存在",
                    status_code=409,
                )
            service.name = normalized
        if description is not None:
            service.description = description.strip()
        if is_enabled is not None:
            service.is_enabled = is_enabled
        self._record(actor, service, "mock_service.updated")
        await self._session.commit()
        await self._session.refresh(service)
        return service

    async def create_route(
        self,
        *,
        actor: User,
        project_id: UUID,
        service_id: UUID,
        payload: MockRouteWrite,
    ) -> MockRoute:
        service = await self._get_project_service(project_id, service_id)
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        await self._ensure_route_name(service.id, payload.name.strip())
        path = _validated_path(payload.path_pattern)
        route = MockRoute(
            mock_service_id=service.id,
            created_by_id=actor.id,
            path_pattern=path,
            **_route_fields(payload),
        )
        self._repository.add(route)
        await self._session.flush()
        self._record(actor, service, "mock_route.created", resource_id=route.id)
        await self._session.commit()
        await self._session.refresh(route)
        return route

    async def list_routes(
        self,
        *,
        actor: User,
        project_id: UUID,
        service_id: UUID,
    ) -> list[MockRoute]:
        service = await self._get_project_service(project_id, service_id)
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_mock_routes(service.id, enabled_only=False)

    async def update_route(
        self,
        *,
        actor: User,
        project_id: UUID,
        service_id: UUID,
        route_id: UUID,
        payload: MockRouteWrite,
    ) -> MockRoute:
        service = await self._get_project_service(project_id, service_id)
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        route = await self._get_service_route(service.id, route_id)
        await self._ensure_route_name(service.id, payload.name.strip(), excluding_id=route.id)
        fields = _route_fields(payload)
        fields["path_pattern"] = _validated_path(payload.path_pattern)
        for name, value in fields.items():
            setattr(route, name, value)
        self._record(actor, service, "mock_route.updated", resource_id=route.id)
        await self._session.commit()
        await self._session.refresh(route)
        return route

    async def delete_route(
        self,
        *,
        actor: User,
        project_id: UUID,
        service_id: UUID,
        route_id: UUID,
    ) -> None:
        service = await self._get_project_service(project_id, service_id)
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        route = await self._get_service_route(service.id, route_id)
        self._record(actor, service, "mock_route.deleted", resource_id=route.id)
        await self._repository.delete(route)
        await self._session.commit()

    async def list_logs(
        self,
        *,
        actor: User,
        project_id: UUID,
        service_id: UUID,
        page: int,
        page_size: int,
    ) -> tuple[list[MockRequestLog], int]:
        service = await self._get_project_service(project_id, service_id)
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_mock_logs(
            service_id=service.id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def dispatch(self, request: MockDispatchRequest) -> MockDispatchResult:
        started_at = monotonic()
        service = await self._repository.find_mock_service_by_slug(request.slug)
        if service is None or not service.is_enabled:
            raise AppError(
                code="MOCK_SERVICE_NOT_FOUND", message="Mock 服务不存在", status_code=404
            )
        scenario = _selected_scenario(request)
        route, context = await self._match_route(service, request, scenario)
        if route is None or context is None:
            result = MockDispatchResult(404, {}, {"error": "没有匹配的 Mock 路由"})
        else:
            result = await _render_route(route, context)
        self._repository.add(_request_log(service, route, request, scenario, result, started_at))
        await self._session.commit()
        return result

    async def _match_route(
        self,
        service: MockService,
        request: MockDispatchRequest,
        scenario: str | None,
    ) -> tuple[MockRoute | None, MockRequestContext | None]:
        routes = await self._repository.list_mock_routes(service.id, enabled_only=True)
        for route in routes:
            if route.method != request.method or route.scenario != scenario:
                continue
            match = compile_mock_path(route.path_pattern).fullmatch(request.path)
            if match is None:
                continue
            context = MockRequestContext(
                path=match.groupdict(),
                query=request.query,
                headers=request.headers,
                body=request.body,
            )
            if match_mock_conditions(route.query_conditions, route.header_conditions, context):
                return route, context
        return None, None

    async def _get_project_service(self, project_id: UUID, service_id: UUID) -> MockService:
        service = await self._repository.get_mock_service(service_id)
        if service is None or service.project_id != project_id:
            raise AppError(
                code="MOCK_SERVICE_NOT_FOUND", message="Mock 服务不存在", status_code=404
            )
        return service

    async def _get_service_route(self, service_id: UUID, route_id: UUID) -> MockRoute:
        route = await self._repository.get_mock_route(route_id)
        if route is None or route.mock_service_id != service_id:
            raise AppError(code="MOCK_ROUTE_NOT_FOUND", message="Mock 路由不存在", status_code=404)
        return route

    async def _ensure_service_unique(self, project_id: UUID, name: str, slug: str) -> None:
        by_name = await self._repository.find_mock_service_by_name(
            project_id=project_id,
            name=name,
        )
        by_slug = await self._repository.find_mock_service_by_slug(slug)
        if by_name is not None or by_slug is not None:
            raise AppError(
                code="MOCK_SERVICE_EXISTS",
                message="Mock 服务名称或访问标识已存在",
                status_code=409,
            )

    async def _ensure_route_name(
        self,
        service_id: UUID,
        name: str,
        *,
        excluding_id: UUID | None = None,
    ) -> None:
        existing = await self._repository.find_mock_route_by_name(
            service_id=service_id,
            name=name,
            excluding_id=excluding_id,
        )
        if existing is not None:
            raise AppError(code="MOCK_ROUTE_EXISTS", message="Mock 路由名称已存在", status_code=409)

    def _record(
        self,
        actor: User,
        service: MockService,
        action: str,
        *,
        resource_id: UUID | None = None,
    ) -> None:
        self._audit.record(
            actor_user_id=actor.id,
            project_id=service.project_id,
            action=action,
            resource_type="mock_service" if resource_id is None else "mock_route",
            resource_id=resource_id or service.id,
        )


def _validated_path(pattern: str) -> str:
    try:
        normalized = normalize_mock_path(pattern)
        compile_mock_path(normalized)
        return normalized
    except MockTemplateError as error:
        raise AppError(code="INVALID_MOCK_PATH", message=str(error), status_code=422) from error


def _route_fields(payload: MockRouteWrite) -> dict[str, object]:
    headers = {
        name: value
        for name, value in payload.response_headers.items()
        if name.lower() not in _FORBIDDEN_RESPONSE_HEADERS
    }
    if len(headers) != len(payload.response_headers):
        raise AppError(
            code="INVALID_MOCK_RESPONSE_HEADER",
            message="Mock 响应包含禁止设置的传输级 Header",
            status_code=422,
        )
    return {
        "name": payload.name.strip(),
        "method": payload.method,
        "query_conditions": dict(payload.query_conditions),
        "header_conditions": dict(payload.header_conditions),
        "response_status": payload.response_status,
        "response_headers": headers,
        "response_body": payload.response_body,
        "delay_ms": payload.delay_ms,
        "scenario": payload.scenario.strip() if payload.scenario else None,
        "priority": payload.priority,
        "is_enabled": payload.is_enabled,
    }


async def _render_route(route: MockRoute, context: MockRequestContext) -> MockDispatchResult:
    try:
        body = render_mock_template(cast(JsonValue, route.response_body), context)
    except MockTemplateError as error:
        return MockDispatchResult(500, {}, {"error": str(error)})
    encoded = json.dumps(body, ensure_ascii=False, default=str).encode()
    if len(encoded) > settings.inline_body_limit_bytes:
        return MockDispatchResult(500, {}, {"error": "Mock 响应超过 2 MB 上限"})
    if route.delay_ms:
        await asyncio.sleep(route.delay_ms / 1000)
    return MockDispatchResult(route.response_status, dict(route.response_headers), body)


def _selected_scenario(request: MockDispatchRequest) -> str | None:
    headers = {name.lower(): value for name, value in request.headers.items()}
    scenario = request.query.get("_scenario") or headers.get("x-flowtest-scenario")
    return scenario[:80] if scenario else None


def _request_log(
    service: MockService,
    route: MockRoute | None,
    request: MockDispatchRequest,
    scenario: str | None,
    result: MockDispatchResult,
    started_at: float,
) -> MockRequestLog:
    return MockRequestLog(
        mock_service_id=service.id,
        mock_route_id=route.id if route else None,
        method=request.method,
        path=request.path,
        query_parameters=cast(dict[str, str], redact(request.query)),
        headers=cast(dict[str, str], redact(request.headers)),
        body=cast(JsonValue, redact(request.body)),
        matched=route is not None,
        scenario=scenario,
        response_status=result.status_code,
        duration_ms=max(0, round((monotonic() - started_at) * 1000)),
    )
