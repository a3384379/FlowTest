import html
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.reporting import FailureCategory, classify_failure
from app.models.access import User
from app.models.artifacts import Artifact
from app.models.workflows import WorkflowExecution, WorkflowNodeExecution
from app.repositories.reporting import ReportingRepository
from app.services.artifacts import ArtifactService
from app.services.audit import AuditService
from app.services.projects import ProjectService


@dataclass(frozen=True, slots=True)
class ExecutionReportSummary:
    id: UUID
    workflow_id: UUID
    workflow_name: str
    workflow_version: int
    status: str
    failure_category: FailureCategory
    total_nodes: int
    passed_nodes: int
    failed_nodes: int
    skipped_nodes: int
    duration_ms: float | None
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class NodeReport:
    id: UUID
    node_id: str
    node_type: str
    name: str
    status: str
    attempts: int
    duration_ms: float | None
    request: JsonValue
    response: JsonValue
    extraction: JsonValue
    assertion: JsonValue
    input_mappings: JsonValue
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class ExecutionReportDetail:
    summary: ExecutionReportSummary
    nodes: list[NodeReport]
    context: dict[str, JsonValue]
    dataset_children: list[ExecutionReportSummary]


@dataclass(frozen=True, slots=True)
class TrendPoint:
    date: date
    total: int
    passed: int
    failed: int
    cancelled: int
    pass_rate: float
    average_duration_ms: float


@dataclass(frozen=True, slots=True)
class ReportTrend:
    points: list[TrendPoint]
    failures: list[tuple[FailureCategory, int]]


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._reports = ReportingRepository(session)
        self._projects = ProjectService(session)
        self._artifacts = ArtifactService(session)
        self._audit = AuditService(session)

    async def list_executions(
        self,
        *,
        actor: User,
        project_id: UUID,
        page: int,
        page_size: int,
        status: str | None,
    ) -> tuple[list[ExecutionReportSummary], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        executions, total = await self._reports.list_executions(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
            status=status,
        )
        return [await self._summary(item) for item in executions], total

    async def get_execution(
        self, *, actor: User, project_id: UUID, execution_id: UUID
    ) -> ExecutionReportDetail:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        execution = await self._execution(project_id, execution_id)
        nodes = await self._reports.list_nodes(execution.id)
        children = await self._reports.list_children(execution.id)
        return ExecutionReportDetail(
            summary=await self._summary(execution, nodes),
            nodes=[self._node(execution, item) for item in nodes],
            context=cast(dict[str, JsonValue], execution.context),
            dataset_children=[await self._summary(child) for child in children],
        )

    async def trend(self, *, actor: User, project_id: UUID, days: int) -> ReportTrend:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        since = datetime.now(UTC) - timedelta(days=days - 1)
        executions = await self._reports.list_executions_since(
            project_id=project_id,
            since=since.replace(hour=0, minute=0, second=0, microsecond=0),
        )
        by_date: dict[date, list[WorkflowExecution]] = defaultdict(list)
        failures: Counter[FailureCategory] = Counter()
        for execution in executions:
            by_date[_as_utc(execution.started_at).date()].append(execution)
            category = classify_failure(status=execution.status, error_code=execution.error_code)
            if category is not FailureCategory.NONE:
                failures[category] += 1
        points = [self._trend_point(day, by_date.get(day, [])) for day in _date_range(days)]
        return ReportTrend(
            points=points,
            failures=sorted(failures.items(), key=lambda item: (-item[1], item[0].value)),
        )

    async def export_html(self, *, actor: User, project_id: UUID, execution_id: UUID) -> Artifact:
        detail = await self.get_execution(
            actor=actor,
            project_id=project_id,
            execution_id=execution_id,
        )
        content = _render_html(detail).encode()
        artifact = await self._artifacts.store_report(
            actor=actor,
            project_id=project_id,
            filename=f"flowtest-report-{execution_id}.html",
            content=content,
        )
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="report.exported",
            resource_type="workflow_execution",
            resource_id=execution_id,
            details={"artifact_id": str(artifact.id)},
        )
        await self._session.commit()
        await self._session.refresh(artifact)
        return artifact

    async def _execution(self, project_id: UUID, execution_id: UUID) -> WorkflowExecution:
        execution = await self._reports.get_execution(execution_id)
        if execution is None or execution.project_id != project_id:
            raise AppError(
                code="REPORT_EXECUTION_NOT_FOUND",
                message="报告执行记录不存在",
                status_code=404,
            )
        return execution

    async def _summary(
        self,
        execution: WorkflowExecution,
        nodes: list[WorkflowNodeExecution] | None = None,
    ) -> ExecutionReportSummary:
        workflow = await self._reports.get_workflow(execution.workflow_id)
        records = nodes if nodes is not None else await self._reports.list_nodes(execution.id)
        return ExecutionReportSummary(
            id=execution.id,
            workflow_id=execution.workflow_id,
            workflow_name=workflow.name if workflow is not None else "已删除工作流",
            workflow_version=_workflow_version(execution.snapshot),
            status=execution.status,
            failure_category=classify_failure(
                status=execution.status,
                error_code=execution.error_code,
            ),
            total_nodes=len(records),
            passed_nodes=sum(item.status == "passed" for item in records),
            failed_nodes=sum(item.status == "failed" for item in records),
            skipped_nodes=sum(item.status == "skipped" for item in records),
            duration_ms=_duration_ms(execution.started_at, execution.completed_at),
            started_at=execution.started_at,
            completed_at=execution.completed_at,
        )

    @staticmethod
    def _node(execution: WorkflowExecution, node: WorkflowNodeExecution) -> NodeReport:
        output = node.output if isinstance(node.output, dict) else {}
        request = _prepared_request(execution.snapshot, node.node_id)
        return NodeReport(
            id=node.id,
            node_id=node.node_id,
            node_type=node.node_type,
            name=node.name,
            status=node.status,
            attempts=node.attempts,
            duration_ms=_duration_ms(node.started_at, node.completed_at),
            request=request,
            response=_response(node.node_type, output),
            extraction=cast(JsonValue, output) if node.node_type == "extract" else None,
            assertion=cast(JsonValue, output) if node.node_type == "assert" else None,
            input_mappings=cast(JsonValue, output.get("input_mappings")),
            error_code=node.error_code,
            error_message=node.error_message,
        )

    @staticmethod
    def _trend_point(day: date, executions: list[WorkflowExecution]) -> TrendPoint:
        total = len(executions)
        durations = [
            duration
            for item in executions
            if (duration := _duration_ms(item.started_at, item.completed_at)) is not None
        ]
        passed = sum(item.status == "passed" for item in executions)
        return TrendPoint(
            date=day,
            total=total,
            passed=passed,
            failed=sum(item.status == "failed" for item in executions),
            cancelled=sum(item.status == "cancelled" for item in executions),
            pass_rate=round(passed * 100 / total, 2) if total else 0.0,
            average_duration_ms=round(sum(durations) / len(durations), 2) if durations else 0.0,
        )


