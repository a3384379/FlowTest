from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflows import (
    Workflow,
    WorkflowExecution,
    WorkflowNodeExecution,
    WorkflowVersion,
)

WorkflowEntity = Workflow | WorkflowVersion | WorkflowExecution | WorkflowNodeExecution


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
                    .where(Workflow.project_id == project_id)
                    .order_by(Workflow.updated_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(Workflow).where(Workflow.project_id == project_id)
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

    async def list_executions(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[WorkflowExecution], int]:
        items = list(
            (
                await self._session.scalars(
                    select(WorkflowExecution)
                    .where(
                        WorkflowExecution.project_id == project_id,
                        WorkflowExecution.parent_execution_id.is_(None),
                    )
                    .order_by(WorkflowExecution.started_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count())
            .select_from(WorkflowExecution)
            .where(
                WorkflowExecution.project_id == project_id,
                WorkflowExecution.parent_execution_id.is_(None),
            )
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
