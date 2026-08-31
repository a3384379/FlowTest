"""Project-facing read-only Context Inspector endpoints."""

from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, SessionDependency
from app.schemas.common import Page
from app.schemas.context_inspector import ContextInspectorDetail, ContextInspectorSummary
from app.services.context_inspector import ContextInspectorService

router = APIRouter(prefix="/projects/{project_id}/contexts")


@router.get("", response_model=Page[ContextInspectorSummary])
async def list_contexts(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[ContextInspectorSummary]:
    items, total = await ContextInspectorService(session).list_contexts(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{context_id}", response_model=ContextInspectorDetail)
async def get_context(
    project_id: UUID,
    context_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ContextInspectorDetail:
    return await ContextInspectorService(session).get_context(
        actor=current_user,
        project_id=project_id,
        context_id=context_id,
    )
