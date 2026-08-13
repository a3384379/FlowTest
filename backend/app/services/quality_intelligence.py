from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.domain.quality_intelligence import (
    FailureClusterEvidence,
    RiskInput,
    calculate_release_risk,
    cluster_failures,
    evidence_fingerprint,
)
from app.models.access import User
from app.models.quality_intelligence import FailureCluster, ReleaseRisk
from app.models.workflows import WorkflowExecution
from app.repositories.impact import ImpactRunBundle
from app.repositories.quality_intelligence import QualityIntelligenceRepository
from app.schemas.quality_intelligence import ReleaseRiskCreate
from app.services.audit import AuditService
from app.services.projects import ProjectService


class QualityIntelligenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = QualityIntelligenceRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def create_risk(
        self, *, actor: User, project_id: UUID, payload: ReleaseRiskCreate
    ) -> tuple[ReleaseRisk, list[FailureCluster]]:
        _require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        impact = await self._impact(project_id, payload.impact_run_id)
        ended_at = datetime.now(UTC)
        started_at = ended_at - timedelta(days=payload.window_days)
        baseline_ended_at = started_at
        baseline_started_at = baseline_ended_at - timedelta(days=payload.window_days)
        current_observations = await self._repository.failure_observations(
            project_id=project_id, started_at=started_at, ended_at=ended_at
        )
        baseline_observations = await self._repository.failure_observations(
            project_id=project_id,
            started_at=baseline_started_at,
            ended_at=baseline_ended_at,
        )
        cluster_evidence = cluster_failures(current_observations, baseline_observations)
        current_total, current_failures = await self._repository.execution_counts(
            project_id=project_id, started_at=started_at, ended_at=ended_at
        )
        baseline_total, baseline_failures = await self._repository.execution_counts(
            project_id=project_id,
            started_at=baseline_started_at,
            ended_at=baseline_ended_at,
        )
        decisions = await self._repository.deployment_decisions(project_id)
        (
            performance_run_id,
            performance_regression,
        ) = await self._repository.latest_performance_regression(project_id)
        flaky_assets = await self._repository.flaky_asset_count(project_id)
        breaking_changes = _breaking_change_count(impact)
        regressed_clusters = sum(
            item.baseline_count == 0 or item.occurrence_count > item.baseline_count
            for item in cluster_evidence
        )
        risk_result = calculate_release_risk(
            RiskInput(
                coverage_percent=impact.coverage.coverage_percent,
                breaking_changes=breaking_changes,
                current_total=current_total,
                current_failures=current_failures,
                baseline_total=baseline_total,
                baseline_failures=baseline_failures,
                regressed_clusters=regressed_clusters,
                unsafe_contracts=decisions.count("unsafe"),
                unknown_contracts=decisions.count("unknown"),
                performance_regression_percent=performance_regression,
                flaky_assets=flaky_assets,
            )
        )
        evidence = _evidence_snapshot(
            impact=impact,
            current_total=current_total,
            current_failures=current_failures,
            baseline_total=baseline_total,
            baseline_failures=baseline_failures,
            cluster_count=len(cluster_evidence),
            regressed_clusters=regressed_clusters,
            decisions=decisions,
            performance_run_id=performance_run_id,
            performance_regression=performance_regression,
            flaky_assets=flaky_assets,
        )
        executions = await self._repository.executions_for_trend(
            project_id=project_id, started_at=started_at, ended_at=ended_at
        )
        risk = ReleaseRisk(
            project_id=project_id,
            impact_run_id=impact.run.id,
            title=payload.title.strip(),
            algorithm_version="release_risk_v1",
            window_days=payload.window_days,
            window_started_at=started_at,
            window_ended_at=ended_at,
            baseline_started_at=baseline_started_at,
            baseline_ended_at=baseline_ended_at,
            score=risk_result.score,
            quality_score=risk_result.quality_score,
            risk_level=risk_result.level.value,
            factors=list(risk_result.factors),
            evidence_snapshot=evidence,
            quality_trend=_quality_trend(executions, started_at.date(), payload.window_days),
            recommended_tests=_recommended_tests(
                impact.selection.selected_assets, cluster_evidence
            ),
            fingerprint=evidence_fingerprint(cast(dict[str, JsonValue], evidence)),
            created_by_id=actor.id,
        )
        self._session.add(risk)
        await self._session.flush()
        clusters = [_cluster_model(project_id, risk.id, item) for item in cluster_evidence]
        self._session.add_all(clusters)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="release_risk.created",
            resource_type="release_risk",
            resource_id=risk.id,
            details={
                "algorithm_version": risk.algorithm_version,
                "score": risk.score,
                "risk_level": risk.risk_level,
                "impact_run_id": str(risk.impact_run_id),
                "failure_cluster_count": len(clusters),
                "fingerprint": risk.fingerprint,
            },
        )
        await self._session.commit()
        await self._session.refresh(risk)
        return risk, await self._repository.list_clusters(risk.id)

    async def list_risks(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[ReleaseRisk], int]:
        _require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_risks(
            project_id=project_id, offset=(page - 1) * page_size, limit=page_size
        )

    async def get_risk(
        self, *, actor: User, project_id: UUID, risk_id: UUID
    ) -> tuple[ReleaseRisk, list[FailureCluster]]:
        _require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        risk = await self._repository.get_risk(risk_id)
        if risk is None or risk.project_id != project_id:
            raise AppError(
                code="RELEASE_RISK_NOT_FOUND", message="发布风险快照不存在", status_code=404
            )
        return risk, await self._repository.list_clusters(risk.id)

    async def list_clusters(
        self, *, actor: User, project_id: UUID, risk_id: UUID
    ) -> list[FailureCluster]:
        _, clusters = await self.get_risk(actor=actor, project_id=project_id, risk_id=risk_id)
        return clusters

    async def _impact(self, project_id: UUID, impact_run_id: UUID) -> ImpactRunBundle:
        bundle = await self._repository.get_impact_bundle(impact_run_id)
        if bundle is None or bundle.run.project_id != project_id:
            raise AppError(code="IMPACT_RUN_NOT_FOUND", message="影响分析不存在", status_code=404)
        return bundle


