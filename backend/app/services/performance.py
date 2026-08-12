from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.errors import AppError
from app.domain.network import OutboundNetworkPolicy
from app.domain.performance import (
    PerformanceExecutionResult,
    PerformanceScenarioDefinition,
    metric_value,
    threshold_outcomes,
)
from app.engine.k6_compiler import CompiledK6Scenario, K6ScenarioCompiler
from app.models.access import User
from app.models.artifacts import Artifact
from app.models.performance import (
    PerformanceGateEvaluation,
    PerformanceRun,
    PerformanceScenario,
)
from app.repositories.performance import PerformanceRepository
from app.runner.k6 import K6ExecutionError
from app.schemas.performance import (
    PerformanceScenarioVersionWrite,
    PerformanceScenarioWrite,
)
from app.services.audit import AuditService
from app.services.outbound import outbound_request_guard
from app.services.projects import ProjectService

logger = logging.getLogger(__name__)


class PerformanceRunDispatcher(Protocol):
    def start_performance_run(self, run_id: UUID) -> None: ...


class PerformanceExecutor(Protocol):
    async def run(
        self, scenario: CompiledK6Scenario, *, timeout_seconds: int
    ) -> PerformanceExecutionResult: ...


class PerformanceMetricsStore(Protocol):
    async def put(self, *, key: str, content: bytes, content_type: str) -> None: ...


@dataclass(frozen=True, slots=True)
class PerformanceRunPlan:
    run_id: UUID
    project_id: UUID
    created_by_id: UUID
    definition: PerformanceScenarioDefinition
    compiled: CompiledK6Scenario
    network_policy: OutboundNetworkPolicy


