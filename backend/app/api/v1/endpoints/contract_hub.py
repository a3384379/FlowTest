from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    CurrentUser,
    PactBroker,
    ProviderVerifier,
    SessionDependency,
)
from app.core.config import settings
from app.schemas.common import Page
from app.schemas.contract_hub import (
    CompatibilityMatrixResponse,
    ContractHubSummaryResponse,
    DeploymentCheckRequest,
    DeploymentCheckResponse,
    PactBrokerImportRequest,
    PactContractResponse,
    ProviderVerificationRequest,
    ProviderVerificationResponse,
    ServiceCatalogCreate,
    ServiceCatalogResponse,
    ServiceGraphResponse,
)
from app.services.contract_hub import ContractHubService, pact_response

router = APIRouter(prefix="/projects/{project_id}/contract-hub")


@router.post(
    "/services",
    response_model=ServiceCatalogResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_service_catalog_entry(
    project_id: UUID,
    payload: ServiceCatalogCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ServiceCatalogResponse:
    model = await _service(session).create_service(
        actor=current_user,
        project_id=project_id,
        payload=payload,
    )
    return ServiceCatalogResponse.model_validate(model)


@router.get("/services", response_model=Page[ServiceCatalogResponse])
async def list_service_catalog_entries(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
) -> Page[ServiceCatalogResponse]:
    models = await _service(session).list_services(actor=current_user, project_id=project_id)
    start = (page - 1) * page_size
    return Page(
        items=[
            ServiceCatalogResponse.model_validate(item)
            for item in models[start : start + page_size]
        ],
        total=len(models),
        page=page,
        page_size=page_size,
    )


@router.post(
    "/pacts",
    response_model=PactContractResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_pact_contract(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    document: Annotated[UploadFile, File()],
    consumer_version: Annotated[str, Form(min_length=1, max_length=120)],
    source_name: Annotated[str | None, Form(max_length=255)] = None,
) -> PactContractResponse:
    content = await document.read(5 * 1024 * 1024 + 1)
    view = await _service(session).import_pact(
        actor=current_user,
        project_id=project_id,
        consumer_version=consumer_version,
        source_name=source_name or document.filename or "pact.json",
        source_type="upload",
        content=content,
    )
    return pact_response(view)


@router.post(
    "/pacts/import-broker",
    response_model=PactContractResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_pact_from_broker(
    project_id: UUID,
    payload: PactBrokerImportRequest,
    session: SessionDependency,
    current_user: CurrentUser,
    broker: PactBroker,
) -> PactContractResponse:
    view = await _service(session).import_from_broker(
        actor=current_user,
        project_id=project_id,
        consumer=payload.consumer,
        provider=payload.provider,
        consumer_version=payload.consumer_version,
        broker=broker,
    )
    return pact_response(view)


@router.get("/pacts", response_model=Page[PactContractResponse])
async def list_pact_contracts(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> Page[PactContractResponse]:
    views = await _service(session).list_pacts(actor=current_user, project_id=project_id)
    start = (page - 1) * page_size
    return Page(
        items=[pact_response(item) for item in views[start : start + page_size]],
        total=len(views),
        page=page,
        page_size=page_size,
    )


@router.post(
    "/pacts/{pact_id}/verify",
    response_model=ProviderVerificationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def verify_pact_provider(
    project_id: UUID,
    pact_id: UUID,
    payload: ProviderVerificationRequest,
    session: SessionDependency,
    current_user: CurrentUser,
    verifier: ProviderVerifier,
) -> ProviderVerificationResponse:
    model = await _service(session).verify_provider(
        actor=current_user,
        project_id=project_id,
        pact_id=pact_id,
        provider_version=payload.provider_version,
        target_base_url=payload.target_base_url,
        verifier=verifier,
    )
    return ProviderVerificationResponse.model_validate(model)


@router.get("/summary", response_model=ContractHubSummaryResponse)
async def get_contract_hub_summary(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ContractHubSummaryResponse:
    return await _service(session).summary(actor=current_user, project_id=project_id)


@router.get("/service-graph", response_model=ServiceGraphResponse)
async def get_service_dependency_graph(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ServiceGraphResponse:
    return await _service(session).service_graph(actor=current_user, project_id=project_id)


@router.get(
    "/compatibility/{provider_service_id}",
    response_model=CompatibilityMatrixResponse,
)
async def get_deployment_compatibility_matrix(
    project_id: UUID,
    provider_service_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> CompatibilityMatrixResponse:
    return await _service(session).compatibility_matrix(
        actor=current_user,
        project_id=project_id,
        provider_service_id=provider_service_id,
    )


@router.post(
    "/deployment-checks",
    response_model=DeploymentCheckResponse,
    status_code=status.HTTP_201_CREATED,
)
async def run_deployment_compatibility_check(
    project_id: UUID,
    payload: DeploymentCheckRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> DeploymentCheckResponse:
    model = await _service(session).deployment_check(
        actor=current_user,
        project_id=project_id,
        provider_service_id=payload.provider_service_id,
        provider_version=payload.provider_version,
    )
    return DeploymentCheckResponse.model_validate(model)


@router.get("/deployment-checks", response_model=Page[DeploymentCheckResponse])
async def list_deployment_compatibility_checks(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[DeploymentCheckResponse]:
    items, total = await _service(session).list_deployment_checks(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[DeploymentCheckResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def _service(session: AsyncSession) -> ContractHubService:
    return ContractHubService(
        session,
        enabled=settings.feature_contract_hub_enabled,
        broker_available=bool(settings.pact_broker_base_url),
    )
