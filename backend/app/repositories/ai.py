from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AIJob, AISuggestion


class AIRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add_job(self, job: AIJob) -> None:
        self._session.add(job)

    def add_suggestions(self, suggestions: list[AISuggestion]) -> None:
        self._session.add_all(suggestions)

    async def get_job(self, job_id: UUID) -> AIJob | None:
        return await self._session.get(AIJob, job_id)

    async def get_job_for_update(self, job_id: UUID) -> AIJob | None:
        result = await self._session.execute(
            select(AIJob).where(AIJob.id == job_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_suggestion_for_update(self, suggestion_id: UUID) -> AISuggestion | None:
        result = await self._session.execute(
            select(AISuggestion).where(AISuggestion.id == suggestion_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_jobs(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[AIJob], int]:
        filters = (AIJob.project_id == project_id,)
        jobs = list(
            (
                await self._session.scalars(
                    select(AIJob)
                    .where(*filters)
                    .order_by(AIJob.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(select(func.count()).select_from(AIJob).where(*filters))
        return jobs, int(total or 0)

    async def list_suggestions(self, job_id: UUID) -> list[AISuggestion]:
        return list(
            (
                await self._session.scalars(
                    select(AISuggestion)
                    .where(AISuggestion.job_id == job_id)
                    .order_by(AISuggestion.position)
                )
            ).all()
        )
