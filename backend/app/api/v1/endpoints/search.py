from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, SessionDependency
from app.schemas.common import Page
from app.schemas.search import SearchResultResponse
from app.services.search import SearchService, search_result_path

router = APIRouter(prefix="/search")


@router.get("", response_model=Page[SearchResultResponse])
async def global_search(
    session: SessionDependency,
    current_user: CurrentUser,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    project_id: Annotated[UUID | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> Page[SearchResultResponse]:
    rows, total = await SearchService(session).search(
        actor=current_user,
        query=q,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[
            SearchResultResponse(
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                project_id=row.project_id,
                project_name=row.project_name,
                title=row.title,
                description=row.description,
                section=row.section,
                path=search_result_path(row),
                updated_at=row.updated_at,
            )
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
