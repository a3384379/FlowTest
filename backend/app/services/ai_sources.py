from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.access import User
from app.repositories.ai_sources import AISourceRepository
from app.schemas.ai_sources import AIPublicSource, AISourceKind, AISourceSummary
from app.services.projects import ProjectService


class AISourceReader(Protocol):
    async def list_sources(
        self, project_id: UUID, kind: AISourceKind, page: int, page_size: int, search: str
    ) -> tuple[list[AISourceSummary], int]: ...

    async def read_source(
        self, project_id: UUID, kind: AISourceKind, source_id: UUID, version: int | None
    ) -> AIPublicSource | None: ...


class AISourceService:
    def __init__(self, session: AsyncSession, reader: AISourceReader | None = None) -> None:
        self._projects = ProjectService(session)
        self._reader = reader if reader is not None else AISourceRepository(session)

    async def list_sources(
        self,
        *,
        actor: User,
        project_id: UUID,
        kind: AISourceKind,
        page: int,
        page_size: int,
        search: str,
    ) -> tuple[list[AISourceSummary], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._reader.list_sources(project_id, kind, page, page_size, search.strip())

    async def read_source(
        self,
        *,
        actor: User,
        project_id: UUID,
        kind: AISourceKind,
        source_id: UUID,
        version: int | None,
    ) -> AIPublicSource:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        source = await self._reader.read_source(project_id, kind, source_id, version)
        if source is None or (version is not None and source.metadata.version != version):
            raise AppError(
                code="AI_SOURCE_NOT_FOUND", message="公开材料来源或固定版本不存在", status_code=404
            )
        if len(source.model_dump_json().encode("utf-8")) > 1024 * 1024:
            raise AppError(
                code="AI_SOURCE_TOO_LARGE",
                message="公开材料超过 1 MB。请缩小来源或手动选择材料",
                status_code=413,
            )
        return source
