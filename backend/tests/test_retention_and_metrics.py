from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.logging import redact
from app.models import Base
from app.models.access import Project, User
from app.models.artifacts import Artifact
from app.models.data_sources import MockRequestLog, MockService
from app.models.governance import IdempotencyRecord
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
        project = Project(
            name="Retention project",
            description="",
            retention_days=30,
            created_by_id=user.id,
        )
        session.add(project)
        await session.flush()
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

    assert summary.projects_scanned == 1
    assert summary.artifacts_deleted == 1
    assert summary.storage_failures == 1
    assert summary.idempotency_records_deleted == 1
    assert summary.mock_request_logs_deleted == 1
    assert storage.deleted == ["expired.bin"]
    assert remaining == {"failed.bin", "current.bin"}
    assert idempotency == []
    assert len(mock_logs) == 1
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
