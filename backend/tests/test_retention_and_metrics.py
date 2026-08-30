from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.logging import redact
from app.models import Base
from app.models.access import AuditLog, Project, User
from app.models.ai import AIChangeSet
from app.models.api_assets import Environment
from app.models.artifacts import Artifact
from app.models.data_sources import MockRequestLog, MockService
from app.models.governance import IdempotencyRecord, OrganizationGovernance
from app.models.organizations import Organization
from app.models.sandbox_preview import SandboxPreviewApproval
from app.models.test_contexts import TestContext as ContextModel
from app.models.test_contexts import TestContextRevision as ContextRevisionModel
from app.models.workflows import WorkflowExecution
from app.observability.metrics import MetricsRegistry, normalize_path, render_metrics
from app.observability.task_metrics import TaskMetricsSnapshot
from app.services.retention import RetentionCleanupService
from app.services.workflow_runtime import _response_output


class RecordingStorage:
    def __init__(self, failing_keys: set[str] | None = None) -> None:
        self.deleted: list[str] = []
        self._failing_keys = failing_keys or set()

    async def delete(self, *, key: str) -> None:
        if key in self._failing_keys:
            raise OSError("storage unavailable")
        self.deleted.append(key)


async def test_retention_cleanup_removes_expired_state_and_preserves_failures() -> None:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = datetime(2026, 8, 9, tzinfo=UTC)
    old = now - timedelta(days=31)
    async with session_maker() as session:
        user = User(
            email="retention@example.com",
            display_name="Retention",
            password_hash="unused",
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        session.add(user)
        await session.flush()
        organization = Organization(
            name="Retention organization",
            slug="retention-organization",
            description="",
            enabled=True,
            created_by_id=user.id,
        )
        session.add(organization)
        await session.flush()
        project = Project(
            organization_id=organization.id,
            name="Retention project",
            description="",
            retention_days=30,
            created_by_id=user.id,
        )
        session.add(project)
        await session.flush()
        environment = Environment(
            project_id=project.id,
            name="Retention sandbox",
            base_url="https://sandbox.example.test",
            classification="sandbox",
            variables={},
            headers={},
            created_by_id=user.id,
        )
        preview_context = ContextModel(
            organization_id=organization.id,
            project_id=project.id,
            name="Retained preview context",
            objective="Verify preview retention",
            target_environment_id=None,
            status="expired",
            current_revision=1,
            created_by_type="user",
            created_by_id=user.id,
            expires_at=old,
            closed_at=None,
        )
        change_set = AIChangeSet(
            project_id=project.id,
            title="Retained preview",
            status="accepted",
            source_snapshot={},
            source_fingerprint="a" * 64,
            source_type="mcp",
            source_ref=None,
            actor_type="user",
            actor_id=user.id,
            created_by_id=user.id,
        )
        session.add_all([environment, preview_context, change_set])
        await session.flush()
        revision = ContextRevisionModel(
            context_id=preview_context.id,
            revision=1,
            repository_revisions=[],
            contract_revisions=[],
            data_profile_revisions=[],
            existing_test_revision=None,
            knowledge_snapshot={},
            completeness={},
            conflict_snapshot={},
            evidence_fingerprints=[],
            fingerprint="b" * 64,
            created_by_type="user",
            created_by_id=user.id,
        )
        session.add(revision)
        await session.flush()
        approval = SandboxPreviewApproval(
            organization_id=organization.id,
            project_id=project.id,
            change_set_id=change_set.id,
            environment_id=environment.id,
            environment_fingerprint="c" * 64,
            target_snapshot_fingerprint="d" * 64,
            runtime_input_fingerprint="e" * 64,
            executor_kind="user",
            executor_id=user.id,
            proposal_fingerprint="f" * 64,
            context_revision_id=revision.id,
            context_fingerprint="1" * 64,
            budget={"max_requests": 2},
            expires_at=old,
            consumed_at=None,
            execution_id=None,
            created_by_id=user.id,
        )
        session.add(approval)
        await session.flush()
        preview_execution = WorkflowExecution(
            project_id=project.id,
            workflow_id=None,
            workflow_version_id=None,
            environment_id=environment.id,
            triggered_by_id=user.id,
            parent_execution_id=None,
            dataset_row_index=None,
            run_purpose="preview",
            source_change_set_id=change_set.id,
            preview_approval_id=approval.id,
            preview_budget={"max_requests": 2},
            preview_evidence={},
            status="passed",
            main_status="passed",
            cleanup_status="passed",
            cleanup_report={},
            snapshot={},
            context={},
            error_code=None,
            error_message=None,
            cancel_requested_at=None,
            force_cancel_requested_at=None,
            force_cancel_reason=None,
            started_at=old,
            completed_at=old,
        )
        session.add(preview_execution)
        await session.flush()
        approval.consumed_at = old
        approval.execution_id = preview_execution.id
        session.add(
            OrganizationGovernance(
                organization_id=organization.id,
                audit_retention_days=30,
                quota_policies={},
                runner_policy={},
            )
        )
        session.add_all(
            [
                AuditLog(
                    actor_user_id=user.id,
                    organization_id=organization.id,
                    project_id=None,
                    action="old.audit",
                    resource_type="retention",
                    resource_id=organization.id,
                    details={},
                    created_at=old,
                ),
                AuditLog(
                    actor_user_id=user.id,
                    organization_id=organization.id,
                    project_id=None,
                    action="current.audit",
                    resource_type="retention",
                    resource_id=organization.id,
                    details={},
                    created_at=now,
                ),
            ]
        )
        mock_service = MockService(
            project_id=project.id,
            name="Retention Mock",
            slug="retention-mock",
            description="",
            is_enabled=True,
            created_by_id=user.id,
        )
        session.add(mock_service)
        await session.flush()
        session.add_all(
            [
                _artifact(project.id, user.id, "expired.bin", old),
                _artifact(project.id, user.id, "failed.bin", old),
                _artifact(project.id, user.id, "current.bin", now),
                IdempotencyRecord(
                    project_id=project.id,
                    actor_key="user",
                    operation="execute",
                    idempotency_key="expired-key",
                    request_hash="a" * 64,
                    status="completed",
                    response_status=202,
                    response_body={"id": "result"},
                    expires_at=now - timedelta(seconds=1),
                ),
                ContextModel(
                    organization_id=organization.id,
                    project_id=project.id,
                    name="Expired context",
                    objective="Verify retention",
                    target_environment_id=None,
                    status="expired",
                    current_revision=1,
                    created_by_type="user",
                    created_by_id=user.id,
                    expires_at=now - timedelta(seconds=1),
                    closed_at=None,
                ),
                _mock_log(mock_service.id, old),
                _mock_log(mock_service.id, now),
            ]
        )
        await session.commit()

        storage = RecordingStorage({"failed.bin"})
        summary = await RetentionCleanupService(session, storage).cleanup(now)
        remaining = set((await session.scalars(select(Artifact.object_key))).all())
        idempotency = list((await session.scalars(select(IdempotencyRecord))).all())
        mock_logs = list((await session.scalars(select(MockRequestLog))).all())
        audit_logs = list((await session.scalars(select(AuditLog))).all())
        contexts = list((await session.scalars(select(ContextModel))).all())
        preview_executions = list((await session.scalars(select(WorkflowExecution))).all())
        preview_approvals = list((await session.scalars(select(SandboxPreviewApproval))).all())

    assert summary.projects_scanned == 1
    assert summary.artifacts_deleted == 1
    assert summary.storage_failures == 1
    assert summary.idempotency_records_deleted == 1
    assert summary.audit_logs_deleted == 1
    assert summary.mock_request_logs_deleted == 1
    assert summary.test_contexts_deleted == 2
    assert summary.workflow_executions_deleted == 1
    assert storage.deleted == ["expired.bin"]
    assert remaining == {"failed.bin", "current.bin"}
    assert idempotency == []
    assert len(mock_logs) == 1
    assert [log.action for log in audit_logs] == ["current.audit"]
    assert contexts == []
    assert preview_executions == []
    assert preview_approvals == []
    await engine.dispose()


async def test_metrics_are_low_cardinality_and_include_execution_gauges() -> None:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    registry = MetricsRegistry()
    registry.observe_request(
        method="get",
        path="/api/v1/projects/123e4567-e89b-12d3-a456-426614174000/reports",
        status=200,
        duration=0.025,
    )
    async with session_maker() as session:
        rendered = await render_metrics(registry, session, AvailableTaskMetrics())

    assert (
        normalize_path("/api/v1/projects/123e4567-e89b-12d3-a456-426614174000/reports")
        == "/api/v1/projects/{id}/reports"
    )
    assert 'path="/api/v1/projects/{id}/reports"' in rendered
    assert 'status="200"' in rendered
    assert "flowtest_execution_records" in rendered
    assert 'flowtest_celery_queue_depth{queue="general"} 7' in rendered
    assert "flowtest_celery_workers_active 3" in rendered
    assert 'flowtest_celery_tasks_total{status="succeeded"} 11' in rendered
    assert "flowtest_celery_metrics_available 1" in rendered
    unavailable = await render_metrics(registry, cast(AsyncSession, UnavailableSession()))
    assert "flowtest_execution_metrics_available 0" in unavailable
    task_unavailable = await render_metrics(registry, session, UnavailableTaskMetrics())
    assert "flowtest_celery_metrics_available 0" in task_unavailable
    await engine.dispose()


class UnavailableSession:
    async def execute(self, _statement: Select[tuple[object, ...]]) -> None:
        raise OSError("database is unavailable")


class AvailableTaskMetrics:
    async def read(self) -> TaskMetricsSnapshot:
        return TaskMetricsSnapshot(
            queue_depths={"general": 7, "data": 2, "ai": 0},
            active_workers=3,
            task_counts={"succeeded": 11, "failed": 1},
        )


class UnavailableTaskMetrics:
    async def read(self) -> TaskMetricsSnapshot:
        raise OSError("Redis is unavailable")


def test_workflow_response_secret_is_available_only_before_persistence_redaction() -> None:
    import httpx

    runtime_output = _response_output(
        httpx.Response(
            200,
            headers={"Set-Cookie": "session=private"},
            json={"data": {"token": "runtime-token"}},
        )
    )
    assert runtime_output["body"]["data"]["token"] == "runtime-token"
    persisted = redact(runtime_output)
    assert persisted["body"]["data"]["token"] == "***"
    assert persisted["headers"]["set-cookie"] == "***"


def _artifact(project_id: UUID, user_id: UUID, key: str, created_at: datetime) -> Artifact:
    return Artifact(
        project_id=project_id,
        object_key=key,
        filename=key,
        content_type="application/octet-stream",
        size_bytes=1,
        sha256="a" * 64,
        purpose="report",
        created_by_id=user_id,
        created_at=created_at,
        updated_at=created_at,
    )


def _mock_log(service_id: UUID, created_at: datetime) -> MockRequestLog:
    return MockRequestLog(
        mock_service_id=service_id,
        mock_route_id=None,
        method="GET",
        path="/retention",
        query_parameters={},
        headers={},
        body=None,
        matched=False,
        scenario=None,
        response_status=404,
        duration_ms=1,
        created_at=created_at,
        updated_at=created_at,
    )
