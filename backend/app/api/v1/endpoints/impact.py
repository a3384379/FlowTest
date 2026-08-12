from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.config import settings
from app.repositories.impact import ImpactRunBundle
from app.schemas.common import Page
from app.schemas.impact import (
    CoverageSnapshotResponse,
    ImpactCatalogItem,
    ImpactCatalogResponse,
    ImpactMappingCreate,
    ImpactMappingResponse,
    ImpactRunCreate,
    ImpactRunDetailResponse,
    ImpactRunSummaryResponse,
    ImpactSchemaCatalogItem,
    TestSelectionResponse,
)
from app.services.impact import ImpactMappingView, ImpactService

router = APIRouter(prefix="/projects/{project_id}/impact")


@router.post(
    "/mappings",
    response_model=ImpactMappingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_impact_mapping(
    project_id: UUID,
    payload: ImpactMappingCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ImpactMappingResponse:
    view = await _service(session).create_mapping(
        actor=current_user,
        project_id=project_id,
        source_kind=payload.source_kind,
        source_selector=payload.source_selector,
        target_type=payload.target_type,
        target_id=payload.target_id,
    )
    return mapping_response(view)


@router.get("/mappings", response_model=Page[ImpactMappingResponse])
async def list_impact_mappings(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
) -> Page[ImpactMappingResponse]:
    views, total = await _service(session).list_mappings(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[mapping_response(view) for view in views],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete("/mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_impact_mapping(
    project_id: UUID,
    mapping_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> Response:
    await _service(session).delete_mapping(
        actor=current_user, project_id=project_id, mapping_id=mapping_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/catalog", response_model=ImpactCatalogResponse)
async def get_impact_catalog(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ImpactCatalogResponse:
    view = await _service(session).catalog(actor=current_user, project_id=project_id)
    return ImpactCatalogResponse(
        targets=[
            ImpactCatalogItem(
                id=item.id,
                target_type=item.target_type.value,
                name=item.name,
                version=item.version,
            )
            for item in view.targets
        ],
        schemas=[
            ImpactSchemaCatalogItem(
                id=item.id,
                protocol=cast(Literal["graphql", "grpc"], item.protocol),
                name=item.name,
                version=item.version,
            )
            for item in view.schemas
        ],
    )


@router.post("/runs", response_model=ImpactRunDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_impact_run(
    project_id: UUID,
    payload: ImpactRunCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ImpactRunDetailResponse:
    bundle = await _service(session).create_run(
        actor=current_user, project_id=project_id, payload=payload
    )
    return impact_run_response(bundle)


@router.get("/runs", response_model=Page[ImpactRunSummaryResponse])
async def list_impact_runs(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[ImpactRunSummaryResponse]:
    models, total = await _service(session).list_runs(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[ImpactRunSummaryResponse.model_validate(item) for item in models],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/runs/{run_id}", response_model=ImpactRunDetailResponse)
async def get_impact_run(
    project_id: UUID,
    run_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ImpactRunDetailResponse:
    bundle = await _service(session).get_run(
        actor=current_user, project_id=project_id, run_id=run_id
    )
    return impact_run_response(bundle)


def mapping_response(view: ImpactMappingView) -> ImpactMappingResponse:
    model = view.model
    return ImpactMappingResponse(
        id=model.id,
        project_id=model.project_id,
        source_kind=cast(Literal["git", "openapi", "graphql", "grpc"], model.source_kind),
        source_selector=model.source_selector,
        target_type=view.target.target_type.value,
        target_id=view.target.id,
        target_name=view.target.name,
        target_version=view.target.version,
        created_by_id=model.created_by_id,
        created_at=model.created_at,
    )


def impact_run_response(bundle: ImpactRunBundle) -> ImpactRunDetailResponse:
    run = bundle.run
    selection = bundle.selection
    coverage = bundle.coverage
    return ImpactRunDetailResponse(
        id=run.id,
        project_id=run.project_id,
        title=run.title,
        source_ref=run.source_ref,
        status=cast(Literal["completed", "failed"], run.status),
        source_fingerprint=run.source_fingerprint,
        source_summary=cast(dict[str, JsonValue], run.source_summary),
        change_count=run.change_count,
        summary=cast(dict[str, JsonValue], run.summary),
        created_by_id=run.created_by_id,
        created_at=run.created_at,
        changes=cast(list[dict[str, JsonValue]], run.changes),
        graph=cast(dict[str, JsonValue], run.graph),
        selection=TestSelectionResponse(
            id=selection.id,
            strategy=selection.strategy,
            selected_assets=cast(list[dict[str, JsonValue]], selection.selected_assets),
            explanations=cast(list[dict[str, JsonValue]], selection.explanations),
            created_at=selection.created_at,
        ),
        coverage=CoverageSnapshotResponse(
            id=coverage.id,
            total_changes=coverage.total_changes,
            covered_changes=coverage.covered_changes,
            coverage_percent=coverage.coverage_percent,
            matrix=cast(list[dict[str, JsonValue]], coverage.matrix),
            gaps=cast(list[dict[str, JsonValue]], coverage.gaps),
            created_at=coverage.created_at,
        ),
    )


def _service(session: AsyncSession) -> ImpactService:
    return ImpactService(session, enabled=settings.feature_impact_engine_enabled)
