from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.junit import JUnitCase, build_junit_xml
from app.domain.quality import (
    QualityMetrics,
    QualityPolicy,
    duration_regression,
    evaluate_gate,
    flaky_score,
)
from app.models.access import User
from app.models.quality import FlakyRecord, QualityGate, QualityGateEvaluation
from app.models.tasking import TestPlanRun, TestPlanRunItem
from app.models.workflows import WorkflowExecution
from app.repositories.quality import QualityRepository
from app.repositories.tasking import TaskingRepository
from app.schemas.quality import QualityGateWrite, RunQualityResponse
from app.services.audit import AuditService
from app.services.projects import ProjectService


class QualityService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._quality = QualityRepository(session)
        self._tasks = TaskingRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def create_gate(
        self, *, actor: User, project_id: UUID, payload: QualityGateWrite
    ) -> QualityGate:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        name = payload.name.strip()
        await self._ensure_gate_name(project_id=project_id, name=name)
        gate = QualityGate(
            project_id=project_id,
            name=name,
            enabled=payload.enabled,
            min_pass_rate=payload.min_pass_rate,
            max_failed=payload.max_failed,
            max_flaky=payload.max_flaky,
            max_duration_regression_percent=payload.max_duration_regression_percent,
            require_no_breaking_changes=payload.require_no_breaking_changes,
            created_by_id=actor.id,
        )
        self._quality.add(gate)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="quality_gate.created",
            resource_type="quality_gate",
            resource_id=gate.id,
        )
        await self._session.commit()
        await self._session.refresh(gate)
        return gate

    async def list_gates(self, *, actor: User, project_id: UUID) -> list[QualityGate]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._quality.list_gates(project_id)

    async def update_gate(
        self,
        *,
        actor: User,
        project_id: UUID,
        gate_id: UUID,
        payload: QualityGateWrite,
    ) -> QualityGate:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        gate = await self._get_gate(project_id, gate_id)
        name = payload.name.strip()
        await self._ensure_gate_name(project_id=project_id, name=name, excluding_id=gate.id)
        gate.name = name
        gate.enabled = payload.enabled
        gate.min_pass_rate = payload.min_pass_rate
        gate.max_failed = payload.max_failed
        gate.max_flaky = payload.max_flaky
        gate.max_duration_regression_percent = payload.max_duration_regression_percent
        gate.require_no_breaking_changes = payload.require_no_breaking_changes
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="quality_gate.updated",
            resource_type="quality_gate",
            resource_id=gate.id,
        )
        await self._session.commit()
        await self._session.refresh(gate)
        return gate

    async def delete_gate(self, *, actor: User, project_id: UUID, gate_id: UUID) -> None:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        gate = await self._get_gate(project_id, gate_id)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="quality_gate.deleted",
            resource_type="quality_gate",
            resource_id=gate.id,
        )
        await self._session.delete(gate)
        await self._session.commit()

    async def list_flaky_records(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[FlakyRecord], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._quality.list_flaky_records(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def set_quarantine(
        self,
        *,
        actor: User,
        project_id: UUID,
        record_id: UUID,
        quarantined: bool,
    ) -> FlakyRecord:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        record = await self._quality.get_flaky_record(record_id)
        if record is None or record.project_id != project_id:
            raise AppError(
                code="FLAKY_RECORD_NOT_FOUND", message="Flaky 记录不存在", status_code=404
            )
        record.quarantined = quarantined
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="flaky_record.quarantine_changed",
            resource_type="flaky_record",
            resource_id=record.id,
            details={"quarantined": quarantined},
        )
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def get_run_quality(
        self, *, actor: User, project_id: UUID, run_id: UUID
    ) -> RunQualityResponse:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        run = await self._get_run(project_id, run_id)
        evaluations = await self._quality.list_evaluations(run.id)
        return RunQualityResponse(
            run_id=run.id,
            baseline_run_id=run.baseline_run_id,
            summary=dict(run.quality_summary),
            evaluations=evaluations,
        )

    async def render_junit(self, *, actor: User, project_id: UUID, run_id: UUID) -> bytes:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        run = await self._get_run(project_id, run_id)
        return await self._junit_for_run(run)

    async def render_ci_junit(self, *, project_id: UUID, run_id: UUID) -> bytes:
        run = await self._get_run(project_id, run_id)
        return await self._junit_for_run(run)

    async def finalize_run(self, *, run: TestPlanRun, items: list[TestPlanRunItem]) -> None:
        completed_at = run.completed_at or datetime.now(UTC)
        for item in items:
            if item.status in {"passed", "failed"}:
                await self._record_outcome(run, item, completed_at)
        baseline = await self._quality.previous_completed_run(run)
        if baseline is not None:
            run.baseline_run_id = baseline.id
        metrics = await self._build_metrics(run, items, baseline)
        summary = asdict(metrics)
        run.quality_summary = summary
        for gate in await self._quality.list_gates(run.project_id):
            if gate.enabled:
                await self._evaluate(gate, run, metrics, completed_at)

    async def evaluate_ci_gate(
        self, *, project_id: UUID, run_id: UUID, gate_id: UUID
    ) -> QualityGateEvaluation:
        run = await self._get_run(project_id, run_id)
        gate = await self._get_gate(project_id, gate_id)
        if run.status not in {"passed", "failed", "cancelled"}:
            raise AppError(
                code="TEST_PLAN_RUN_NOT_FINISHED",
                message="测试计划运行尚未结束",
                status_code=409,
            )
        existing = await self._quality.find_evaluation(gate_id=gate.id, run_id=run.id)
        if existing is not None:
            return existing
        items = await self._tasks.list_run_items(run.id)
        baseline = await self._quality.previous_completed_run(run)
        metrics = await self._build_metrics(run, items, baseline)
        evaluation = await self._evaluate(gate, run, metrics, datetime.now(UTC))
        await self._session.commit()
        await self._session.refresh(evaluation)
        return evaluation

    async def is_quarantined(
        self, *, project_id: UUID, target_type: str, target_id: UUID, target_version: int
    ) -> bool:
        record = await self._quality.find_flaky_record(
            project_id=project_id,
            target_type=target_type,
            target_id=target_id,
            target_version=target_version,
        )
        return record is not None and record.quarantined

    async def _record_outcome(
        self, run: TestPlanRun, item: TestPlanRunItem, completed_at: datetime
    ) -> None:
        record = await self._quality.ensure_flaky_record(
            project_id=run.project_id,
            target_type=item.target_type,
            target_id=item.target_id,
            target_version=item.target_version,
        )
        if record.last_status is not None and record.last_status != item.status:
            record.transitions += 1
        record.total_runs += 1
        record.passed_runs += int(item.status == "passed")
        record.failed_runs += int(item.status == "failed")
        record.flaky_score = flaky_score(
            total_runs=record.total_runs,
            passed_runs=record.passed_runs,
            failed_runs=record.failed_runs,
            transitions=record.transitions,
        )
        record.last_status = item.status
        record.last_run_id = run.id
        record.last_run_at = completed_at

    async def _build_metrics(
        self,
        run: TestPlanRun,
        items: list[TestPlanRunItem],
        baseline: TestPlanRun | None,
    ) -> QualityMetrics:
        total = sum(item.status != "quarantined" for item in items)
        passed = sum(item.status == "passed" for item in items)
        failed = sum(item.status == "failed" for item in items)
        quarantined = sum(item.status == "quarantined" for item in items)
        flaky = 0
        for item in items:
            record = await self._quality.find_flaky_record(
                project_id=run.project_id,
                target_type=item.target_type,
                target_id=item.target_id,
                target_version=item.target_version,
            )
            flaky += int(record is not None and record.flaky_score > 0)
        duration = _run_duration(run)
        baseline_duration = _summary_duration(baseline)
        return QualityMetrics(
            total=total,
            passed=passed,
            failed=failed,
            quarantined=quarantined,
            flaky=flaky,
            pass_rate=round(passed / total * 100, 2) if total else 100.0,
            duration_seconds=duration,
            baseline_duration_seconds=baseline_duration,
            duration_regression_percent=duration_regression(duration, baseline_duration),
            breaking_changes=await self._quality.latest_breaking_change_count(run.project_id),
        )

    async def _evaluate(
        self,
        gate: QualityGate,
        run: TestPlanRun,
        metrics: QualityMetrics,
        evaluated_at: datetime,
    ) -> QualityGateEvaluation:
        result = evaluate_gate(
            QualityPolicy(
                min_pass_rate=gate.min_pass_rate,
                max_failed=gate.max_failed,
                max_flaky=gate.max_flaky,
                max_duration_regression_percent=gate.max_duration_regression_percent,
                require_no_breaking_changes=gate.require_no_breaking_changes,
            ),
            metrics,
        )
        evaluation = QualityGateEvaluation(
            project_id=run.project_id,
            quality_gate_id=gate.id,
            test_plan_run_id=run.id,
            status="passed" if result.passed else "failed",
            metrics=asdict(metrics),
            violations=list(result.violations),
            evaluated_at=evaluated_at,
        )
        self._quality.add(evaluation)
        return evaluation

    async def _junit_for_run(self, run: TestPlanRun) -> bytes:
        items = await self._tasks.list_run_items(run.id)
        cases: list[JUnitCase] = []
        for item in items:
            execution = (
                await self._session.get(WorkflowExecution, item.workflow_execution_id)
                if item.workflow_execution_id is not None
                else None
            )
            cases.append(
                JUnitCase(
                    name=f"{item.target_type}:{item.target_id}@{item.target_version}",
                    classname="FlowTest.TestPlan",
                    duration_seconds=_execution_duration(execution),
                    status=item.status,
                    message="测试项执行失败" if item.status == "failed" else None,
                )
            )
        return build_junit_xml(suite_name=f"FlowTest plan {run.test_plan_id}", cases=tuple(cases))

    async def _get_gate(self, project_id: UUID, gate_id: UUID) -> QualityGate:
        gate = await self._quality.get_gate(gate_id)
        if gate is None or gate.project_id != project_id:
            raise AppError(code="QUALITY_GATE_NOT_FOUND", message="质量门禁不存在", status_code=404)
        return gate

    async def _get_run(self, project_id: UUID, run_id: UUID) -> TestPlanRun:
        run = await self._tasks.get_run(run_id)
        if run is None or run.project_id != project_id:
            raise AppError(
                code="TEST_PLAN_RUN_NOT_FOUND", message="测试计划运行不存在", status_code=404
            )
        return run

    async def _ensure_gate_name(
        self, *, project_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> None:
        if await self._quality.gate_name_exists(
            project_id=project_id, name=name, excluding_id=excluding_id
        ):
            raise AppError(
                code="QUALITY_GATE_NAME_EXISTS", message="质量门禁名称已存在", status_code=409
            )


def _run_duration(run: TestPlanRun) -> float:
    if run.started_at is None or run.completed_at is None:
        return 0.0
    return max((_aware(run.completed_at) - _aware(run.started_at)).total_seconds(), 0.0)


def _summary_duration(run: TestPlanRun | None) -> float | None:
    if run is None:
        return None
    value = run.quality_summary.get("duration_seconds")
    return float(value) if isinstance(value, int | float) else _run_duration(run)


def _execution_duration(execution: WorkflowExecution | None) -> float:
    if execution is None or execution.started_at is None or execution.completed_at is None:
        return 0.0
    return max(
        (_aware(execution.completed_at) - _aware(execution.started_at)).total_seconds(),
        0.0,
    )


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