def _require_enabled() -> None:
    if not settings.feature_quality_intelligence_enabled:
        raise AppError(
            code="QUALITY_INTELLIGENCE_DISABLED", message="质量智能未启用", status_code=503
        )


def _breaking_change_count(impact: ImpactRunBundle) -> int:
    return sum(item.get("severity") == "breaking" for item in impact.run.changes)


def _evidence_snapshot(
    *,
    impact: ImpactRunBundle,
    current_total: int,
    current_failures: int,
    baseline_total: int,
    baseline_failures: int,
    cluster_count: int,
    regressed_clusters: int,
    decisions: list[str],
    performance_run_id: UUID | None,
    performance_regression: float,
    flaky_assets: int,
) -> dict[str, Any]:
    return {
        "impact": {
            "run_id": str(impact.run.id),
            "source_fingerprint": impact.run.source_fingerprint,
            "change_count": impact.run.change_count,
            "breaking_change_count": _breaking_change_count(impact),
            "selection_id": str(impact.selection.id),
            "selection_strategy": impact.selection.strategy,
            "selected_asset_count": len(impact.selection.selected_assets),
            "coverage_snapshot_id": str(impact.coverage.id),
            "coverage_percent": impact.coverage.coverage_percent,
            "coverage_gap_count": len(impact.coverage.gaps),
        },
        "executions": {
            "current_total": current_total,
            "current_failures": current_failures,
            "baseline_total": baseline_total,
            "baseline_failures": baseline_failures,
        },
        "failure_clusters": {
            "count": cluster_count,
            "regressed_count": regressed_clusters,
        },
        "contracts": {
            "unsafe": decisions.count("unsafe"),
            "unknown": decisions.count("unknown"),
            "safe": decisions.count("safe"),
        },
        "performance": {
            "run_id": str(performance_run_id) if performance_run_id else None,
            "p95_regression_percent": round(performance_regression, 2),
        },
        "flaky_assets": flaky_assets,
    }


def _quality_trend(
    executions: list[WorkflowExecution], started_on: date, days: int
) -> list[dict[str, Any]]:
    by_day: dict[date, list[WorkflowExecution]] = defaultdict(list)
    for execution in executions:
        by_day[execution.started_at.astimezone(UTC).date()].append(execution)
    points = []
    for offset in range(days + 1):
        day = started_on + timedelta(days=offset)
        values = by_day.get(day, [])
        passed = sum(item.status == "passed" for item in values)
        failed = sum(item.status == "failed" for item in values)
        total = len(values)
        points.append(
            {
                "date": day.isoformat(),
                "total": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": round(passed / total * 100, 2) if total else 100.0,
            }
        )
    return points


def _recommended_tests(
    selected_assets: list[dict[str, Any]], clusters: tuple[FailureClusterEvidence, ...]
) -> list[dict[str, Any]]:
    failed_workflows = {
        workflow_id for cluster in clusters for workflow_id in cluster.affected_workflow_ids
    }
    recommendations = []
    for asset in selected_assets:
        target_id = str(asset.get("target_id", ""))
        risk = str(asset.get("risk", "low"))
        priority = "high" if target_id in failed_workflows or risk == "high" else "medium"
        reasons = [str(value) for value in asset.get("reasons", []) if isinstance(value, str)]
        if target_id in failed_workflows:
            reasons.append("该 Workflow 在当前窗口存在失败聚类")
        recommendations.append(
            {
                "target_type": asset.get("target_type"),
                "target_id": target_id,
                "name": asset.get("name"),
                "version": asset.get("version"),
                "priority": priority,
                "reasons": sorted(set(reasons)),
                "change_keys": asset.get("change_keys", []),
            }
        )
    priorities = {"high": 0, "medium": 1}
    return sorted(
        recommendations,
        key=lambda item: (priorities.get(str(item["priority"]), 2), str(item["target_id"])),
    )


def _cluster_model(
    project_id: UUID, risk_id: UUID, evidence: FailureClusterEvidence
) -> FailureCluster:
    return FailureCluster(
        project_id=project_id,
        release_risk_id=risk_id,
        fingerprint=evidence.fingerprint,
        title=evidence.title,
        failure_category=evidence.category,
        error_code=evidence.error_code,
        node_type=evidence.node_type,
        occurrence_count=evidence.occurrence_count,
        baseline_count=evidence.baseline_count,
        affected_workflow_ids=list(evidence.affected_workflow_ids),
        affected_workflow_names=list(evidence.affected_workflow_names),
        sample_execution_ids=list(evidence.sample_execution_ids),
        confidence=evidence.confidence,
        regression_percent=evidence.regression_percent,
        recommendation=evidence.recommendation,
    )
