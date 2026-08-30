import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Delete

from app.core.storage import object_storage
from app.models.access import AuditLog, Project, RefreshSession
from app.models.artifacts import Artifact
from app.models.data_sources import MockRequestLog, MockService
from app.models.executions import APICallExecution
from app.models.governance import IdempotencyRecord, OrganizationGovernance
from app.models.imports import ImportRun
from app.models.reporting import NotificationDelivery
from app.models.sandbox_preview import SandboxPreviewApproval
from app.models.tasking import TestPlanRun
from app.models.test_contexts import TestContext, TestContextRevision
from app.models.workflows import WorkflowExecution

logger = logging.getLogger(__name__)


class ObjectDeleter(Protocol):
    async def delete(self, *, key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class RetentionCleanupSummary:
    projects_scanned: int = 0
    api_executions_deleted: int = 0
    workflow_executions_deleted: int = 0
    test_plan_runs_deleted: int = 0
    notification_deliveries_deleted: int = 0
    mock_request_logs_deleted: int = 0
    artifacts_deleted: int = 0
    storage_failures: int = 0
    idempotency_records_deleted: int = 0
    import_previews_deleted: int = 0
    refresh_sessions_deleted: int = 0
    audit_logs_deleted: int = 0
    test_contexts_deleted: int = 0


class RetentionCleanupService:
    def __init__(
        self,
        session: AsyncSession,
        storage: ObjectDeleter = object_storage,
    ) -> None:
        self._session = session
        self._storage = storage

    async def cleanup(self, now: datetime | None = None) -> RetentionCleanupSummary:
        cleanup_at = now or datetime.now(UTC)
        projects = list((await self._session.scalars(select(Project))).all())
        totals = _MutableCleanupSummary(projects_scanned=len(projects))
        for project in projects:
            cutoff = cleanup_at - timedelta(days=project.retention_days)
            await self._cleanup_project(project.id, cutoff, totals)
        totals.idempotency_records_deleted += await self._delete(
            delete(IdempotencyRecord).where(IdempotencyRecord.expires_at < cleanup_at)
        )
        totals.import_previews_deleted += await self._delete(
            delete(ImportRun).where(
                ImportRun.status == "preview",
                ImportRun.created_at < cleanup_at - timedelta(days=1),
            )
        )
        totals.refresh_sessions_deleted += await self._delete(
            delete(RefreshSession).where(RefreshSession.expires_at < cleanup_at)
        )
        await self._delete(
            delete(SandboxPreviewApproval).where(
                SandboxPreviewApproval.consumed_at.is_(None),
                SandboxPreviewApproval.expires_at < cleanup_at,
            )
        )
        referenced_context = exists(
            select(TestContextRevision.id)
            .join(
                SandboxPreviewApproval,
                SandboxPreviewApproval.context_revision_id == TestContextRevision.id,
            )
            .where(TestContextRevision.context_id == TestContext.id)
        )
        totals.test_contexts_deleted += await self._delete(
            delete(TestContext).where(
                TestContext.expires_at < cleanup_at,
                ~referenced_context,
            )
        )
        governance = list((await self._session.scalars(select(OrganizationGovernance))).all())
        for policy in governance:
            totals.audit_logs_deleted += await self._delete(
                delete(AuditLog).where(
                    AuditLog.organization_id == policy.organization_id,
                    AuditLog.created_at < cleanup_at - timedelta(days=policy.audit_retention_days),
                )
            )
        await self._session.commit()
        return totals.freeze()

    async def _cleanup_project(
        self,
        project_id: UUID,
        cutoff: datetime,
        totals: "_MutableCleanupSummary",
    ) -> None:
        artifacts = list(
            (
                await self._session.scalars(
                    select(Artifact).where(
                        Artifact.project_id == project_id,
                        Artifact.created_at < cutoff,
                    )
                )
            ).all()
        )
        for artifact in artifacts:
            try:
                await self._storage.delete(key=artifact.object_key)
            except Exception as error:
                totals.storage_failures += 1
                logger.warning(
                    "Retention object deletion failed: %s",
                    type(error).__name__,
                    extra={"artifact_id": str(artifact.id)},
                )
                continue
            await self._session.delete(artifact)
            totals.artifacts_deleted += 1
        await self._session.flush()
        totals.notification_deliveries_deleted += await self._delete(
            delete(NotificationDelivery).where(
                NotificationDelivery.project_id == project_id,
                NotificationDelivery.created_at < cutoff,
            )
        )
        totals.mock_request_logs_deleted += await self._delete(
            delete(MockRequestLog).where(
                MockRequestLog.mock_service_id.in_(
                    select(MockService.id).where(MockService.project_id == project_id)
                ),
                MockRequestLog.created_at < cutoff,
            )
        )
        totals.test_plan_runs_deleted += await self._delete(
            delete(TestPlanRun).where(
                TestPlanRun.project_id == project_id,
                TestPlanRun.completed_at.is_not(None),
                TestPlanRun.completed_at < cutoff,
            )
        )
        totals.workflow_executions_deleted += await self._delete_workflow_executions(
            project_id,
            cutoff,
        )
        totals.api_executions_deleted += await self._delete(
            delete(APICallExecution).where(
                APICallExecution.project_id == project_id,
                APICallExecution.completed_at.is_not(None),
                APICallExecution.completed_at < cutoff,
            )
        )

    async def _delete(self, statement: Delete) -> int:
        result = await self._session.execute(statement)
        return int(getattr(result, "rowcount", 0) or 0)

    async def _delete_workflow_executions(
        self,
        project_id: UUID,
        cutoff: datetime,
    ) -> int:
        expired = (
            WorkflowExecution.project_id == project_id,
            WorkflowExecution.completed_at.is_not(None),
            WorkflowExecution.completed_at < cutoff,
        )
        surviving_preview = exists(
            select(WorkflowExecution.id).where(
                WorkflowExecution.preview_approval_id == SandboxPreviewApproval.id,
                or_(
                    WorkflowExecution.completed_at.is_(None),
                    WorkflowExecution.completed_at >= cutoff,
                ),
            )
        )
        approval_ids = list(
            (
                await self._session.scalars(
                    select(SandboxPreviewApproval.id).where(
                        SandboxPreviewApproval.project_id == project_id,
                        SandboxPreviewApproval.execution_id.in_(
                            select(WorkflowExecution.id).where(*expired)
                        ),
                        ~surviving_preview,
                    )
                )
            ).all()
        )
        if approval_ids:
            await self._session.execute(
                update(SandboxPreviewApproval)
                .where(SandboxPreviewApproval.id.in_(approval_ids))
                .values(consumed_at=None, execution_id=None)
            )
        deleted = await self._delete(
            delete(WorkflowExecution).where(
                *expired,
                or_(
                    WorkflowExecution.run_purpose == "standard",
                    WorkflowExecution.preview_approval_id.in_(approval_ids),
                ),
            )
        )
        if approval_ids:
            await self._delete(
                delete(SandboxPreviewApproval).where(SandboxPreviewApproval.id.in_(approval_ids))
            )
        return deleted


@dataclass(slots=True)
class _MutableCleanupSummary:
    projects_scanned: int = 0
    api_executions_deleted: int = 0
    workflow_executions_deleted: int = 0
    test_plan_runs_deleted: int = 0
    notification_deliveries_deleted: int = 0
    mock_request_logs_deleted: int = 0
    artifacts_deleted: int = 0
    storage_failures: int = 0
    idempotency_records_deleted: int = 0
    import_previews_deleted: int = 0
    refresh_sessions_deleted: int = 0
    audit_logs_deleted: int = 0
    test_contexts_deleted: int = 0

    def freeze(self) -> RetentionCleanupSummary:
        return RetentionCleanupSummary(**asdict(self))
