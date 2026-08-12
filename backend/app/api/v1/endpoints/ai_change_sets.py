from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import AIJobQueue, CurrentUser, SessionDependency
from app.models.ai import AIChangeItem, AIChangeSet
from app.schemas.ai_change_sets import (
    AIChangeItemResponse,
    AIChangeItemReview,
    AIChangeSetCreate,
    AIChangeSetDetailResponse,
    AIChangeSetSummaryResponse,
)
from app.schemas.common import Page
from app.services.ai_change_sets import AIChangeSetService

router = APIRouter(prefix="/ai/change-sets")


@router.post(
    "",
    response_model=AIChangeSetSummaryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_ai_change_set(
    payload: AIChangeSetCreate,
    session: SessionDependency,
    current_user: CurrentUser,
    dispatcher: AIJobQueue,
) -> AIChangeSetSummaryResponse:
    change_set = await AIChangeSetService(session).create(
        actor=current_user, payload=payload, dispatcher=dispatcher
    )
    return AIChangeSetSummaryResponse.model_validate(change_set)


@router.get("", response_model=Page[AIChangeSetSummaryResponse])
async def list_ai_change_sets(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[AIChangeSetSummaryResponse]:
    items, total = await AIChangeSetService(session).list_change_sets(
        actor=current_user, project_id=project_id, page=page, page_size=page_size
    )
    return Page(
        items=[AIChangeSetSummaryResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{change_set_id}", response_model=AIChangeSetDetailResponse)
async def get_ai_change_set(
    change_set_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> AIChangeSetDetailResponse:
    change_set, items = await AIChangeSetService(session).get(
        actor=current_user, change_set_id=change_set_id
    )
    return _detail(change_set, items)


@router.post(
    "/{change_set_id}/items/{item_id}/{decision}",
    response_model=AIChangeItemResponse,
)
async def review_ai_change_item(
    change_set_id: UUID,
    item_id: UUID,
    decision: Literal["accept", "reject"],
    payload: AIChangeItemReview,
    session: SessionDependency,
    current_user: CurrentUser,
) -> AIChangeItemResponse:
    _, item = await AIChangeSetService(session).review_item(
        actor=current_user,
        change_set_id=change_set_id,
        item_id=item_id,
        accept=decision == "accept",
        edited_content=payload.content,
        note=payload.note,
    )
    return AIChangeItemResponse.model_validate(item)


def _detail(change_set: AIChangeSet, items: list[AIChangeItem]) -> AIChangeSetDetailResponse:
    summary = AIChangeSetSummaryResponse.model_validate(change_set)
    return AIChangeSetDetailResponse(
        **summary.model_dump(),
        source_snapshot=change_set.source_snapshot,
        items=[AIChangeItemResponse.model_validate(item) for item in items],
    )