def _prepared_request(snapshot: dict[str, object], node_id: str) -> JsonValue:
    apis = snapshot.get("apis")
    if not isinstance(apis, dict):
        return None
    api = apis.get(node_id)
    if not isinstance(api, dict):
        return None
    return cast(JsonValue, api.get("prepared_request"))


def _response(node_type: str, output: dict[str, object]) -> JsonValue:
    if node_type != "api":
        return None
    return cast(
        JsonValue,
        {
            key: value
            for key, value in output.items()
            if key in {"status_code", "headers", "body", "size_bytes"}
        },
    )


def _workflow_version(snapshot: dict[str, object]) -> int:
    workflow = snapshot.get("workflow")
    version = workflow.get("version") if isinstance(workflow, dict) else None
    return version if isinstance(version, int) else 0


def _duration_ms(started_at: datetime | None, completed_at: datetime | None) -> float | None:
    if started_at is None or completed_at is None:
        return None
    return round((_as_utc(completed_at) - _as_utc(started_at)).total_seconds() * 1000, 2)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _date_range(days: int) -> list[date]:
    today = datetime.now(UTC).date()
    return [today - timedelta(days=offset) for offset in reversed(range(days))]


def _render_html(detail: ExecutionReportDetail) -> str:
    summary = detail.summary
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(node.name)}</td>"
        f"<td>{html.escape(node.node_type)}</td>"
        f"<td>{html.escape(node.status)}</td>"
        f"<td>{node.attempts}</td>"
        f"<td>{html.escape(node.error_message or '')}</td>"
        "</tr>"
        for node in detail.nodes
    )
    payload = html.escape(
        json.dumps(
            {
                "context": detail.context,
                "nodes": [
                    {
                        "name": node.name,
                        "request": node.request,
                        "response": node.response,
                        "extraction": node.extraction,
                        "assertion": node.assertion,
                    }
                    for node in detail.nodes
                ],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>FlowTest 测试报告</title><style>"
        "body{font-family:system-ui;margin:32px;color:#172033}"
        "table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #d9e2f2;padding:8px;text-align:left}"
        "th{background:#eef4ff}pre{background:#f6f8fb;padding:16px;white-space:pre-wrap}"
        ".passed{color:#168a45}.failed{color:#c93535}</style></head><body>"
        f"<h1>FlowTest 测试报告</h1><p>工作流: {html.escape(summary.workflow_name)} "
        f'v{summary.workflow_version}</p><p>状态: <strong class="{html.escape(summary.status)}">'
        f"{html.escape(summary.status)}</strong> · 执行 ID: {summary.id}</p>"
        f"<p>节点: {summary.total_nodes} · 通过: {summary.passed_nodes} · "
        f"失败: {summary.failed_nodes} · 耗时: {summary.duration_ms or 0} ms</p>"
        "<h2>步骤</h2><table><thead><tr><th>名称</th><th>类型</th><th>状态</th>"
        f"<th>尝试</th><th>错误</th></tr></thead><tbody>{rows}</tbody></table>"
        f"<h2>脱敏详情</h2><pre>{payload}</pre></body></html>"
    )
