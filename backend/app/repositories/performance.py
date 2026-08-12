from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.performance import (
    PerformanceGateEvaluation,
    PerformanceRun,
    PerformanceScenario,
)
from app.models.quality import QualityGate

PerformanceEntity = PerformanceScenario | PerformanceRun | PerformanceGateEvaluation


class PerformanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: PerformanceEntity) -> None:
        self._session.add(entity)

    async def get_scenario(self, scenario_id: UUID) -> PerformanceScenario | None:
        return await self._session.get(PerformanceScenario, scenario_id)

    async def get_scenario_for_update(self, scenario_id: UUID) -> PerformanceScenario | None:
        result = await self._session.execute(
            select(PerformanceScenario)
            .where(PerformanceScenario.id == scenario_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def latest_version(self, *, project_id: UUID, name: str) -> int:
        value = await self._session.scalar(
            select(func.max(PerformanceScenario.version)).where(
                PerformanceScenario.project_id == project_id,
                PerformanceScenario.name == name,
            )
        )
        return int(value or 0)

    async def list_scenarios(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[PerformanceScenario], int]:
        condition = PerformanceScenario.project_id == project_id
        items = list(
            (
                await self._session.scalars(
                    select(PerformanceScenario)
                    .where(condition)
                    .order_by(
                        PerformanceScenario.name,
                        PerformanceScenario.version.desc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(PerformanceScenario).where(condition)
        )
        return items, int(total or 0)

    async def get_run(self, run_id: UUID) -> PerformanceRun | None:
        return await self._session.get(PerformanceRun, run_id)

    async def get_run_for_update(self, run_id: UUID) -> PerformanceRun | None:
        result = await self._session.execute(
            select(PerformanceRun).where(PerformanceRun.id == run_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_runs(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[PerformanceRun], int]:
        condition = PerformanceRun.project_id == project_id
        items = list(
            (
                await self._session.scalars(
                    select(PerformanceRun)
                    .where(condition)
                    .order_by(PerformanceRun.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(PerformanceRun).where(condition)
        )
        return items, int(total or 0)

    async def previous_completed_run(self, run: PerformanceRun) -> PerformanceRun | None:
        result = await self._session.execute(
            select(PerformanceRun)
            .where(
                PerformanceRun.scenario_id == run.scenario_id,
                PerformanceRun.id != run.id,
                PerformanceRun.status.in_(("passed", "failed")),
                PerformanceRun.completed_at.is_not(None),
                PerformanceRun.created_at < run.created_at,
            )
            .order_by(PerformanceRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def enabled_gates(self, project_id: UUID) -> list[QualityGate]:
        return list(
            (
                await self._session.scalars(
                    select(QualityGate).where(
                        QualityGate.project_id == project_id,
                        QualityGate.enabled.is_(True),
                    )
                )
            ).all()
        )

    async def list_evaluations(self, run_id: UUID) -> list[PerformanceGateEvaluation]:
        return list(
            (
                await self._session.scalars(
                    select(PerformanceGateEvaluation)
                    .where(PerformanceGateEvaluation.performance_run_id == run_id)
                    .order_by(PerformanceGateEvaluation.evaluated_at)
                )
            ).all()
        )
