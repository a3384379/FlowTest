from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tasking import ServiceToken, TestPlan, TestPlanItem, TestPlanRun, TestPlanRunItem

TaskEntity = TestPlan | TestPlanItem | TestPlanRun | TestPlanRunItem | ServiceToken


class TaskingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: TaskEntity) -> None:
        self._session.add(entity)

    def add_all(self, entities: Sequence[TaskEntity]) -> None:
        self._session.add_all(entities)

    async def delete_items(self, items: list[TestPlanItem]) -> None:
        for item in items:
            await self._session.delete(item)

    async def get_plan(self, plan_id: UUID) -> TestPlan | None:
        return await self._session.get(TestPlan, plan_id)

    async def list_plans(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[TestPlan], int]:
        query = select(TestPlan).where(TestPlan.project_id == project_id)
        items = list(
            (
                await self._session.scalars(
                    query.order_by(TestPlan.updated_at.desc()).offset(offset).limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(select(func.count()).select_from(query.subquery()))
        return items, int(total or 0)

    async def plan_name_exists(
        self, *, project_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> bool:
        query = select(TestPlan.id).where(
            TestPlan.project_id == project_id,
            TestPlan.name == name,
        )
        if excluding_id is not None:
            query = query.where(TestPlan.id != excluding_id)
        return await self._session.scalar(query) is not None

    async def list_plan_items(self, plan_id: UUID) -> list[TestPlanItem]:
        return list(
            (
                await self._session.scalars(
                    select(TestPlanItem)
                    .where(TestPlanItem.test_plan_id == plan_id)
                    .order_by(TestPlanItem.position)
                )
            ).all()
        )

    async def get_run(self, run_id: UUID) -> TestPlanRun | None:
        return await self._session.get(TestPlanRun, run_id)

    async def list_runs(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[TestPlanRun], int]:
        condition = TestPlanRun.project_id == project_id
        items = list(
            (
                await self._session.scalars(
                    select(TestPlanRun)
                    .where(condition)
                    .order_by(TestPlanRun.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(TestPlanRun).where(condition)
        )
        return items, int(total or 0)

    async def list_run_items(self, run_id: UUID) -> list[TestPlanRunItem]:
        return list(
            (
                await self._session.scalars(
                    select(TestPlanRunItem)
                    .where(TestPlanRunItem.test_plan_run_id == run_id)
                    .order_by(TestPlanRunItem.position)
                )
            ).all()
        )

    async def due_plans(self, now: datetime, limit: int = 100) -> list[TestPlan]:
        return list(
            (
                await self._session.scalars(
                    select(TestPlan)
                    .where(
                        TestPlan.enabled.is_(True),
                        TestPlan.next_run_at.is_not(None),
                        TestPlan.next_run_at <= now,
                    )
                    .order_by(TestPlan.next_run_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )

    async def find_token(self, prefix: str) -> ServiceToken | None:
        result = await self._session.execute(
            select(ServiceToken).where(ServiceToken.token_prefix == prefix)
        )
        return result.scalar_one_or_none()

    async def list_tokens(self, project_id: UUID) -> list[ServiceToken]:
        return list(
            (
                await self._session.scalars(
                    select(ServiceToken)
                    .where(ServiceToken.project_id == project_id)
                    .order_by(ServiceToken.created_at.desc())
                )
            ).all()
        )
