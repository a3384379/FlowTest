from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import AIJobQueue, CurrentUser, SessionDependency
from app.core.config import settings
from app.schemas.ai import (
    AIJobCreateRequest,
    AIJobResponse,
    AIProjectSettingsRequest,
    AIStatusResponse,
    AISuggestionResponse,
    AISuggestionReviewRequest,
)
from app.schemas.ai_sources import AIPublicSource, AISourceKind, AISourceSummary
from app.schemas.common import Page
from app.services.ai import AIJobService
from app.services.ai_sources import AISourceService

router = APIRouter(prefix="/ai")


@router.get("/projects/{project_id}/sources", response_model=Page[AISourceSummary])
async def list_public_ai_sources(
    project_id: UUID,
    kind: AISourceKind,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default="", max_length=200),
) -> Page[AISourceSummary]:
    items, total = await AISourceService(session).list_sources(
        actor=current_user,
        project_id=project_id,
        kind=kind,
        page=page,
        page_size=page_size,
        search=search,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/projects/{project_id}/sources/{kind}/{source_id}", response_model=AIPublicSource)
async def read_public_ai_source(
    project_id: UUID,
    kind: AISourceKind,
    source_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    version: int | None = Query(default=None, ge=1),
) -> AIPublicSource:
    return await AISourceService(session).read_source(
        actor=current_user, project_id=project_id, kind=kind, source_id=source_id, version=version
    )


@router.get("/status", response_model=AIStatusResponse)
async def get_ai_status(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> AIStatusResponse:
    enabled, model, sample_sharing = await AIJobService(session).status(
        actor=current_user, project_id=project_id
    )
    return AIStatusResponse(
        enabled=enabled,
        model=model,
        sample_sharing_enabled=sample_sharing,
    )


@router.put("/projects/{project_id}/settings", response_model=AIStatusResponse)
async def update_ai_project_settings(
    project_id: UUID,
    payload: AIProjectSettingsRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> AIStatusResponse:
    sharing = await AIJobService(session).update_sample_sharing(
        actor=current_user,
        project_id=project_id,
        enabled=payload.sample_sharing_enabled,
    )
    return AIStatusResponse(
        enabled=settings.feature_ai_enabled,
        model=settings.ai_model or None,
        sample_sharing_enabled=sharing,
    )


@router.post("/jobs", response_model=AIJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_ai_job(
    payload: AIJobCreateRequest,
    session: SessionDependency,
    current_user: CurrentUser,
    dispatcher: AIJobQueue,
) -> AIJobResponse:
    job = await AIJobService(session).create(
        actor=current_user,
        payload=payload,
        dispatcher=dispatcher,
    )
    return AIJobResponse.model_validate(job)


@router.get("/jobs", response_model=Page[AIJobResponse])
async def list_ai_jobs(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[AIJobResponse]:
    items, total = await AIJobService(session).list_jobs(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[AIJobResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/jobs/{job_id}", response_model=AIJobResponse)
async def get_ai_job(
    job_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> AIJobResponse:
    job = await AIJobService(session).get_job(actor=current_user, job_id=job_id)
    return AIJobResponse.model_validate(job)


@router.get("/jobs/{job_id}/suggestions", response_model=list[AISuggestionResponse])
async def list_ai_suggestions(
    job_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[AISuggestionResponse]:
    suggestions = await AIJobService(session).list_suggestions(actor=current_user, job_id=job_id)
    return [AISuggestionResponse.model_validate(item) for item in suggestions]


@router.post("/suggestions/{suggestion_id}/{decision}", response_model=AISuggestionResponse)
async def review_ai_suggestion(
    suggestion_id: UUID,
    decision: Literal["accept", "reject"],
    payload: AISuggestionReviewRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> AISuggestionResponse:
    suggestion = await AIJobService(session).review(
        actor=current_user,
        suggestion_id=suggestion_id,
        accept=decision == "accept",
        edited_content=payload.content,
        note=payload.note,
    )
    return AISuggestionResponse.model_validate(suggestion)
