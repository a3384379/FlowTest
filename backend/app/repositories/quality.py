from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contracts import ContractRun
from app.models.quality import FlakyRecord, QualityGate, QualityGateEvaluation
from app.models.tasking import TestPlanRun

QualityEntity = QualityGate | FlakyRecord | QualityGateEvaluation


@dataclass(frozen=True)
class FlakySummary:
    asset_total: int
    record_total: int
    flaky_total: int
    flaky_version_total: int
    quarantined_total: int
    quarantined_version_total: int
    oldest_updated_at: datetime | None
    latest_updated_at: datetime | None


class QualityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: QualityEntity) -> None:
        self._session.add(entity)

    async def list_gates(self, project_id: UUID) -> list[QualityGate]:
        return list(
            (
                await self._session.scalars(
                    select(QualityGate)
                    .where(QualityGate.project_id == project_id)
                    .order_by(QualityGate.created_at)
                )
            ).all()
        )

    async def get_gate(self, gate_id: UUID) -> QualityGate | None:
        return await self._session.get(QualityGate, gate_id)

    async def gate_name_exists(
        self, *, project_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> bool:
        query = select(QualityGate.id).where(
            QualityGate.project_id == project_id,
            QualityGate.name == name,
        )
        if excluding_id is not None:
            query = query.where(QualityGate.id != excluding_id)
        return await self._session.scalar(query) is not None

    async def list_flaky_records(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[FlakyRecord], int]:
        condition = FlakyRecord.project_id == project_id
        items = list(
            (
                await self._session.scalars(
                    select(FlakyRecord)
                    .where(condition)
                    .order_by(
                        FlakyRecord.flaky_score.desc(),
                        FlakyRecord.updated_at.desc(),
                        FlakyRecord.id.asc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(FlakyRecord).where(condition)
        )
        return items, int(total or 0)

    async def summarize_flaky_records(self, project_id: UUID) -> FlakySummary:
        positive = case((FlakyRecord.flaky_score > 0, 1), else_=0)
        isolated = case((FlakyRecord.quarantined.is_(True), 1), else_=0)
        assets = (
            select(
                func.count().label("versions"),
                func.max(positive).label("flaky"),
                func.sum(positive).label("flaky_versions"),
                func.max(isolated).label("isolated"),
                func.sum(isolated).label("isolated_versions"),
                func.min(FlakyRecord.updated_at).label("oldest"),
                func.max(FlakyRecord.updated_at).label("latest"),
            )
            .where(FlakyRecord.project_id == project_id)
            .group_by(FlakyRecord.target_type, FlakyRecord.target_id)
            .subquery()
        )
        row = (
            await self._session.execute(
                select(
                    func.count().label("asset_total"),
                    func.sum(assets.c.versions).label("record_total"),
                    func.sum(assets.c.flaky).label("flaky_total"),
                    func.sum(assets.c.flaky_versions).label("flaky_version_total"),
                    func.sum(assets.c.isolated).label("quarantined_total"),
                    func.sum(assets.c.isolated_versions).label("quarantined_version_total"),
                    func.min(assets.c.oldest).label("oldest_updated_at"),
                    func.max(assets.c.latest).label("latest_updated_at"),
                ).select_from(assets)
            )
        ).one()
        return FlakySummary(
            asset_total=int(row.asset_total or 0),
            record_total=int(row.record_total or 0),
            flaky_total=int(row.flaky_total or 0),
            flaky_version_total=int(row.flaky_version_total or 0),
            quarantined_total=int(row.quarantined_total or 0),
            quarantined_version_total=int(row.quarantined_version_total or 0),
            oldest_updated_at=row.oldest_updated_at,
            latest_updated_at=row.latest_updated_at,
        )

    async def get_flaky_record(self, record_id: UUID) -> FlakyRecord | None:
        return await self._session.get(FlakyRecord, record_id)

    async def find_flaky_record(
        self, *, project_id: UUID, target_type: str, target_id: UUID, target_version: int
    ) -> FlakyRecord | None:
        result = await self._session.execute(
            select(FlakyRecord)
            .where(
                FlakyRecord.project_id == project_id,
                FlakyRecord.target_type == target_type,
                FlakyRecord.target_id == target_id,
                FlakyRecord.target_version == target_version,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def ensure_flaky_record(
        self, *, project_id: UUID, target_type: str, target_id: UUID, target_version: int
    ) -> FlakyRecord:
        values = {
            "project_id": project_id,
            "target_type": target_type,
            "target_id": target_id,
            "target_version": target_version,
            "total_runs": 0,
            "passed_runs": 0,
            "failed_runs": 0,
            "transitions": 0,
            "flaky_score": 0,
            "quarantined": False,
            "last_status": None,
            "last_run_id": None,
            "last_run_at": None,
        }
        bind = self._session.get_bind()
        constraint = ["project_id", "target_type", "target_id", "target_version"]
        if bind.dialect.name == "postgresql":
            await self._session.execute(
                postgres_insert(FlakyRecord)
                .values(**values)
                .on_conflict_do_nothing(index_elements=constraint)
            )
        else:
            await self._session.execute(
                sqlite_insert(FlakyRecord)
                .values(**values)
                .on_conflict_do_nothing(index_elements=constraint)
            )
        record = await self.find_flaky_record(
            project_id=project_id,
            target_type=target_type,
            target_id=target_id,
            target_version=target_version,
        )
        if record is None:
            raise RuntimeError("failed to create Flaky record")
        return record

    async def list_evaluations(self, run_id: UUID) -> list[QualityGateEvaluation]:
        return list(
            (
                await self._session.scalars(
                    select(QualityGateEvaluation)
                    .where(QualityGateEvaluation.test_plan_run_id == run_id)
                    .order_by(QualityGateEvaluation.evaluated_at)
                )
            ).all()
        )

    async def find_evaluation(self, *, gate_id: UUID, run_id: UUID) -> QualityGateEvaluation | None:
        result = await self._session.execute(
            select(QualityGateEvaluation).where(
                QualityGateEvaluation.quality_gate_id == gate_id,
                QualityGateEvaluation.test_plan_run_id == run_id,
            )
        )
        return result.scalar_one_or_none()

    async def previous_completed_run(self, run: TestPlanRun) -> TestPlanRun | None:
        result = await self._session.execute(
            select(TestPlanRun)
            .where(
                TestPlanRun.project_id == run.project_id,
                TestPlanRun.test_plan_id == run.test_plan_id,
                TestPlanRun.id != run.id,
                TestPlanRun.status.in_(("passed", "failed")),
                TestPlanRun.completed_at.is_not(None),
                TestPlanRun.created_at < run.created_at,
            )
            .order_by(TestPlanRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def latest_breaking_change_count(self, project_id: UUID) -> int:
        result = await self._session.execute(
            select(ContractRun.breaking_changes)
            .where(ContractRun.project_id == project_id, ContractRun.status == "completed")
            .order_by(ContractRun.created_at.desc())
            .limit(1)
        )
        changes = result.scalar_one_or_none()
        return len(changes) if isinstance(changes, list) else 0