class PerformanceScenarioService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = PerformanceRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)
        self._compiler = K6ScenarioCompiler()

    async def create(
        self, *, actor: User, project_id: UUID, payload: PerformanceScenarioWrite
    ) -> PerformanceScenario:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        definition = payload.definition
        await self._validate_definition(project_id, definition)
        name = payload.name.strip()
        version = await self._repository.latest_version(project_id=project_id, name=name) + 1
        scenario = self._new_scenario(
            actor=actor,
            project_id=project_id,
            name=name,
            description=payload.description,
            version=version,
            definition=definition,
        )
        self._repository.add(scenario)
        await self._session.flush()
        self._record(actor, scenario, "performance_scenario.created")
        await self._session.commit()
        await self._session.refresh(scenario)
        return scenario

    async def create_version(
        self,
        *,
        actor: User,
        project_id: UUID,
        scenario_id: UUID,
        payload: PerformanceScenarioVersionWrite,
    ) -> PerformanceScenario:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        source = await self._get_scenario(project_id, scenario_id)
        if source.status != "published":
            raise AppError(
                code="PERFORMANCE_SCENARIO_NOT_PUBLISHED",
                message="只能从已发布性能场景创建新版本",
                status_code=409,
            )
        await self._validate_definition(project_id, payload.definition)
        version = await self._repository.latest_version(project_id=project_id, name=source.name) + 1
        scenario = self._new_scenario(
            actor=actor,
            project_id=project_id,
            name=source.name,
            description=payload.description,
            version=version,
            definition=payload.definition,
        )
        self._repository.add(scenario)
        await self._session.flush()
        self._record(actor, scenario, "performance_scenario.version_created")
        await self._session.commit()
        await self._session.refresh(scenario)
        return scenario

    async def publish(
        self, *, actor: User, project_id: UUID, scenario_id: UUID
    ) -> PerformanceScenario:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        scenario = await self._repository.get_scenario_for_update(scenario_id)
        if scenario is None or scenario.project_id != project_id:
            raise _scenario_not_found()
        if scenario.status == "published":
            return scenario
        definition = PerformanceScenarioDefinition.model_validate(scenario.definition)
        await self._validate_definition(project_id, definition)
        compiled = self._compiler.compile(definition)
        if compiled.sha256 != scenario.compiled_sha256:
            raise AppError(
                code="PERFORMANCE_SCENARIO_SNAPSHOT_MISMATCH",
                message="性能场景编译摘要不一致",
                status_code=409,
            )
        scenario.status = "published"
        scenario.published_at = datetime.now(UTC)
        self._record(actor, scenario, "performance_scenario.published")
        await self._session.commit()
        await self._session.refresh(scenario)
        return scenario

    async def list_scenarios(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[PerformanceScenario], int]:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_scenarios(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def get(self, *, actor: User, project_id: UUID, scenario_id: UUID) -> PerformanceScenario:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._get_scenario(project_id, scenario_id)

    def _new_scenario(
        self,
        *,
        actor: User,
        project_id: UUID,
        name: str,
        description: str,
        version: int,
        definition: PerformanceScenarioDefinition,
    ) -> PerformanceScenario:
        compiled = self._compiler.compile(definition)
        return PerformanceScenario(
            project_id=project_id,
            name=name,
            description=description.strip(),
            version=version,
            status="draft",
            target_type=definition.target_type,
            definition=definition.model_dump(mode="json"),
            compiled_sha256=compiled.sha256,
            created_by_id=actor.id,
        )

    async def _validate_definition(
        self, project_id: UUID, definition: PerformanceScenarioDefinition
    ) -> None:
        if definition.maximum_vus > settings.performance_max_vus:
            raise AppError(
                code="PERFORMANCE_VUS_LIMIT_EXCEEDED",
                message=f"VU 不能超过系统上限 {settings.performance_max_vus}",
                status_code=422,
            )
        if definition.total_duration_seconds > settings.performance_max_duration_seconds:
            raise AppError(
                code="PERFORMANCE_DURATION_LIMIT_EXCEEDED",
                message=f"执行时长不能超过系统上限 {settings.performance_max_duration_seconds} 秒",
                status_code=422,
            )
        policy = await self._projects.load_runtime_security_policy(project_id)
        for step in definition.steps:
            await outbound_request_guard.enforce(step.url, policy)

    async def _get_scenario(self, project_id: UUID, scenario_id: UUID) -> PerformanceScenario:
        scenario = await self._repository.get_scenario(scenario_id)
        if scenario is None or scenario.project_id != project_id:
            raise _scenario_not_found()
        return scenario

    def _record(self, actor: User, scenario: PerformanceScenario, action: str) -> None:
        self._audit.record(
            actor_user_id=actor.id,
            project_id=scenario.project_id,
            action=action,
            resource_type="performance_scenario",
            resource_id=scenario.id,
            details={"version": scenario.version, "compiled_sha256": scenario.compiled_sha256},
        )

    @staticmethod
    def _require_enabled() -> None:
        if not settings.feature_performance_lab_enabled:
            raise AppError(
                code="PERFORMANCE_LAB_DISABLED",
                message="性能实验室尚未启用",
                status_code=409,
            )


class PerformanceRunService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = PerformanceRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def queue(
        self,
        *,
        actor: User,
        project_id: UUID,
        scenario_id: UUID,
        dispatcher: PerformanceRunDispatcher,
    ) -> PerformanceRun:
        PerformanceScenarioService._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        scenario = await self._repository.get_scenario(scenario_id)
        if scenario is None or scenario.project_id != project_id:
            raise _scenario_not_found()
        if scenario.status != "published":
            raise AppError(
                code="PERFORMANCE_SCENARIO_NOT_PUBLISHED",
                message="性能场景发布后才能运行",
                status_code=409,
            )
        run = PerformanceRun(
            project_id=project_id,
            scenario_id=scenario.id,
            scenario_version=scenario.version,
            status="queued",
            definition_snapshot=dict(scenario.definition),
            compiled_sha256=scenario.compiled_sha256,
            created_by_id=actor.id,
        )
        self._repository.add(run)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="performance_run.queued",
            resource_type="performance_run",
            resource_id=run.id,
            details={"scenario_id": str(scenario.id), "scenario_version": scenario.version},
        )
        await self._session.commit()
        await self._session.refresh(run)
        try:
            dispatcher.start_performance_run(run.id)
        except Exception as error:
            logger.exception(
                "Performance run dispatch failed", extra={"performance_run_id": str(run.id)}
            )
            run.status = "failed"
            run.error_code = "PERFORMANCE_QUEUE_UNAVAILABLE"
            run.error_message = "性能任务队列暂时不可用"
            run.completed_at = datetime.now(UTC)
            await self._session.commit()
            raise AppError(
                code="PERFORMANCE_QUEUE_UNAVAILABLE",
                message="性能任务队列暂时不可用",
                status_code=503,
            ) from error
        return run

    async def list_runs(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[PerformanceRun], int]:
        PerformanceScenarioService._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_runs(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def get(
        self, *, actor: User, project_id: UUID, run_id: UUID
    ) -> tuple[PerformanceRun, list[PerformanceGateEvaluation]]:
        PerformanceScenarioService._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        run = await self._repository.get_run(run_id)
        if run is None or run.project_id != project_id:
            raise AppError(
                code="PERFORMANCE_RUN_NOT_FOUND", message="性能运行不存在", status_code=404
            )
        return run, await self._repository.list_evaluations(run.id)


class PerformanceRunCoordinator:
    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        executor: PerformanceExecutor,
        metrics_store: PerformanceMetricsStore,
    ) -> None:
        self._session_maker = session_maker
        self._executor = executor
        self._metrics_store = metrics_store
        self._compiler = K6ScenarioCompiler()

    async def run(self, run_id: UUID) -> None:
        plan = await self._claim(run_id)
        if plan is None:
            return
        try:
            for step in plan.definition.steps:
                await outbound_request_guard.enforce(step.url, plan.network_policy)
            timeout = min(
                plan.definition.total_duration_seconds + plan.definition.graceful_stop_seconds + 60,
                settings.performance_runner_timeout_seconds,
            )
            result = await self._executor.run(plan.compiled, timeout_seconds=timeout)
            await self._complete(plan, result)
        except K6ExecutionError as error:
            await self._fail(run_id, error.code, error.message)
        except AppError as error:
            await self._fail(run_id, error.code, error.message)
        except Exception:
            logger.exception("Performance worker failed", extra={"performance_run_id": str(run_id)})
            await self._fail(run_id, "PERFORMANCE_RUNNER_FAILED", "性能 Runner 执行失败")

    async def _claim(self, run_id: UUID) -> PerformanceRunPlan | None:
        async with self._session_maker() as session:
            repository = PerformanceRepository(session)
            run = await repository.get_run_for_update(run_id)
            if run is None or run.status != "queued":
                return None
            definition = PerformanceScenarioDefinition.model_validate(run.definition_snapshot)
            compiled = self._compiler.compile(definition)
            if compiled.sha256 != run.compiled_sha256:
                run.status = "failed"
                run.error_code = "PERFORMANCE_SNAPSHOT_MISMATCH"
                run.error_message = "性能场景 Snapshot 摘要不一致"
                run.completed_at = datetime.now(UTC)
                await session.commit()
                return None
            policy = await ProjectService(session).load_runtime_security_policy(run.project_id)
            run.status = "running"
            run.started_at = datetime.now(UTC)
            await session.commit()
            return PerformanceRunPlan(
                run_id=run.id,
                project_id=run.project_id,
                created_by_id=run.created_by_id,
                definition=definition,
                compiled=compiled,
                network_policy=policy,
            )

    async def _complete(self, plan: PerformanceRunPlan, result: PerformanceExecutionResult) -> None:
        completed_at = datetime.now(UTC)
        artifact_id = await self._store_metrics(plan, result.raw_metrics)
        outcomes = threshold_outcomes(result.summary)
        thresholds_passed = bool(outcomes) and all(item.passed for item in outcomes)
        async with self._session_maker() as session:
            repository = PerformanceRepository(session)
            run = await repository.get_run_for_update(plan.run_id)
            if run is None or run.status != "running":
                return
            baseline = await repository.previous_completed_run(run)
            run.baseline_run_id = baseline.id if baseline is not None else None
            run.raw_metrics_artifact_id = artifact_id
            run.summary = _aggregate_summary(result.summary, baseline)
            run.threshold_results = [item.model_dump(mode="json") for item in outcomes]
            run.status = "passed" if result.exit_code == 0 and thresholds_passed else "failed"
            if not outcomes:
                run.error_code = "K6_THRESHOLD_RESULTS_MISSING"
                run.error_message = "k6 未返回阈值结果"
            elif not thresholds_passed:
                run.error_code = "PERFORMANCE_THRESHOLD_FAILED"
                run.error_message = "性能阈值未通过"
            run.completed_at = completed_at
            await _evaluate_gates(repository, run, completed_at)
            await session.commit()

    async def _store_metrics(self, plan: PerformanceRunPlan, content: bytes) -> UUID | None:
        if not content:
            return None
        artifact_id = uuid4()
        object_key = f"projects/{plan.project_id}/performance-runs/{plan.run_id}/raw-metrics.json"
        await self._metrics_store.put(
            key=object_key,
            content=content,
            content_type="application/x-ndjson",
        )
        async with self._session_maker() as session:
            session.add(
                Artifact(
                    id=artifact_id,
                    project_id=plan.project_id,
                    object_key=object_key,
                    filename=f"performance-{plan.run_id}-raw-metrics.json",
                    content_type="application/x-ndjson",
                    size_bytes=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                    purpose="performance",
                    created_by_id=plan.created_by_id,
                )
            )
            await session.commit()
        return artifact_id

    async def _fail(self, run_id: UUID, code: str, message: str) -> None:
        async with self._session_maker() as session:
            run = await PerformanceRepository(session).get_run_for_update(run_id)
            if run is None or run.status in {"passed", "failed", "cancelled"}:
                return
            run.status = "failed"
            run.error_code = code[:64]
            run.error_message = message[:500]
            run.completed_at = datetime.now(UTC)
            await session.commit()


