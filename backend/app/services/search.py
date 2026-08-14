from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.access import User
from app.repositories.access import ProjectRepository
from app.repositories.search import SearchRepository, SearchRow


class SearchService:
    def __init__(self, session: AsyncSession) -> None:
        self._projects = ProjectRepository(session)
        self._search = SearchRepository(session)

    async def search(
        self,
        *,
        actor: User,
        query: str,
        project_id: UUID | None,
        page: int,
        page_size: int,
    ) -> tuple[list[SearchRow], int]:
        normalized = query.strip()
        if len(normalized) < 2:
            raise AppError(
                code="SEARCH_QUERY_INVALID",
                message="搜索词至少需要 2 个字符",
                status_code=422,
            )
        projects, _ = await self._projects.list_for_user(
            user_id=actor.id,
            system_admin=actor.is_system_admin,
            offset=0,
            limit=10_000,
        )
        accessible_ids = {project.id for project, _role in projects}
        if project_id is not None:
            if project_id not in accessible_ids:
                raise AppError(code="PROJECT_NOT_FOUND", message="项目不存在", status_code=404)
            accessible_ids = {project_id}
        return await self._search.search(
            query=normalized,
            project_ids=accessible_ids,
            offset=(page - 1) * page_size,
            limit=page_size,
        )


def search_result_path(row: SearchRow) -> str:
    return f"/projects/{row.project_id}/{row.section}?focus={row.resource_type}:{row.resource_id}"
