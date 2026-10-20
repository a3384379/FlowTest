from datetime import datetime
from uuid import UUID

from sqlalchemy import SQLColumnExpression, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.domain.reporting import (
    ReportFilterKind,
    ReportFilterOption,
    ReportScope,
    ReportStatus,
    ReportTrendRecord,
)
from app.models.api_assets import Environment
from app.models.reporting import NotificationDelivery, NotificationWebhook
from app.models.tasking import TestPlan, TestPlanRun, TestPlanRunItem
from app.models.test_assets import TestCase
from app.models.workflows import (
    Workflow,
    WorkflowControlRecord,
    WorkflowExecution,
    WorkflowNodeExecution,
)
from app.repositories.catalog_paging import ranked_catalog_page


def _plan_match(
    project_id: UUID, plan_id: UUID | SQLColumnExpression[UUID] | None = None
) -> ColumnElement[bool]:
    query = (
        select(TestPlanRunItem.id)
        .join(TestPlanRun, TestPlanRun.id == TestPlanRunItem.test_plan_run_id)
        .where(
            TestPlanRun.project_id == project_id,
            or_(
                TestPlanRunItem.id == WorkflowExecution.source_plan_run_item_id,
                and_(
                    WorkflowExecution.source_plan_run_item_id.is_(None),
                    TestPlanRunItem.workflow_execution_id == WorkflowExecution.id,
                ),
            ),
        )
        .correlate(WorkflowExecution, TestPlan)
    )
    if plan_id is not None:
        query = query.where(TestPlanRun.test_plan_id == plan_id)
    return exists(query)


def _source_match(project_id: UUID, source: str) -> ColumnElement[bool]:
    if source == "preview":
        return WorkflowExecution.run_purpose == "preview"
    if source == "plan":
        return (WorkflowExecution.run_purpose == "standard") & (
            (WorkflowExecution.source_trigger == "plan") | _plan_match(project_id)
        )
    if source == "case":
        return (
            (WorkflowExecution.run_purpose == "standard")
            & (WorkflowExecution.source_case_id.is_not(None))
            & (WorkflowExecution.source_trigger == "direct")
            & ~_plan_match(project_id)
        )
    return (
        (WorkflowExecution.run_purpose == "standard")
        & WorkflowExecution.source_case_id.is_(None)
        & ~_plan_match(project_id)
    )


def _case_match(project_id: UUID, case_id: UUID | SQLColumnExpression[UUID]) -> ColumnElement[bool]:
    legacy = exists(
        select(TestPlanRunItem.id)
        .join(TestPlanRun, TestPlanRun.id == TestPlanRunItem.test_plan_run_id)
        .where(
            TestPlanRun.project_id == project_id,
            TestPlanRunItem.target_type == "case",
            TestPlanRunItem.target_id == case_id,
            or_(
                TestPlanRunItem.id == WorkflowExecution.source_plan_run_item_id,
                and_(
                    WorkflowExecution.source_plan_run_item_id.is_(None),
                    TestPlanRunItem.workflow_execution_id == WorkflowExecution.id,
                ),
            ),
        )
        .correlate(WorkflowExecution, TestCase)
    )
    return (WorkflowExecution.source_case_id == case_id) | (
        WorkflowExecution.source_case_id.is_(None) & legacy
    )


def _execution_criteria(project_id: UUID, scope: ReportScope) -> list[ColumnElement[bool]]:
    criteria: list[ColumnElement[bool]] = [
        WorkflowExecution.project_id == project_id,
        WorkflowExecution.parent_execution_id.is_(None),
    ]
    for column, value in (
        (WorkflowExecution.status, scope.status),
        (WorkflowExecution.workflow_id, scope.workflow_id),
        (WorkflowExecution.environment_id, scope.environment_id),
    ):
        if value is not None:
            criteria.append(column == value)
    if scope.source_case_id is not None:
        criteria.append(_case_match(project_id, scope.source_case_id))
    if scope.started_from is not None:
        criteria.append(WorkflowExecution.started_at >= scope.started_from)
    if scope.started_until is not None:
        criteria.append(WorkflowExecution.started_at < scope.started_until)
    if scope.source is not None:
        criteria.append(_source_match(project_id, scope.source))
    if scope.source_plan_id is not None:
        criteria.append(_plan_match(project_id, scope.source_plan_id))
    return criteria


class ReportingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_filter_options(
        self,
        *,
        project_id: UUID,
        kind: ReportFilterKind,
        offset: int,
        limit: int,
        search: str,
        selected_id: UUID | None,
    ) -> tuple[list[ReportFilterOption], int]:
        model: type[Workflow] | type[Environment] | type[TestCase] | type[TestPlan]
        if kind == "plan":
            model = TestPlan
            history = (
                select(WorkflowExecution.id)
                .where(
                    *_execution_criteria(project_id, ReportScope()),
                    _plan_match(project_id, TestPlan.id),
                )
                .correlate(TestPlan)
            )
        else:
            if kind == "workflow":
                model, column = Workflow, WorkflowExecution.workflow_id
            elif kind == "environment":
                model, column = Environment, WorkflowExecution.environment_id
            else:
                model, column = TestCase, WorkflowExecution.source_case_id
            match = _case_match(project_id, TestCase.id) if kind == "case" else column == model.id
            history = (
                select(WorkflowExecution.id)
                .where(*_execution_criteria(project_id, ReportScope()), match)
                .correlate(model)
            )
        criteria = [model.project_id == project_id, exists(history)]
        if selected_id is not None:
            criteria.append(model.id == selected_id)
        if search:
            criteria.append(model.name.icontains(search, autoescape=True))
        query = select(model.id, model.name).where(*criteria)
        total = await self._session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await self._session.execute(
            query.order_by(model.name, model.id).offset(offset).limit(limit)
        )
        return [ReportFilterOption(identifier, name) for identifier, name in rows], int(total or 0)

    def add(self, entity: NotificationWebhook | NotificationDelivery) -> None:
        self._session.add(entity)

    async def get_execution(self, execution_id: UUID) -> WorkflowExecution | None:
        return await self._session.get(WorkflowExecution, execution_id)

    async def get_workflow(self, workflow_id: UUID) -> Workflow | None:
        return await self._session.get(Workflow, workflow_id)

    async def list_executions(
        self,
        *,
        project_id: UUID,
        offset: int,
        limit: int,
        status: ReportStatus | None = None,
        scope: ReportScope | None = None,
    ) -> tuple[list[WorkflowExecution], int]:
        criteria = _execution_criteria(project_id, scope or ReportScope(status=status))
        ranked = (
            select(
                WorkflowExecution.id.label("item_id"),
                func.row_number()
                .over(order_by=(WorkflowExecution.started_at.desc(), WorkflowExecution.id.desc()))
                .label("position"),
            )
            .where(*criteria)
            .cte()
        )
        page = ranked_catalog_page(ranked, offset, limit)
        rows = (
            await self._session.execute(
                select(WorkflowExecution, page.c.total)
                .select_from(page)
                .outerjoin(WorkflowExecution, WorkflowExecution.id == page.c.item_id)
                .order_by(page.c.position)
            )
        ).all()
        return [row[0] for row in rows if row[0] is not None], int(rows[0][1])

    async def list_executions_since(
        self, *, project_id: UUID, since: datetime, scope: ReportScope | None = None
    ) -> list[ReportTrendRecord]:
        rows = await self._session.execute(
            select(
                WorkflowExecution.status,
                WorkflowExecution.error_code,
                WorkflowExecution.started_at,
                WorkflowExecution.completed_at,
            ).where(
                *_execution_criteria(project_id, scope or ReportScope()),
                WorkflowExecution.started_at >= since,
            )
        )
        return [
            ReportTrendRecord(status, error, started, completed)
            for status, error, started, completed in rows
        ]

    async def list_nodes(self, execution_id: UUID) -> list[WorkflowNodeExecution]:
        return list(
            (
                await self._session.scalars(
                    select(WorkflowNodeExecution)
                    .where(WorkflowNodeExecution.workflow_execution_id == execution_id)
                    .order_by(WorkflowNodeExecution.created_at)
                )
            ).all()
        )

    async def list_children(
        self, execution_id: UUID, *, project_id: UUID
    ) -> list[WorkflowExecution]:
        return list(
            (
                await self._session.scalars(
                    select(WorkflowExecution)
                    .where(
                        WorkflowExecution.parent_execution_id == execution_id,
                        WorkflowExecution.project_id == project_id,
                    )
                    .order_by(WorkflowExecution.dataset_row_index)
                )
            ).all()
        )

    async def list_control_records(self, execution_id: UUID) -> list[WorkflowControlRecord]:
        return list(
            (
                await self._session.scalars(
                    select(WorkflowControlRecord)
                    .where(WorkflowControlRecord.workflow_execution_id == execution_id)
                    .order_by(
                        WorkflowControlRecord.node_id,
                        WorkflowControlRecord.kind,
                        WorkflowControlRecord.ordinal,
                    )
                )
            ).all()
        )

    async def get_webhook(self, webhook_id: UUID) -> NotificationWebhook | None:
        return await self._session.get(NotificationWebhook, webhook_id)

    async def list_webhooks(self, project_id: UUID) -> list[NotificationWebhook]:
        return list(
            (
                await self._session.scalars(
                    select(NotificationWebhook)
                    .where(NotificationWebhook.project_id == project_id)
                    .order_by(NotificationWebhook.created_at)
                )
            ).all()
        )

    async def list_enabled_webhooks(
        self, *, project_id: UUID, event_type: str
    ) -> list[NotificationWebhook]:
        candidates = list(
            (
                await self._session.scalars(
                    select(NotificationWebhook).where(
                        NotificationWebhook.project_id == project_id,
                        NotificationWebhook.enabled.is_(True),
                    )
                )
            ).all()
        )
        return [item for item in candidates if event_type in item.events]

    async def list_deliveries(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[NotificationDelivery], int]:
        items = list(
            (
                await self._session.scalars(
                    select(NotificationDelivery)
                    .where(NotificationDelivery.project_id == project_id)
                    .order_by(NotificationDelivery.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count())
            .select_from(NotificationDelivery)
            .where(NotificationDelivery.project_id == project_id)
        )
        return items, int(total or 0)