async def _evaluate_gates(
    repository: PerformanceRepository, run: PerformanceRun, evaluated_at: datetime
) -> None:
    p95 = _number(run.summary.get("http_req_duration_p95_ms"))
    regression = _number(run.summary.get("p95_regression_percent"))
    failed_thresholds = [item for item in run.threshold_results if item.get("passed") is False]
    metrics: dict[str, object] = {
        "http_req_duration_p95_ms": p95,
        "p95_regression_percent": regression,
        "failed_thresholds": len(failed_thresholds),
    }
    for gate in await repository.enabled_gates(run.project_id):
        violations = [
            f"性能阈值未通过: {item.get('metric')} {item.get('expression')}"
            for item in failed_thresholds
        ]
        if regression is not None and regression > gate.max_duration_regression_percent:
            violations.append(
                f"P95 回归 {regression:.2f}% 超过上限 {gate.max_duration_regression_percent:.2f}%"
            )
        repository.add(
            PerformanceGateEvaluation(
                project_id=run.project_id,
                quality_gate_id=gate.id,
                performance_run_id=run.id,
                status="failed" if violations else "passed",
                metrics=metrics,
                violations=violations,
                evaluated_at=evaluated_at,
            )
        )


def _aggregate_summary(
    summary: dict[str, object], baseline: PerformanceRun | None
) -> dict[str, object]:
    p95 = metric_value(summary, "http_req_duration", "p(95)")
    request_rate = metric_value(summary, "http_reqs", "rate")
    request_count = metric_value(summary, "http_reqs", "count")
    failure_rate = metric_value(summary, "http_req_failed", "rate")
    baseline_p95 = (
        _number(baseline.summary.get("http_req_duration_p95_ms")) if baseline is not None else None
    )
    regression = _regression(p95, baseline_p95)
    return {
        "http_req_duration_p95_ms": p95,
        "http_reqs_rate": request_rate,
        "http_reqs_count": request_count,
        "http_req_failed_rate": failure_rate,
        "baseline_p95_ms": baseline_p95,
        "p95_regression_percent": regression,
    }


def _regression(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None or baseline <= 0:
        return None
    return round((current - baseline) / baseline * 100, 2)


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _scenario_not_found() -> AppError:
    return AppError(
        code="PERFORMANCE_SCENARIO_NOT_FOUND", message="性能场景不存在", status_code=404
    )
