from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reporting import NotificationDelivery, NotificationWebhook
from app.models.workflows import Workflow, WorkflowExecution, WorkflowNodeExecution


class ReportingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        status: str | None = None,
    ) -> tuple[list[WorkflowExecution], int]:
        criteria = [
            WorkflowExecution.project_id == project_id,
            WorkflowExecution.parent_execution_id.is_(None),
        ]
        if status is not None:
            criteria.append(WorkflowExecution.status == status)
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

    async def list_executions_since(
        self, *, project_id: UUID, since: datetime
    ) -> list[WorkflowExecution]:
        return list(
            (
                await self._session.scalars(
                    select(WorkflowExecution).where(
                        WorkflowExecution.project_id == project_id,
                        WorkflowExecution.parent_execution_id.is_(None),
                        WorkflowExecution.started_at >= since,
                    )
                )
            ).all()
        )

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

    async def list_children(self, execution_id: UUID) -> list[WorkflowExecution]:
        return list(
            (
                await self._session.scalars(
                    select(WorkflowExecution)
                    .where(WorkflowExecution.parent_execution_id == execution_id)
                    .order_by(WorkflowExecution.dataset_row_index)
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
