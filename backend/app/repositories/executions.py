from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.executions import APICallExecution, AssertionResult


class ExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: APICallExecution | AssertionResult) -> None:
        self._session.add(entity)

    async def get(self, execution_id: UUID) -> APICallExecution | None:
        return await self._session.get(APICallExecution, execution_id)

    async def list_for_project(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[APICallExecution], int]:
        executions = list(
            (
                await self._session.scalars(
                    select(APICallExecution)
                    .where(APICallExecution.project_id == project_id)
                    .order_by(APICallExecution.started_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count())
            .select_from(APICallExecution)
            .where(APICallExecution.project_id == project_id)
        )
        return executions, int(total or 0)

    async def list_assertions(self, execution_id: UUID) -> list[AssertionResult]:
        return list(
            (
                await self._session.scalars(
                    select(AssertionResult)
                    .where(AssertionResult.execution_id == execution_id)
                    .order_by(AssertionResult.created_at)
                )
            ).all()
        )
