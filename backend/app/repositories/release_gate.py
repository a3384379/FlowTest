from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contracts import DeploymentCompatibilityCheck
from app.models.impact import CoverageSnapshot, ImpactRun
from app.models.performance import PerformanceGateEvaluation, PerformanceRun
from app.models.quality import QualityGate, QualityGateEvaluation
from app.models.quality_intelligence import ReleaseRisk
from app.models.release_gate import ReleaseDecision, ReleasePolicy
from app.models.runner_fabric import RunnerLeaseRecord, RunnerTask
from app.models.tasking import TestPlanRun


@dataclass(frozen=True, slots=True)
class QualityEvidenceBundle:
    run: TestPlanRun
    evaluation: QualityGateEvaluation | None


@dataclass(frozen=True, slots=True)
class ImpactEvidenceBundle:
    run: ImpactRun
    coverage: CoverageSnapshot | None


@dataclass(frozen=True, slots=True)
class PerformanceEvidenceBundle:
    run: PerformanceRun
    evaluations: tuple[PerformanceGateEvaluation, ...]


@dataclass(frozen=True, slots=True)
class RunnerEvidenceBundle:
    task: RunnerTask
    leases: tuple[RunnerLeaseRecord, ...]


class ReleaseGateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: ReleasePolicy | ReleaseDecision) -> None:
        self._session.add(entity)

    async def get_policy(self, policy_id: UUID) -> ReleasePolicy | None:
        return await self._session.get(ReleasePolicy, policy_id)

    async def get_quality_gate(self, gate_id: UUID) -> QualityGate | None:
        return await self._session.get(QualityGate, gate_id)

    async def policy_name_exists(
        self, *, project_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> bool:
        query = select(ReleasePolicy.id).where(
            ReleasePolicy.project_id == project_id, ReleasePolicy.name == name
        )
        if excluding_id is not None:
            query = query.where(ReleasePolicy.id != excluding_id)
        return (await self._session.scalar(query.limit(1))) is not None

    async def list_policies(self, project_id: UUID) -> list[ReleasePolicy]:
        return list(
            (
                await self._session.scalars(
                    select(ReleasePolicy)
                    .where(ReleasePolicy.project_id == project_id)
                    .order_by(ReleasePolicy.created_at)
                )
            ).all()
        )

    async def get_decision(self, decision_id: UUID) -> ReleaseDecision | None:
        return await self._session.get(ReleaseDecision, decision_id)

    async def list_decisions(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[ReleaseDecision], int]:
        condition = ReleaseDecision.project_id == project_id
        items = list(
            (
                await self._session.scalars(
                    select(ReleaseDecision)
                    .where(condition)
                    .order_by(ReleaseDecision.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(ReleaseDecision).where(condition)
        )
        return items, int(total or 0)

    async def quality_evidence(
        self, *, run_id: UUID, gate_id: UUID
    ) -> QualityEvidenceBundle | None:
        run = await self._session.get(TestPlanRun, run_id)
        if run is None:
            return None
        evaluation = await self._session.scalar(
            select(QualityGateEvaluation).where(
                QualityGateEvaluation.test_plan_run_id == run_id,
                QualityGateEvaluation.quality_gate_id == gate_id,
            )
        )
        return QualityEvidenceBundle(run=run, evaluation=evaluation)

    async def deployment_check(self, check_id: UUID) -> DeploymentCompatibilityCheck | None:
        return await self._session.get(DeploymentCompatibilityCheck, check_id)

    async def impact_evidence(self, run_id: UUID) -> ImpactEvidenceBundle | None:
        run = await self._session.get(ImpactRun, run_id)
        if run is None:
            return None
        coverage = await self._session.scalar(
            select(CoverageSnapshot).where(CoverageSnapshot.impact_run_id == run_id)
        )
        return ImpactEvidenceBundle(run=run, coverage=coverage)

    async def release_risk(self, risk_id: UUID) -> ReleaseRisk | None:
        return await self._session.get(ReleaseRisk, risk_id)

    async def performance_evidence(self, run_id: UUID) -> PerformanceEvidenceBundle | None:
        run = await self._session.get(PerformanceRun, run_id)
        if run is None:
            return None
        evaluations = tuple(
            (
                await self._session.scalars(
                    select(PerformanceGateEvaluation)
                    .where(PerformanceGateEvaluation.performance_run_id == run_id)
                    .order_by(PerformanceGateEvaluation.evaluated_at)
                )
            ).all()
        )
        return PerformanceEvidenceBundle(run=run, evaluations=evaluations)

    async def runner_evidence(self, task_id: UUID) -> RunnerEvidenceBundle | None:
        task = await self._session.get(RunnerTask, task_id)
        if task is None:
            return None
        leases = tuple(
            (
                await self._session.scalars(
                    select(RunnerLeaseRecord)
                    .where(RunnerLeaseRecord.task_id == task_id)
                    .order_by(RunnerLeaseRecord.fencing_token)
                )
            ).all()
        )
        return RunnerEvidenceBundle(task=task, leases=leases)
