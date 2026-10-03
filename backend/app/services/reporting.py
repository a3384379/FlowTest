import html
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID

from pydantic import BaseModel, JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.reporting import FailureCategory, classify_failure
from app.engine.results import NodeObservation, NodeResult
from app.models.access import User
from app.models.artifacts import Artifact
from app.models.workflows import Workflow, WorkflowExecution, WorkflowNodeExecution
from app.repositories.durable_execution import DurableExecutionRepository
from app.repositories.reporting import ReportingRepository
from app.schemas.durable_execution import ExecutionCheckpointResponse
from app.services.artifacts import ArtifactService
from app.services.audit import AuditService
from app.services.projects import ProjectService


@dataclass(frozen=True, slots=True)
class ExecutionReportSummary:
    id: UUID
    workflow_id: UUID | None
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
    observations: list[NodeObservation]
    request: JsonValue
    response: JsonValue
    extraction: JsonValue
    assertion: JsonValue
    input_mappings: JsonValue
    error_code: str | None
    error_message: str | None
    output: JsonValue = None
    result: NodeResult | None = None


@dataclass(frozen=True, slots=True)
class ExecutionReportDetail:
    summary: ExecutionReportSummary
    nodes: list[NodeReport]
    context: dict[str, JsonValue]
    dataset_children: list[ExecutionReportSummary]


@dataclass(frozen=True, slots=True)
class ExportControlRecord:
    node_id: str
    kind: str
    ordinal: int
    status: str
    test_verdict: str
    payload: JsonValue


@dataclass(frozen=True, slots=True)
class ExecutionExportDetail(ExecutionReportDetail):
    snapshot: dict[str, JsonValue]
    control_records: list[ExportControlRecord]
    checkpoints: list[ExecutionCheckpointResponse]
    dataset_evidence: list["ExecutionExportDetail"]


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
        self._durable = DurableExecutionRepository(session)
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
        children = await self._reports.list_children(execution.id, project_id=project_id)
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
        detail = await self._export_detail(
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

    async def _export_detail(
        self, *, actor: User, project_id: UUID, execution_id: UUID
    ) -> ExecutionExportDetail:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._export_execution(project_id, execution_id, set(), 0)

    async def _export_execution(
        self, project_id: UUID, execution_id: UUID, visited: set[UUID], depth: int
    ) -> ExecutionExportDetail:
        if execution_id in visited or len(visited) >= 1000 or depth > 16:
            raise AppError(
                code="REPORT_EXPORT_LIMIT_EXCEEDED",
                message="报告执行树循环或超过导出边界; 请分别导出子运行",
                status_code=422,
            )
        visited.add(execution_id)
        execution = await self._execution(project_id, execution_id)
        nodes = await self._reports.list_nodes(execution_id)
        children = await self._reports.list_children(execution_id, project_id=project_id)
        records = await self._reports.list_control_records(execution_id)
        checkpoints = await self._durable.list_checkpoints(execution_id)
        return ExecutionExportDetail(
            summary=await self._summary(execution, nodes),
            nodes=[self._node(execution, item) for item in nodes],
            context=cast(dict[str, JsonValue], execution.context),
            dataset_children=[await self._summary(child) for child in children],
            snapshot=cast(dict[str, JsonValue], execution.snapshot),
            control_records=[
                ExportControlRecord(
                    node_id=item.node_id,
                    kind=item.kind,
                    ordinal=item.ordinal,
                    status=item.status,
                    test_verdict=item.test_verdict,
                    payload=cast(JsonValue, item.payload),
                )
                for item in records
            ],
            checkpoints=[ExecutionCheckpointResponse.model_validate(item) for item in checkpoints],
            dataset_evidence=[
                await self._export_execution(project_id, child.id, visited, depth + 1)
                for child in children
            ],
        )

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
        workflow = (
            await self._reports.get_workflow(execution.workflow_id)
            if execution.workflow_id is not None
            else None
        )
        records = nodes if nodes is not None else await self._reports.list_nodes(execution.id)
        return ExecutionReportSummary(
            id=execution.id,
            workflow_id=execution.workflow_id,
            workflow_name=_report_workflow_name(execution, workflow),
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
        stored_output = node.output_summary if node.output_summary is not None else node.output
        output = stored_output if isinstance(stored_output, dict) else {}
        stored_result = node.result_summary if node.result_summary is not None else node.result
        result = _node_result(stored_result)
        observations = list(result.observations) if result is not None else []
        latest = observations[-1] if observations else None
        request = (
            cast(JsonValue, latest.request.model_dump(mode="json"))
            if latest is not None
            else _prepared_request(execution.snapshot, node.node_id)
        )
        response = (
            cast(JsonValue, latest.response.model_dump(mode="json"))
            if latest is not None and latest.response is not None
            else _response(node.node_type, output)
        )
        return NodeReport(
            id=node.id,
            node_id=node.node_id,
            node_type=node.node_type,
            name=node.name,
            status=node.status,
            attempts=node.attempts,
            duration_ms=_duration_ms(node.started_at, node.completed_at),
            observations=observations,
            request=request,
            response=response,
            extraction=cast(JsonValue, output) if node.node_type == "extract" else None,
            assertion=_node_assertion(node.node_type, output, result),
            input_mappings=cast(JsonValue, output.get("input_mappings")),
            error_code=node.error_code,
            error_message=node.error_message,
            output=cast(JsonValue, stored_output),
            result=result,
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


def _node_result(result: dict[str, object] | None) -> NodeResult | None:
    if result is None:
        return None
    try:
        return NodeResult.model_validate(result)
    except ValueError:
        # Legacy results can be incomplete; retain their separate stored output.
        return None


def _node_assertion(
    node_type: str, output: dict[str, object], result: NodeResult | None
) -> JsonValue:
    if node_type == "assert":
        return cast(JsonValue, output)
    if result is not None and result.assertions:
        return [cast(JsonValue, item.model_dump(mode="json")) for item in result.assertions]
    return None


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
            asdict(detail),
            ensure_ascii=False,
            indent=2,
            default=_export_value,
        )
    )
    duration = "未提供" if summary.duration_ms is None else f"{summary.duration_ms} ms"
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
        f"失败: {summary.failed_nodes} · 耗时: {duration}</p>"
        "<h2>步骤</h2><table><thead><tr><th>名称</th><th>类型</th><th>状态</th>"
        f"<th>尝试</th><th>错误</th></tr></thead><tbody>{rows}</tbody></table>"
        f"<h2>冻结执行证据</h2><pre>{payload}</pre></body></html>"
    )


def _export_value(value: object) -> JsonValue:
    if isinstance(value, BaseModel):
        return cast(JsonValue, value.model_dump(mode="json"))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Unsupported report value: {type(value).__name__}")


def _report_workflow_name(execution: WorkflowExecution, workflow: Workflow | None) -> str:
    metadata = execution.snapshot.get("workflow")
    if isinstance(metadata, dict):
        name = metadata.get("name")
        if isinstance(name, str) and name.strip():
            return name
    if execution.run_purpose == "preview":
        return "Sandbox Preview"
    if workflow is None:
        return "已删除工作流(历史名称未提供)"
    return f"{workflow.name}(当前名称; 历史名称未提供)"
