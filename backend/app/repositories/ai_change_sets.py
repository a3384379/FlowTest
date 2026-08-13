from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AIChangeItem, AIChangeSet
from app.models.quality_intelligence import ReleaseRisk
from app.models.test_assets import TestCase
from app.models.workflows import Workflow


class AIChangeSetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add_change_set(self, change_set: AIChangeSet) -> None:
        self._session.add(change_set)

    def add_items(self, items: list[AIChangeItem]) -> None:
        self._session.add_all(items)

    async def get_change_set(self, change_set_id: UUID) -> AIChangeSet | None:
        return await self._session.get(AIChangeSet, change_set_id)

    async def get_change_set_for_update(self, change_set_id: UUID) -> AIChangeSet | None:
        return (
            await self._session.execute(
                select(AIChangeSet).where(AIChangeSet.id == change_set_id).with_for_update()
            )
        ).scalar_one_or_none()

    async def get_change_set_by_job_for_update(self, job_id: UUID) -> AIChangeSet | None:
        return (
            await self._session.execute(
                select(AIChangeSet).where(AIChangeSet.ai_job_id == job_id).with_for_update()
            )
        ).scalar_one_or_none()

    async def list_change_sets(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[AIChangeSet], int]:
        condition = AIChangeSet.project_id == project_id
        items = list(
            (
                await self._session.scalars(
                    select(AIChangeSet)
                    .where(condition)
                    .order_by(AIChangeSet.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(AIChangeSet).where(condition)
        )
        return items, int(total or 0)

    async def list_items(self, change_set_id: UUID) -> list[AIChangeItem]:
        return list(
            (
                await self._session.scalars(
                    select(AIChangeItem)
                    .where(AIChangeItem.change_set_id == change_set_id)
                    .order_by(AIChangeItem.position)
                )
            ).all()
        )

    async def get_item_for_update(self, item_id: UUID) -> AIChangeItem | None:
        return (
            await self._session.execute(
                select(AIChangeItem).where(AIChangeItem.id == item_id).with_for_update()
            )
        ).scalar_one_or_none()

    async def get_risk(self, risk_id: UUID) -> ReleaseRisk | None:
        return await self._session.get(ReleaseRisk, risk_id)

    async def get_test_case(self, resource_id: UUID) -> TestCase | None:
        return await self._session.get(TestCase, resource_id)

    async def get_test_case_for_update(self, resource_id: UUID) -> TestCase | None:
        return (
            await self._session.execute(
                select(TestCase).where(TestCase.id == resource_id).with_for_update()
            )
        ).scalar_one_or_none()

    async def get_workflow(self, resource_id: UUID) -> Workflow | None:
        return await self._session.get(Workflow, resource_id)

    async def get_workflow_for_update(self, resource_id: UUID) -> Workflow | None:
        return (
            await self._session.execute(
                select(Workflow).where(Workflow.id == resource_id).with_for_update()
            )
        ).scalar_one_or_none()
