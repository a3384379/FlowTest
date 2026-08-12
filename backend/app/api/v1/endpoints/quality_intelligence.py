from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.models.quality_intelligence import FailureCluster, ReleaseRisk
from app.schemas.common import Page
from app.schemas.quality_intelligence import (
    FailureClusterResponse,
    ReleaseRiskCreate,
    ReleaseRiskDetailResponse,
    ReleaseRiskSummaryResponse,
)
from app.services.quality_intelligence import QualityIntelligenceService

router = APIRouter()


@router.post(
    "/projects/{project_id}/release-risks",
    response_model=ReleaseRiskDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_release_risk(
    project_id: UUID,
    payload: ReleaseRiskCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ReleaseRiskDetailResponse:
    risk, clusters = await QualityIntelligenceService(session).create_risk(
        actor=current_user, project_id=project_id, payload=payload
    )
    return _detail(risk, clusters)


@router.get(
    "/projects/{project_id}/release-risks",
    response_model=Page[ReleaseRiskSummaryResponse],
)
async def list_release_risks(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[ReleaseRiskSummaryResponse]:
    items, total = await QualityIntelligenceService(session).list_risks(
        actor=current_user, project_id=project_id, page=page, page_size=page_size
    )
    return Page(
        items=[ReleaseRiskSummaryResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/projects/{project_id}/release-risks/{risk_id}",
    response_model=ReleaseRiskDetailResponse,
)
async def get_release_risk(
    project_id: UUID,
    risk_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ReleaseRiskDetailResponse:
    risk, clusters = await QualityIntelligenceService(session).get_risk(
        actor=current_user, project_id=project_id, risk_id=risk_id
    )
    return _detail(risk, clusters)


@router.get(
    "/projects/{project_id}/failure-clusters",
    response_model=list[FailureClusterResponse],
)
async def list_failure_clusters(
    project_id: UUID,
    release_risk_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[FailureClusterResponse]:
    clusters = await QualityIntelligenceService(session).list_clusters(
        actor=current_user, project_id=project_id, risk_id=release_risk_id
    )
    return [FailureClusterResponse.model_validate(item) for item in clusters]


def _detail(risk: ReleaseRisk, clusters: list[FailureCluster]) -> ReleaseRiskDetailResponse:
    summary = ReleaseRiskSummaryResponse.model_validate(risk)
    return ReleaseRiskDetailResponse(
        **summary.model_dump(),
        window_started_at=risk.window_started_at,
        window_ended_at=risk.window_ended_at,
        baseline_started_at=risk.baseline_started_at,
        baseline_ended_at=risk.baseline_ended_at,
        factors=risk.factors,
        evidence_snapshot=risk.evidence_snapshot,
        quality_trend=risk.quality_trend,
        recommended_tests=risk.recommended_tests,
        failure_clusters=[FailureClusterResponse.model_validate(item) for item in clusters],
    )
