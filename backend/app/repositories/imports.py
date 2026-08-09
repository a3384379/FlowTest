from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.imports import ImportRun


class ImportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, run: ImportRun) -> None:
        self._session.add(run)

    async def get(self, run_id: UUID) -> ImportRun | None:
        return await self._session.get(ImportRun, run_id)

    async def list_for_project(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[ImportRun], int]:
        runs = list(
            (
                await self._session.scalars(
                    select(ImportRun)
                    .where(ImportRun.project_id == project_id)
                    .order_by(ImportRun.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(ImportRun).where(ImportRun.project_id == project_id)
        )
        return runs, int(total or 0)
