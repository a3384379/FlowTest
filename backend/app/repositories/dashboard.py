from dataclasses import dataclass
from datetime import date, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.models.access import Project, ProjectMember
from app.models.api_assets import APIDefinition
from app.models.executions import APICallExecution
from app.models.workflows import Workflow, WorkflowExecution


@dataclass(frozen=True, slots=True)
class DashboardCounts:
    projects: int
    apis: int
    workflows: int


@dataclass(frozen=True, slots=True)
class DashboardExecutionRecord:
    id: UUID
    project_id: UUID
    project_name: str
    kind: str
    target_id: UUID
    target_name: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    duration_ms: float | None


@dataclass(frozen=True, slots=True)
class DashboardActivityCount:
    day: date
    status: str
    count: int


class DashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def accessible_project_ids(
        self,
        *,
        user_id: UUID,
        system_admin: bool,
        organization_id: UUID | None = None,
    ) -> list[UUID]:
        query = select(Project.id)
        if not system_admin:
            query = query.join(ProjectMember).where(ProjectMember.user_id == user_id)
        if organization_id is not None:
            query = query.where(
                or_(
                    Project.organization_id == organization_id,
                    Project.organization_id.is_(None),
                )
            )
        return list((await self._session.scalars(query)).all())

    async def counts(self, project_ids: list[UUID]) -> DashboardCounts:
        if not project_ids:
            return DashboardCounts(projects=0, apis=0, workflows=0)
        api_count = await self._session.scalar(
            select(func.count())
            .select_from(APIDefinition)
            .where(
                APIDefinition.project_id.in_(project_ids),
                APIDefinition.is_active.is_(True),
            )
        )
        workflow_count = await self._session.scalar(
            select(func.count()).select_from(Workflow).where(Workflow.project_id.in_(project_ids))
        )
        return DashboardCounts(
            projects=len(project_ids),
            apis=int(api_count or 0),
            workflows=int(workflow_count or 0),
        )

    async def activity(
        self,
        *,
        project_ids: list[UUID],
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[DashboardExecutionRecord]:
        if not project_ids:
            return []
        api_query = (
            select(APICallExecution, Project.name, APIDefinition.name)
            .join(Project, Project.id == APICallExecution.project_id)
            .join(APIDefinition, APIDefinition.id == APICallExecution.api_definition_id)
            .where(APICallExecution.project_id.in_(project_ids))
            .order_by(APICallExecution.started_at.desc())
        )
        workflow_query = (
            select(WorkflowExecution, Project.name, Workflow.name)
            .join(Project, Project.id == WorkflowExecution.project_id)
            .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
            .where(
                WorkflowExecution.project_id.in_(project_ids),
                WorkflowExecution.parent_execution_id.is_(None),
            )
            .order_by(WorkflowExecution.started_at.desc())
        )
        if since is not None:
            api_query = api_query.where(APICallExecution.started_at >= since)
            workflow_query = workflow_query.where(WorkflowExecution.started_at >= since)
        if limit is not None:
            api_query = api_query.limit(limit)
            workflow_query = workflow_query.limit(limit)

        api_rows = (await self._session.execute(api_query)).all()
        workflow_rows = (await self._session.execute(workflow_query)).all()
        records = [
            DashboardExecutionRecord(
                id=execution.id,
                project_id=execution.project_id,
                project_name=project_name,
                kind="api",
                target_id=execution.api_definition_id,
                target_name=target_name,
                status=execution.status,
                started_at=execution.started_at,
                completed_at=execution.completed_at,
                duration_ms=execution.elapsed_ms,
            )
            for execution, project_name, target_name in api_rows
        ]
        records.extend(
            DashboardExecutionRecord(
                id=execution.id,
                project_id=execution.project_id,
                project_name=project_name,
                kind="workflow",
                target_id=execution.workflow_id,
                target_name=target_name,
                status=execution.status,
                started_at=execution.started_at,
                completed_at=execution.completed_at,
                duration_ms=_duration_ms(execution.started_at, execution.completed_at),
            )
            for execution, project_name, target_name in workflow_rows
        )
        return sorted(records, key=lambda item: item.started_at, reverse=True)[:limit]

    async def activity_counts(
        self,
        *,
        project_ids: list[UUID],
        since: datetime,
    ) -> list[DashboardActivityCount]:
        if not project_ids:
            return []
        api_day = self._local_date_expression(APICallExecution.started_at)
        workflow_day = self._local_date_expression(WorkflowExecution.started_at)
        api_query = (
            select(
                api_day.label("day"),
                APICallExecution.status.label("status"),
                func.count().label("count"),
            )
            .where(
                APICallExecution.project_id.in_(project_ids),
                APICallExecution.started_at >= since,
            )
            .group_by(api_day, APICallExecution.status)
        )
        workflow_query = (
            select(
                workflow_day.label("day"),
                WorkflowExecution.status.label("status"),
                func.count().label("count"),
            )
            .where(
                WorkflowExecution.project_id.in_(project_ids),
                WorkflowExecution.parent_execution_id.is_(None),
                WorkflowExecution.started_at >= since,
            )
            .group_by(workflow_day, WorkflowExecution.status)
        )
        rows = (await self._session.execute(api_query.union_all(workflow_query))).all()
        return [
            DashboardActivityCount(day=_coerce_date(day), status=status, count=int(count))
            for day, status, count in rows
        ]

    def _local_date_expression(
        self,
        column: InstrumentedAttribute[datetime] | ColumnElement[datetime],
    ) -> ColumnElement[date]:
        bind = self._session.get_bind()
        if bind.dialect.name == "postgresql":
            return cast(ColumnElement[date], func.date(func.timezone("Asia/Shanghai", column)))
        return cast(ColumnElement[date], func.date(column, "+8 hours"))

    async def execution_count(self, project_ids: list[UUID]) -> int:
        if not project_ids:
            return 0
        api_count = await self._session.scalar(
            select(func.count())
            .select_from(APICallExecution)
            .where(APICallExecution.project_id.in_(project_ids))
        )
        workflow_count = await self._session.scalar(
            select(func.count())
            .select_from(WorkflowExecution)
            .where(
                WorkflowExecution.project_id.in_(project_ids),
                WorkflowExecution.parent_execution_id.is_(None),
            )
        )
        return int(api_count or 0) + int(workflow_count or 0)


def _duration_ms(started_at: datetime, completed_at: datetime | None) -> float | None:
    if completed_at is None:
        return None
    return (completed_at - started_at).total_seconds() * 1000


def _coerce_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)
