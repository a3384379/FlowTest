from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.quality_intelligence import FailureObservation
from app.domain.reporting import classify_failure
from app.models.contracts import DeploymentCompatibilityCheck
from app.models.impact import CoverageSnapshot, ImpactRun, TestSelection
from app.models.performance import PerformanceRun
from app.models.quality import FlakyRecord
from app.models.quality_intelligence import FailureCluster, ReleaseRisk
from app.models.workflows import Workflow, WorkflowExecution, WorkflowNodeExecution
from app.repositories.impact import ImpactRunBundle

_OUTCOME_EXECUTION_STATUSES = ("passed", "failed")
TerminalExecutionSnapshot = tuple[tuple[WorkflowExecution, str], ...]


class QualityIntelligenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add_risk(self, risk: ReleaseRisk, clusters: list[FailureCluster]) -> None:
        self._session.add(risk)
        self._session.add_all(clusters)

    async def get_impact_bundle(self, run_id: UUID) -> ImpactRunBundle | None:
        row = (
            await self._session.execute(
                select(ImpactRun, TestSelection, CoverageSnapshot)
                .join(TestSelection, TestSelection.impact_run_id == ImpactRun.id)
                .join(CoverageSnapshot, CoverageSnapshot.impact_run_id == ImpactRun.id)
                .where(ImpactRun.id == run_id)
            )
        ).one_or_none()
        return ImpactRunBundle(*row) if row is not None else None

    async def list_risks(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[ReleaseRisk], int]:
        condition = ReleaseRisk.project_id == project_id
        items = list(
            (
                await self._session.scalars(
                    select(ReleaseRisk)
                    .where(condition)
                    .order_by(ReleaseRisk.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(ReleaseRisk).where(condition)
        )
        return items, int(total or 0)

    async def get_risk(self, risk_id: UUID) -> ReleaseRisk | None:
        return await self._session.get(ReleaseRisk, risk_id)

    async def list_clusters(self, risk_id: UUID) -> list[FailureCluster]:
        return list(
            (
                await self._session.scalars(
                    select(FailureCluster)
                    .where(FailureCluster.release_risk_id == risk_id)
                    .order_by(FailureCluster.occurrence_count.desc(), FailureCluster.fingerprint)
                )
            ).all()
        )

    async def failure_observations(
        self,
        *,
        project_id: UUID,
        started_at: datetime,
        ended_at: datetime,
        terminal_executions: TerminalExecutionSnapshot | None = None,
    ) -> tuple[FailureObservation, ...]:
        rows = (
            terminal_executions
            if terminal_executions is not None
            else await self.terminal_execution_snapshot(
                project_id=project_id, started_at=started_at, ended_at=ended_at
            )
        )
        failed_rows = [
            (execution, name) for execution, name in rows if execution.status == "failed"
        ]
        first_failure_evidence: dict[
            UUID, tuple[WorkflowExecution, WorkflowNodeExecution | None]
        ] = {}
        if failed_rows:
            root_ids = [execution.id for execution, _name in failed_rows]
            evidence_root_id = func.coalesce(
                WorkflowExecution.parent_execution_id, WorkflowExecution.id
            )
            evidence_rows = (
                await self._session.execute(
                    select(WorkflowExecution, WorkflowNodeExecution)
                    .outerjoin(
                        WorkflowNodeExecution,
                        (WorkflowNodeExecution.workflow_execution_id == WorkflowExecution.id)
                        & (WorkflowNodeExecution.status == "failed"),
                    )
                    .where(
                        WorkflowExecution.project_id == project_id,
                        WorkflowExecution.status == "failed",
                        WorkflowExecution.completed_at.is_not(None),
                        WorkflowExecution.completed_at <= ended_at,
                        evidence_root_id.in_(root_ids),
                    )
                    .order_by(
                        evidence_root_id,
                        case(
                            (WorkflowExecution.parent_execution_id.is_not(None), 0),
                            else_=1,
                        ),
                        WorkflowExecution.started_at,
                        WorkflowNodeExecution.started_at.asc().nulls_last(),
                        case((WorkflowNodeExecution.id.is_not(None), 0), else_=1),
                        WorkflowNodeExecution.completed_at,
                        WorkflowNodeExecution.id,
                        WorkflowExecution.id,
                    )
                )
            ).all()
            for evidence_execution, node in evidence_rows:
                evidence_root_id = evidence_execution.parent_execution_id or evidence_execution.id
                first_failure_evidence.setdefault(evidence_root_id, (evidence_execution, node))
        observations = []
        for execution, workflow_name in failed_rows:
            evidence_execution, failed_node = first_failure_evidence.get(
                execution.id, (execution, None)
            )
            error_code = (
                failed_node.error_code if failed_node is not None else evidence_execution.error_code
            )
            observations.append(
                FailureObservation(
                    execution_id=execution.id,
                    workflow_id=execution.workflow_id,
                    workflow_name=workflow_name,
                    category=classify_failure(status=execution.status, error_code=error_code).value,
                    error_code=error_code,
                    node_type=failed_node.node_type if failed_node is not None else None,
                    occurred_at=execution.started_at,
                )
            )
        return tuple(observations)

    async def terminal_execution_snapshot(
        self, *, project_id: UUID, started_at: datetime, ended_at: datetime
    ) -> TerminalExecutionSnapshot:
        rows = await self._session.execute(
            select(WorkflowExecution, Workflow.name)
            .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
            .where(
                WorkflowExecution.project_id == project_id,
                WorkflowExecution.parent_execution_id.is_(None),
                WorkflowExecution.status.in_(_OUTCOME_EXECUTION_STATUSES),
                WorkflowExecution.started_at >= started_at,
                WorkflowExecution.started_at < ended_at,
                WorkflowExecution.completed_at.is_not(None),
                WorkflowExecution.completed_at <= ended_at,
            )
            .order_by(WorkflowExecution.started_at.desc())
        )
        return tuple(rows.tuples().all())

    async def deployment_decisions(self, project_id: UUID) -> list[str]:
        ranked = (
            select(
                DeploymentCompatibilityCheck.provider_service_id.label("provider_service_id"),
                DeploymentCompatibilityCheck.decision.label("decision"),
                func.row_number()
                .over(
                    partition_by=DeploymentCompatibilityCheck.provider_service_id,
                    order_by=(
                        DeploymentCompatibilityCheck.created_at.desc(),
                        DeploymentCompatibilityCheck.id.desc(),
                    ),
                )
                .label("decision_rank"),
            )
            .where(DeploymentCompatibilityCheck.project_id == project_id)
            .subquery()
        )
        return list(
            (
                await self._session.scalars(
                    select(ranked.c.decision)
                    .where(ranked.c.decision_rank == 1)
                    .order_by(ranked.c.provider_service_id)
                )
            ).all()
        )

    async def latest_performance_regression(self, project_id: UUID) -> tuple[UUID | None, float]:
        run = (
            await self._session.scalars(
                select(PerformanceRun)
                .where(
                    PerformanceRun.project_id == project_id,
                    PerformanceRun.status.in_(("passed", "failed")),
                )
                .order_by(PerformanceRun.created_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if run is None:
            return None, 0.0
        value = run.summary.get("p95_regression_percent")
        return run.id, float(value) if isinstance(value, int | float) else 0.0

    async def flaky_asset_count(self, project_id: UUID) -> int:
        flaky_assets = (
            select(FlakyRecord.target_type, FlakyRecord.target_id)
            .where(FlakyRecord.project_id == project_id, FlakyRecord.flaky_score > 0)
            .group_by(FlakyRecord.target_type, FlakyRecord.target_id)
            .subquery()
        )
        value = await self._session.scalar(select(func.count()).select_from(flaky_assets))
        return int(value or 0)
