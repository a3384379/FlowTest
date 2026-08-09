import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.core.security import password_service
from app.core.storage import StoredObject
from app.domain.reporting import FailureCategory, classify_failure
from app.main import app
from app.models import Base
from app.models.access import Project, User
from app.models.api_assets import Environment
from app.models.workflows import (
    Workflow,
    WorkflowExecution,
    WorkflowNodeExecution,
    WorkflowVersion,
)
from app.services.notifications import NotificationDeliveryService

ADMIN_EMAIL = "report-admin@example.com"
ADMIN_PASSWORD = "report-password-123!"


@dataclass(frozen=True, slots=True)
class ReportingContext:
    client: AsyncClient
    session_maker: async_sessionmaker[AsyncSession]
    project_id: UUID
    execution_id: UUID


@pytest.fixture
async def reporting_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[ReportingContext]:
    storage = MemoryObjectStorage()
    monkeypatch.setattr("app.services.artifacts.object_storage", storage)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'reporting.db'}",
        connect_args={"check_same_thread": False},
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    project_id, execution_id = await _seed(session_maker)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield ReportingContext(client, session_maker, project_id, execution_id)
    app.dependency_overrides.clear()
    await engine.dispose()


class MemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}

    async def put(self, *, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = StoredObject(content=content, content_type=content_type)

    async def get(self, *, key: str) -> StoredObject:
        return self.objects[key]

    async def delete(self, *, key: str) -> None:
        self.objects.pop(key, None)


@pytest.mark.asyncio
async def test_report_list_detail_trend_and_html_export(
    reporting_context: ReportingContext,
) -> None:
    client = reporting_context.client
    headers = await _login_headers(client)
    project_id = reporting_context.project_id
    execution_id = reporting_context.execution_id

    listed = await client.get(
        f"/api/v1/projects/{project_id}/reports/executions",
        headers=headers,
        params={"status": "failed"},
    )
    assert listed.status_code == 200, listed.text
    summary = listed.json()["items"][0]
    assert summary["workflow_name"] == "失败分类流程"
    assert summary["failure_category"] == "http_server"
    assert summary["total_nodes"] == 3
    assert summary["passed_nodes"] == 1
    assert summary["failed_nodes"] == 1
    assert summary["skipped_nodes"] == 1

    detail = await client.get(
        f"/api/v1/projects/{project_id}/reports/executions/{execution_id}",
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    api_step = payload["nodes"][1]
    assert api_step["request"]["headers"]["Authorization"] == "***"
    assert api_step["response"]["status_code"] == 503
    assert api_step["input_mappings"][0]["source_node_id"] == "start"
    assert "raw-secret" not in json.dumps(payload)

    trends = await client.get(
        f"/api/v1/projects/{project_id}/reports/trends",
        headers=headers,
        params={"days": 7},
    )
    assert trends.status_code == 200
    assert len(trends.json()["points"]) == 7
    assert trends.json()["points"][-1]["failed"] == 1
    assert trends.json()["failures"] == [{"category": "http_server", "count": 1}]

    exported = await client.post(
        f"/api/v1/projects/{project_id}/reports/executions/{execution_id}/exports/html",
        headers=headers,
    )
    assert exported.status_code == 201, exported.text
    artifact = exported.json()
    assert artifact["purpose"] == "report"
    downloaded = await client.get(
        f"/api/v1/projects/{project_id}/files/{artifact['id']}",
        headers=headers,
    )
    assert downloaded.status_code == 200
    assert "FlowTest 测试报告" in downloaded.text
    assert "raw-secret" not in downloaded.text


@respx.mock
@pytest.mark.asyncio
async def test_signed_webhook_secret_is_write_only_and_delivery_is_auditable(
    reporting_context: ReportingContext,
) -> None:
    client = reporting_context.client
    headers = await _login_headers(client)
    project_id = reporting_context.project_id
    execution_id = reporting_context.execution_id
    target = respx.post("https://notify.example.test/flowtest").mock(return_value=Response(204))

    created = await client.post(
        f"/api/v1/projects/{project_id}/notification-webhooks",
        headers=headers,
        json={
            "name": "质量通知",
            "url": "https://notify.example.test/flowtest",
            "events": ["workflow.completed"],
        },
    )
    assert created.status_code == 201, created.text
    secret = created.json()["secret"]
    assert secret.startswith("ftnotify_")

    listed = await client.get(
        f"/api/v1/projects/{project_id}/notification-webhooks",
        headers=headers,
    )
    assert listed.status_code == 200
    assert "secret" not in listed.text
    assert "ciphertext" not in listed.text

    async with reporting_context.session_maker() as session:
        await NotificationDeliveryService(session).deliver_workflow(execution_id)
    assert target.called
    request = target.calls[0].request
    timestamp = request.headers["X-FlowTest-Timestamp"]
    expected = (
        "sha256="
        + hmac.new(
            secret.encode(), timestamp.encode() + b"." + request.content, hashlib.sha256
        ).hexdigest()
    )
    assert hmac.compare_digest(request.headers["X-FlowTest-Signature"], expected)
    assert request.headers["X-FlowTest-Event"] == "workflow.completed"
    assert json.loads(request.content)["failure_category"] == "http_server"

    deliveries = await client.get(
        f"/api/v1/projects/{project_id}/notification-deliveries",
        headers=headers,
    )
    assert deliveries.status_code == 200
    assert deliveries.json()["items"][0]["status"] == "delivered"
    assert deliveries.json()["items"][0]["response_status"] == 204

    disabled = await client.patch(
        f"/api/v1/projects/{project_id}/notification-webhooks/{created.json()['id']}",
        headers=headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    failing_target = respx.post("https://notify.example.test/failing").mock(
        return_value=Response(503)
    )
    updated = await client.patch(
        f"/api/v1/projects/{project_id}/notification-webhooks/{created.json()['id']}",
        headers=headers,
        json={
            "name": "失败通知",
            "url": "https://notify.example.test/failing",
            "events": ["workflow.completed", "test_plan.completed"],
            "enabled": True,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["events"] == ["test_plan.completed", "workflow.completed"]
    async with reporting_context.session_maker() as session:
        await NotificationDeliveryService(session).deliver_workflow(execution_id)
    assert failing_target.called
    failed_deliveries = await client.get(
        f"/api/v1/projects/{project_id}/notification-deliveries",
        headers=headers,
    )
    failed_delivery = next(
        item for item in failed_deliveries.json()["items"] if item["status"] == "failed"
    )
    assert failed_delivery["response_status"] == 503

    missing = await client.patch(
        f"/api/v1/projects/{project_id}/notification-webhooks/00000000-0000-4000-8000-000000000999",
        headers=headers,
        json={"enabled": False},
    )
    assert missing.status_code == 404


@pytest.mark.parametrize(
    ("status", "error_code", "expected"),
    [
        ("passed", None, FailureCategory.NONE),
        ("cancelled", None, FailureCategory.CANCELLED),
        ("failed", "WORKFLOW_ASSERTION_FAILED", FailureCategory.ASSERTION),
        ("failed", "NETWORK_TIMEOUT", FailureCategory.TIMEOUT),
        ("failed", "DNS_REBINDING", FailureCategory.NETWORK),
        ("failed", "HTTP_4XX", FailureCategory.HTTP_CLIENT),
        ("failed", "HTTP_5XX", FailureCategory.HTTP_SERVER),
        ("failed", "INVALID_MAPPING", FailureCategory.CONFIGURATION),
        ("failed", "WORKFLOW_RUNTIME_ERROR", FailureCategory.RUNTIME),
    ],
)
def test_failure_classification(
    status: str,
    error_code: str | None,
    expected: FailureCategory,
) -> None:
    assert classify_failure(status=status, error_code=error_code) is expected


async def _seed(
    session_maker: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    now = datetime.now(UTC)
    async with session_maker() as session:
        user = User(
            email=ADMIN_EMAIL,
            display_name="Report administrator",
            password_hash=password_service.hash(ADMIN_PASSWORD),
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        session.add(user)
        await session.flush()
        project = Project(name="报告项目", description="", created_by_id=user.id)
        session.add(project)
        await session.flush()
        environment = Environment(
            project_id=project.id,
            name="测试环境",
            base_url="https://api.example.test",
            variables={},
            headers={},
            created_by_id=user.id,
        )
        session.add(environment)
        await session.flush()
        workflow = Workflow(
            project_id=project.id,
            folder_id=None,
            name="失败分类流程",
            description="",
            draft_definition={},
            draft_revision=1,
            current_version=1,
            created_by_id=user.id,
        )
        session.add(workflow)
        await session.flush()
        version = WorkflowVersion(
            workflow_id=workflow.id,
            version=1,
            definition={},
            fingerprint="a" * 64,
            created_by_id=user.id,
            published_at=now,
        )
        session.add(version)
        await session.flush()
        execution = WorkflowExecution(
            project_id=project.id,
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            environment_id=environment.id,
            triggered_by_id=user.id,
            parent_execution_id=None,
            dataset_row_index=None,
            status="failed",
            snapshot=_snapshot(workflow.id, version.id),
            context={"variables": {"token": "***"}},
            error_code="HTTP_5XX",
            error_message="目标接口返回 503",
            cancel_requested_at=None,
            started_at=now - timedelta(seconds=2),
            completed_at=now,
            run_payload_ciphertext=None,
            run_payload_nonce=None,
        )
        session.add(execution)
        await session.flush()
        session.add_all(_nodes(execution.id, now))
        await session.commit()
        return project.id, execution.id


def _snapshot(workflow_id: UUID, version_id: UUID) -> dict[str, Any]:
    return {
        "workflow": {"id": str(workflow_id), "version_id": str(version_id), "version": 1},
        "apis": {
            "api": {
                "prepared_request": {
                    "method": "GET",
                    "url": "https://api.example.test/failure",
                    "headers": {"Authorization": "***"},
                    "body": None,
                }
            }
        },
    }


def _nodes(execution_id: UUID, now: datetime) -> list[WorkflowNodeExecution]:
    common = {
        "workflow_execution_id": execution_id,
        "attempts": 1,
        "started_at": now - timedelta(seconds=2),
        "completed_at": now,
    }
    return [
        WorkflowNodeExecution(
            **common,
            node_id="start",
            node_type="start",
            name="开始",
            status="passed",
            output=None,
            error_code=None,
            error_message=None,
        ),
        WorkflowNodeExecution(
            **common,
            node_id="api",
            node_type="api",
            name="失败请求",
            status="failed",
            output={
                "status_code": 503,
                "headers": {"content-type": "application/json"},
                "body": {"message": "temporarily unavailable"},
                "size_bytes": 38,
                "input_mappings": [{"source_node_id": "start"}],
            },
            error_code="HTTP_5XX",
            error_message="目标接口返回 503",
        ),
        WorkflowNodeExecution(
            **common,
            node_id="end",
            node_type="end",
            name="结束",
            status="skipped",
            output=None,
            error_code=None,
            error_message=None,
        ),
    ]


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
