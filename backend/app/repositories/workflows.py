from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.control_reports import project_control_report
from app.models.workflows import (
    Workflow,
    WorkflowControlRecord,
    WorkflowExecution,
    WorkflowNodeExecution,
    WorkflowVersion,
)

WorkflowEntity = (
    Workflow | WorkflowVersion | WorkflowExecution | WorkflowNodeExecution | WorkflowControlRecord
)


@dataclass(frozen=True)
class WorkflowNodeExecutionReport:
    id: UUID
    workflow_execution_id: UUID
    node_id: str
    node_type: str
    name: str
    phase: str
    best_effort: bool
    status: str
    attempts: int
    output: Any
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime


@dataclass(frozen=True)
class WorkflowExecutionReport:
    id: UUID
    project_id: UUID
    redaction_mode: str
    redaction_policy_version: int
    workflow_id: UUID | None
    workflow_version_id: UUID | None
    environment_id: UUID
    triggered_by_id: UUID
    parent_execution_id: UUID | None
    dataset_row_index: int | None
    derived_from_execution_id: UUID | None
    rerun_loop_node_id: str | None
    rerun_input_indices: list[int] | None
    run_purpose: str
    source_change_set_id: UUID | None
    preview_approval_id: UUID | None
    preview_budget: dict[str, Any]
    preview_evidence: dict[str, Any]
    status: str
    main_status: str | None
    cleanup_status: str | None
    cleanup_report: dict[str, Any]
    snapshot: dict[str, Any]
    context: dict[str, Any]
    error_code: str | None
    error_message: str | None
    cancel_requested_at: datetime | None
    force_cancel_requested_at: datetime | None
    force_cancel_reason: str | None
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class WorkflowControlRecordSummary:
    ordinal: int
    status: str
    test_verdict: str


class WorkflowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: WorkflowEntity) -> None:
        self._session.add(entity)

    def add_all(self, entities: Sequence[WorkflowEntity]) -> None:
        self._session.add_all(entities)

    async def get(self, workflow_id: UUID) -> Workflow | None:
        return await self._session.get(Workflow, workflow_id)

    async def get_for_update(self, workflow_id: UUID) -> Workflow | None:
        result = await self._session.execute(
            select(Workflow)
            .where(Workflow.id == workflow_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_version(self, version_id: UUID) -> WorkflowVersion | None:
        return await self._session.get(WorkflowVersion, version_id)

    async def find_version(self, workflow_id: UUID, version: int) -> WorkflowVersion | None:
        result = await self._session.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def list_versions(self, workflow_id: UUID) -> list[WorkflowVersion]:
        return list(
            (
                await self._session.scalars(
                    select(WorkflowVersion)
                    .where(WorkflowVersion.workflow_id == workflow_id)
                    .order_by(WorkflowVersion.version.desc())
                )
            ).all()
        )

    async def list_workflows(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[Workflow], int]:
        items = list(
            (
                await self._session.scalars(
                    select(Workflow)
                    .where(
                        Workflow.project_id == project_id,
                        Workflow.archived_at.is_(None),
                    )
                    .order_by(Workflow.updated_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count())
            .select_from(Workflow)
            .where(Workflow.project_id == project_id, Workflow.archived_at.is_(None))
        )
        return items, int(total or 0)

    async def name_exists(
        self,
        *,
        project_id: UUID,
        name: str,
        excluding_id: UUID | None = None,
    ) -> bool:
        query = select(Workflow.id).where(
            Workflow.project_id == project_id,
            Workflow.name == name,
        )
        if excluding_id is not None:
            query = query.where(Workflow.id != excluding_id)
        return await self._session.scalar(query) is not None

    async def get_execution(self, execution_id: UUID) -> WorkflowExecution | None:
        return await self._session.get(WorkflowExecution, execution_id)

    async def get_execution_report(
        self, *, project_id: UUID, execution_id: UUID
    ) -> WorkflowExecutionReport | None:
        row = (
            await self._session.execute(
                select(*self._execution_report_columns()).where(
                    WorkflowExecution.id == execution_id,
                    WorkflowExecution.project_id == project_id,
                )
            )
        ).one_or_none()
        return WorkflowExecutionReport(*row) if row is not None else None

    async def list_child_execution_reports(
        self, execution_id: UUID
    ) -> list[WorkflowExecutionReport]:
        rows = (
            await self._session.execute(
                select(*self._execution_report_columns())
                .where(WorkflowExecution.parent_execution_id == execution_id)
                .order_by(WorkflowExecution.dataset_row_index)
            )
        ).all()
        return [WorkflowExecutionReport(*row) for row in rows]

    @staticmethod
    def _execution_report_columns() -> tuple[Any, ...]:
        execution = WorkflowExecution
        context = case(
            (execution.context_summary.is_not(None), execution.context_summary),
            else_=execution.context,
        )
        return (
            execution.id,
            execution.project_id,
            execution.redaction_mode,
            execution.redaction_policy_version,
            execution.workflow_id,
            execution.workflow_version_id,
            execution.environment_id,
            execution.triggered_by_id,
            execution.parent_execution_id,
            execution.dataset_row_index,
            execution.derived_from_execution_id,
            execution.rerun_loop_node_id,
            execution.rerun_input_indices,
            execution.run_purpose,
            execution.source_change_set_id,
            execution.preview_approval_id,
            execution.preview_budget,
            execution.preview_evidence,
            execution.status,
            execution.main_status,
            execution.cleanup_status,
            execution.cleanup_report,
            execution.snapshot,
            context,
            execution.error_code,
            execution.error_message,
            execution.cancel_requested_at,
            execution.force_cancel_requested_at,
            execution.force_cancel_reason,
            execution.started_at,
            execution.completed_at,
        )

    async def list_executions(
        self,
        *,
        project_id: UUID,
        workflow_id: UUID | None,
        offset: int,
        limit: int,
    ) -> tuple[list[WorkflowExecution], int]:
        criteria = [
            WorkflowExecution.project_id == project_id,
            WorkflowExecution.parent_execution_id.is_(None),
        ]
        if workflow_id is not None:
            criteria.append(WorkflowExecution.workflow_id == workflow_id)
        items = list(
            (
                await self._session.scalars(
                    select(WorkflowExecution)
                    .where(*criteria)
                    .order_by(WorkflowExecution.started_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(WorkflowExecution).where(*criteria)
        )
        return items, int(total or 0)

    async def list_child_executions(self, execution_id: UUID) -> list[WorkflowExecution]:
        return list(
            (
                await self._session.scalars(
                    select(WorkflowExecution)
                    .where(WorkflowExecution.parent_execution_id == execution_id)
                    .order_by(WorkflowExecution.dataset_row_index)
                )
            ).all()
        )

    async def request_child_cancellation(self, execution_id: UUID, requested_at: datetime) -> None:
        await self._session.execute(
            update(WorkflowExecution)
            .where(
                WorkflowExecution.parent_execution_id == execution_id,
                WorkflowExecution.status.in_(("queued", "running")),
                WorkflowExecution.cancel_requested_at.is_(None),
            )
            .values(cancel_requested_at=requested_at)
        )

    async def list_node_executions(self, execution_id: UUID) -> list[WorkflowNodeExecution]:
        return list(
            (
                await self._session.scalars(
                    select(WorkflowNodeExecution)
                    .where(WorkflowNodeExecution.workflow_execution_id == execution_id)
                    .order_by(WorkflowNodeExecution.created_at)
                )
            ).all()
        )

    async def list_node_execution_reports(
        self, execution_id: UUID
    ) -> list[WorkflowNodeExecutionReport]:
        node = WorkflowNodeExecution
        output = case((node.output_summary.is_not(None), node.output_summary), else_=node.output)
        result = case((node.result_summary.is_not(None), node.result_summary), else_=node.result)
        rows = (
            await self._session.execute(
                select(
                    node.id,
                    node.workflow_execution_id,
                    node.node_id,
                    node.node_type,
                    node.name,
                    node.phase,
                    node.best_effort,
                    node.status,
                    node.attempts,
                    output,
                    result,
                    node.error_code,
                    node.error_message,
                    node.started_at,
                    node.completed_at,
                )
                .where(node.workflow_execution_id == execution_id)
                .order_by(node.created_at)
            )
        ).all()
        return [WorkflowNodeExecutionReport(*row) for row in rows]

    async def list_control_records(
        self,
        *,
        execution_id: UUID,
        node_id: str,
        kind: str,
        test_verdict: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[WorkflowControlRecordSummary], int]:
        record = WorkflowControlRecord
        criteria = [
            record.workflow_execution_id == execution_id,
            record.node_id == node_id,
            record.kind == kind,
        ]
        if test_verdict is not None:
            criteria.append(record.test_verdict == test_verdict)
        rows = (
            await self._session.execute(
                select(record.ordinal, record.status, record.test_verdict)
                .where(*criteria)
                .order_by(record.ordinal)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        total = await self._session.scalar(
            select(func.count()).select_from(record).where(*criteria)
        )
        return [WorkflowControlRecordSummary(*row) for row in rows], int(total or 0)

    async def get_control_record(
        self, *, execution_id: UUID, node_id: str, kind: str, ordinal: int
    ) -> WorkflowControlRecord | None:
        result = await self._session.execute(
            select(WorkflowControlRecord).where(
                WorkflowControlRecord.workflow_execution_id == execution_id,
                WorkflowControlRecord.node_id == node_id,
                WorkflowControlRecord.kind == kind,
                WorkflowControlRecord.ordinal == ordinal,
            )
        )
        return result.scalar_one_or_none()

    async def replace_node_executions(
        self, execution_id: UUID, entities: Sequence[WorkflowNodeExecution]
    ) -> None:
        await self._session.execute(
            delete(WorkflowControlRecord).where(
                WorkflowControlRecord.workflow_execution_id == execution_id
            )
        )
        await self._session.execute(
            delete(WorkflowNodeExecution).where(
                WorkflowNodeExecution.workflow_execution_id == execution_id
            )
        )
        self.add_all(entities)
        records: list[WorkflowControlRecord] = []
        for node in entities:
            projection = project_control_report(node.output, node.result)
            if projection is None:
                continue
            node.output_summary = projection.output_summary
            node.result_summary = projection.result_summary
            records.extend(
                WorkflowControlRecord(
                    workflow_execution_id=execution_id,
                    node_id=node.node_id,
                    kind=item.kind,
                    ordinal=item.ordinal,
                    status=item.status,
                    test_verdict=item.test_verdict,
                    payload=item.payload,
                )
                for item in projection.items
            )
        self.add_all(records)
