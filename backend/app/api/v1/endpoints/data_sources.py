import json
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import JsonValue

from app.api.dependencies import CurrentUser, SessionDependency
from app.composition import build_credential_service
from app.core.config import settings
from app.core.errors import AppError
from app.schemas.common import Page
from app.schemas.data_sources import (
    CredentialCreate,
    CredentialMetadata,
    CredentialUpdate,
    MockRequestLogResponse,
    MockRouteResponse,
    MockRouteWrite,
    MockServiceCreate,
    MockServiceResponse,
    MockServiceUpdate,
)
from app.services.mock_services import MockDispatchRequest, MockServiceManager

router = APIRouter()
mock_dispatch_router = APIRouter(prefix="/mock")


@router.get("/credentials", response_model=list[CredentialMetadata])
async def list_credentials(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[CredentialMetadata]:
    credentials = await build_credential_service(session).list(
        actor=current_user, project_id=project_id
    )
    return [CredentialMetadata.model_validate(item) for item in credentials]


@router.post(
    "/credentials",
    response_model=CredentialMetadata,
    status_code=status.HTTP_201_CREATED,
)
async def create_credential(
    payload: CredentialCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> CredentialMetadata:
    credential = await build_credential_service(session).create(
        actor=current_user,
        project_id=payload.project_id,
        name=payload.name,
        kind=payload.kind,
        host=payload.host,
        port=payload.port,
        database_name=payload.database_name,
        username=payload.username,
        secret=payload.secret,
        secret_provider=payload.secret_provider,
        tls_enabled=payload.tls_enabled,
    )
    return CredentialMetadata.model_validate(credential)


@router.patch("/credentials/{credential_id}", response_model=CredentialMetadata)
async def update_credential(
    credential_id: UUID,
    payload: CredentialUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> CredentialMetadata:
    credential = await build_credential_service(session).update(
        actor=current_user,
        credential_id=credential_id,
        name=payload.name,
        host=payload.host,
        port=payload.port,
        database_name=payload.database_name,
        username=payload.username,
        secret=payload.secret,
        tls_enabled=payload.tls_enabled,
    )
    return CredentialMetadata.model_validate(credential)


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> Response:
    await build_credential_service(session).delete(actor=current_user, credential_id=credential_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/projects/{project_id}/mock-services",
    response_model=list[MockServiceResponse],
)
async def list_mock_services(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[MockServiceResponse]:
    services = await MockServiceManager(session).list_services(
        actor=current_user,
        project_id=project_id,
    )
    return [MockServiceResponse.model_validate(item) for item in services]


@router.post(
    "/projects/{project_id}/mock-services",
    response_model=MockServiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_mock_service(
    project_id: UUID,
    payload: MockServiceCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> MockServiceResponse:
    service = await MockServiceManager(session).create_service(
        actor=current_user,
        project_id=project_id,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
    )
    return MockServiceResponse.model_validate(service)


@router.patch(
    "/projects/{project_id}/mock-services/{service_id}",
    response_model=MockServiceResponse,
)
async def update_mock_service(
    project_id: UUID,
    service_id: UUID,
    payload: MockServiceUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> MockServiceResponse:
    service = await MockServiceManager(session).update_service(
        actor=current_user,
        project_id=project_id,
        service_id=service_id,
        name=payload.name,
        description=payload.description,
        is_enabled=payload.is_enabled,
    )
    return MockServiceResponse.model_validate(service)


@router.get(
    "/projects/{project_id}/mock-services/{service_id}/routes",
    response_model=list[MockRouteResponse],
)
async def list_mock_routes(
    project_id: UUID,
    service_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[MockRouteResponse]:
    routes = await MockServiceManager(session).list_routes(
        actor=current_user,
        project_id=project_id,
        service_id=service_id,
    )
    return [MockRouteResponse.model_validate(item) for item in routes]


@router.post(
    "/projects/{project_id}/mock-services/{service_id}/routes",
    response_model=MockRouteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_mock_route(
    project_id: UUID,
    service_id: UUID,
    payload: MockRouteWrite,
    session: SessionDependency,
    current_user: CurrentUser,
) -> MockRouteResponse:
    route = await MockServiceManager(session).create_route(
        actor=current_user,
        project_id=project_id,
        service_id=service_id,
        payload=payload,
    )
    return MockRouteResponse.model_validate(route)


@router.put(
    "/projects/{project_id}/mock-services/{service_id}/routes/{route_id}",
    response_model=MockRouteResponse,
)
async def update_mock_route(
    project_id: UUID,
    service_id: UUID,
    route_id: UUID,
    payload: MockRouteWrite,
    session: SessionDependency,
    current_user: CurrentUser,
) -> MockRouteResponse:
    route = await MockServiceManager(session).update_route(
        actor=current_user,
        project_id=project_id,
        service_id=service_id,
        route_id=route_id,
        payload=payload,
    )
    return MockRouteResponse.model_validate(route)


@router.delete(
    "/projects/{project_id}/mock-services/{service_id}/routes/{route_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_mock_route(
    project_id: UUID,
    service_id: UUID,
    route_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> Response:
    await MockServiceManager(session).delete_route(
        actor=current_user,
        project_id=project_id,
        service_id=service_id,
        route_id=route_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/projects/{project_id}/mock-services/{service_id}/request-logs",
    response_model=Page[MockRequestLogResponse],
)
async def list_mock_request_logs(
    project_id: UUID,
    service_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[MockRequestLogResponse]:
    logs, total = await MockServiceManager(session).list_logs(
        actor=current_user,
        project_id=project_id,
        service_id=service_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[MockRequestLogResponse.model_validate(item) for item in logs],
        total=total,
        page=page,
        page_size=page_size,
    )


@mock_dispatch_router.get("/{slug}/{path:path}", operation_id="dispatch_mock_get")
async def dispatch_mock_get(
    slug: str,
    path: str,
    request: Request,
    session: SessionDependency,
) -> JSONResponse:
    return await _dispatch_mock(slug, path, request, session)


@mock_dispatch_router.post("/{slug}/{path:path}", operation_id="dispatch_mock_post")
async def dispatch_mock_post(
    slug: str,
    path: str,
    request: Request,
    session: SessionDependency,
) -> JSONResponse:
    return await _dispatch_mock(slug, path, request, session)


@mock_dispatch_router.put("/{slug}/{path:path}", operation_id="dispatch_mock_put")
async def dispatch_mock_put(
    slug: str,
    path: str,
    request: Request,
    session: SessionDependency,
) -> JSONResponse:
    return await _dispatch_mock(slug, path, request, session)


@mock_dispatch_router.patch("/{slug}/{path:path}", operation_id="dispatch_mock_patch")
async def dispatch_mock_patch(
    slug: str,
    path: str,
    request: Request,
    session: SessionDependency,
) -> JSONResponse:
    return await _dispatch_mock(slug, path, request, session)


@mock_dispatch_router.delete("/{slug}/{path:path}", operation_id="dispatch_mock_delete")
async def dispatch_mock_delete(
    slug: str,
    path: str,
    request: Request,
    session: SessionDependency,
) -> JSONResponse:
    return await _dispatch_mock(slug, path, request, session)


async def _dispatch_mock(
    slug: str,
    path: str,
    request: Request,
    session: SessionDependency,
) -> JSONResponse:
    body = await _request_body(request)
    result = await MockServiceManager(session).dispatch(
        MockDispatchRequest(
            slug=slug,
            method=request.method,
            path=f"/{path}" if path else "/",
            query=dict(request.query_params),
            headers=dict(request.headers),
            body=body,
        )
    )
    return JSONResponse(
        status_code=result.status_code,
        headers=result.headers,
        content=result.body,
    )


async def _request_body(request: Request) -> JsonValue:
    content = await request.body()
    if len(content) > settings.inline_body_limit_bytes:
        raise AppError(
            code="MOCK_REQUEST_TOO_LARGE",
            message="Mock 请求超过 2 MB 上限",
            status_code=413,
        )
    if not content:
        return None
    if "application/json" not in request.headers.get("content-type", "").lower():
        return content.decode(errors="replace")
    try:
        return cast(JsonValue, json.loads(content))
    except json.JSONDecodeError as error:
        raise AppError(
            code="INVALID_JSON", message="Mock 请求 JSON 无效", status_code=422
        ) from error
