from uuid import UUID

from fastapi import APIRouter, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.schemas.service_targets import (
    ServiceCreate,
    ServiceEndpointConnectivityResponse,
    ServiceEndpointCreate,
    ServiceEndpointResponse,
    ServiceEndpointUpdate,
    ServiceResponse,
    ServiceUpdate,
)
from app.services.service_targets import ServiceTargetService

router = APIRouter(prefix="/projects/{project_id}")


@router.get("/services", response_model=list[ServiceResponse])
async def list_services(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[ServiceResponse]:
    services = await ServiceTargetService(session).list_services(
        actor=current_user,
        project_id=project_id,
    )
    return [ServiceResponse.model_validate(service) for service in services]


@router.post("/services", response_model=ServiceResponse, status_code=status.HTTP_201_CREATED)
async def create_service(
    project_id: UUID,
    payload: ServiceCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ServiceResponse:
    service = await ServiceTargetService(session).create_service(
        actor=current_user,
        project_id=project_id,
        service_key=payload.service_key,
        name=payload.name,
        description=payload.description,
        owner_team=payload.owner_team,
        service_type=payload.service_type,
        enabled=payload.enabled,
    )
    return ServiceResponse.model_validate(service)


@router.patch("/services/{service_id}", response_model=ServiceResponse)
async def update_service(
    project_id: UUID,
    service_id: UUID,
    payload: ServiceUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ServiceResponse:
    service = await ServiceTargetService(session).update_service(
        actor=current_user,
        project_id=project_id,
        service_id=service_id,
        name=payload.name,
        description=payload.description,
        owner_team=payload.owner_team,
        service_type=payload.service_type,
        enabled=payload.enabled,
    )
    return ServiceResponse.model_validate(service)


@router.get(
    "/environments/{environment_id}/service-endpoints",
    response_model=list[ServiceEndpointResponse],
)
async def list_environment_endpoints(
    project_id: UUID,
    environment_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[ServiceEndpointResponse]:
    endpoints = await ServiceTargetService(session).list_endpoints(
        actor=current_user,
        project_id=project_id,
        environment_id=environment_id,
    )
    return [ServiceEndpointResponse.model_validate(endpoint) for endpoint in endpoints]


@router.get("/service-endpoints", response_model=list[ServiceEndpointResponse])
async def list_project_endpoints(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[ServiceEndpointResponse]:
    endpoints = await ServiceTargetService(session).list_endpoints(
        actor=current_user,
        project_id=project_id,
        environment_id=None,
    )
    return [ServiceEndpointResponse.model_validate(endpoint) for endpoint in endpoints]


@router.post(
    "/environments/{environment_id}/service-endpoints",
    response_model=ServiceEndpointResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_environment_endpoint(
    project_id: UUID,
    environment_id: UUID,
    payload: ServiceEndpointCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ServiceEndpointResponse:
    endpoint = await ServiceTargetService(session).create_endpoint(
        actor=current_user,
        project_id=project_id,
        environment_id=environment_id,
        service_id=payload.service_id,
        variant=payload.variant,
        base_url=str(payload.base_url),
        enabled=payload.enabled,
        connect_timeout_ms=payload.connect_timeout_ms,
        read_timeout_ms=payload.read_timeout_ms,
        tls_verify=payload.tls_verify,
        proxy_ref=payload.proxy_ref,
        headers=payload.headers,
        variables=payload.variables,
        secret_refs=payload.secret_refs,
        health_check_path=payload.health_check_path,
        health_expected_status=payload.health_expected_status,
    )
    return ServiceEndpointResponse.model_validate(endpoint)


@router.patch("/service-endpoints/{endpoint_id}", response_model=ServiceEndpointResponse)
async def update_endpoint(
    project_id: UUID,
    endpoint_id: UUID,
    payload: ServiceEndpointUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ServiceEndpointResponse:
    endpoint = await ServiceTargetService(session).update_endpoint(
        actor=current_user,
        project_id=project_id,
        endpoint_id=endpoint_id,
        variant=payload.variant,
        base_url=str(payload.base_url) if payload.base_url is not None else None,
        enabled=payload.enabled,
        connect_timeout_ms=payload.connect_timeout_ms,
        read_timeout_ms=payload.read_timeout_ms,
        tls_verify=payload.tls_verify,
        proxy_ref=payload.proxy_ref,
        headers=payload.headers,
        variables=payload.variables,
        secret_refs=payload.secret_refs,
        health_check_path=payload.health_check_path,
        health_expected_status=payload.health_expected_status,
        changed_fields=payload.model_fields_set,
    )
    return ServiceEndpointResponse.model_validate(endpoint)


@router.post(
    "/service-endpoints/{endpoint_id}/connectivity",
    response_model=ServiceEndpointConnectivityResponse,
)
async def check_endpoint_connectivity(
    project_id: UUID,
    endpoint_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ServiceEndpointConnectivityResponse:
    result = await ServiceTargetService(session).check_connectivity(
        actor=current_user,
        project_id=project_id,
        endpoint_id=endpoint_id,
    )
    return ServiceEndpointConnectivityResponse.model_validate(result)
