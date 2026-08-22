from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AIChangeItem, AIChangeSet
from app.models.change_regression import ChangeRegressionRun, ChangeRegressionStage
from app.models.release_gate import ReleaseDecision
from app.models.tasking import TestPlanRun


@dataclass(frozen=True, slots=True)
class ChangeRegressionBundle:
    run: ChangeRegressionRun
    stages: list[ChangeRegressionStage]
    change_set: AIChangeSet | None
    change_items: list[AIChangeItem]
    test_plan_run: TestPlanRun | None
    release_decision: ReleaseDecision | None


class ChangeRegressionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add_run(self, run: ChangeRegressionRun) -> None:
        self._session.add(run)

    def add_stage(self, stage: ChangeRegressionStage) -> None:
        self._session.add(stage)

    async def get_run(self, run_id: UUID) -> ChangeRegressionRun | None:
        return await self._session.get(ChangeRegressionRun, run_id)

    async def get_run_for_update(self, run_id: UUID) -> ChangeRegressionRun | None:
        return (
            await self._session.execute(
                select(ChangeRegressionRun)
                .where(ChangeRegressionRun.id == run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def list_runs(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[ChangeRegressionRun], int]:
        condition = ChangeRegressionRun.project_id == project_id
        items = list(
            (
                await self._session.scalars(
                    select(ChangeRegressionRun)
                    .where(condition)
                    .order_by(ChangeRegressionRun.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(ChangeRegressionRun).where(condition)
        )
        return items, int(total or 0)

    async def list_stages(self, run_id: UUID) -> list[ChangeRegressionStage]:
        return list(
            (
                await self._session.scalars(
                    select(ChangeRegressionStage)
                    .where(ChangeRegressionStage.regression_run_id == run_id)
                    .order_by(ChangeRegressionStage.sequence)
                )
            ).all()
        )

    async def next_stage_sequence(self, run_id: UUID) -> int:
        current = await self._session.scalar(
            select(func.max(ChangeRegressionStage.sequence)).where(
                ChangeRegressionStage.regression_run_id == run_id
            )
        )
        return int(current or 0) + 1

    async def get_bundle(self, run_id: UUID) -> ChangeRegressionBundle | None:
        run = await self.get_run(run_id)
        if run is None:
            return None
        await self._session.refresh(run)
        stages = await self.list_stages(run_id)
        change_set = (
            await self._session.get(AIChangeSet, run.change_set_id)
            if run.change_set_id is not None
            else None
        )
        change_items = (
            list(
                (
                    await self._session.scalars(
                        select(AIChangeItem)
                        .where(AIChangeItem.change_set_id == run.change_set_id)
                        .order_by(AIChangeItem.position)
                    )
                ).all()
            )
            if run.change_set_id is not None
            else []
        )
        test_plan_run = (
            await self._session.get(TestPlanRun, run.test_plan_run_id)
            if run.test_plan_run_id is not None
            else None
        )
        release_decision = (
            await self._session.get(ReleaseDecision, run.release_decision_id)
            if run.release_decision_id is not None
            else None
        )
        return ChangeRegressionBundle(
            run=run,
            stages=stages,
            change_set=change_set,
            change_items=change_items,
            test_plan_run=test_plan_run,
            release_decision=release_decision,
        )
