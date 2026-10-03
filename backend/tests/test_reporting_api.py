import hashlib
import hmac
import html
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.core.security import password_service
from app.core.storage import StoredObject
from app.domain.reporting import FailureCategory, classify_failure
from app.engine.contracts import NodeStatus
from app.engine.results import (
    HttpRequestSnapshot,
    HttpResponseSnapshot,
    NodeAssertion,
    NodeObservation,
    NodeResult,
    NodeResultError,
)
from app.main import app
from app.models import Base
from app.models.access import Project, User
from app.models.api_assets import Environment
from app.models.durable_execution import ExecutionCheckpoint
from app.models.workflows import (
    Workflow,
    WorkflowControlRecord,
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


@pytest.mark.asyncio
@pytest.mark.parametrize(("depth", "cycle"), [(2, True), (18, False)])
async def test_report_export_rejects_cyclic_or_excessively_deep_execution_trees(
    reporting_context: ReportingContext, depth: int, cycle: bool
) -> None:
    async with reporting_context.session_maker() as session:
        execution = await session.get(WorkflowExecution, reporting_context.execution_id)
        assert execution is not None
        parent_id = execution.id
        for index in range(depth):
            child = WorkflowExecution(
                project_id=execution.project_id,
                workflow_id=execution.workflow_id,
                workflow_version_id=execution.workflow_version_id,
                environment_id=execution.environment_id,
                triggered_by_id=execution.triggered_by_id,
                parent_execution_id=parent_id,
                dataset_row_index=index,
                status="passed",
                snapshot=execution.snapshot,
                context={},
                started_at=execution.started_at,
                completed_at=execution.completed_at,
            )
            session.add(child)
            await session.flush()
            parent_id = child.id
        if cycle:
            execution.parent_execution_id = parent_id
            execution.dataset_row_index = depth
        await session.commit()
    headers = await _login_headers(reporting_context.client)
    response = await reporting_context.client.post(
        f"/api/v1/projects/{reporting_context.project_id}/reports/executions/"
        f"{reporting_context.execution_id}/exports/html",
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "REPORT_EXPORT_LIMIT_EXCEEDED"
    assert response.json()["error"]["trace_id"]


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
        "workflow": {
            "id": str(workflow_id),
            "name": "失败分类流程",
            "version_id": str(version_id),
            "version": 1,
        },
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


async def _seed_report_evidence(context: ReportingContext) -> UUID:
    now = datetime.now(UTC)
    observations = tuple(
        NodeObservation(
            attempt=attempt,
            request=HttpRequestSnapshot(method="GET", url="https://api.example.test/amount"),
            response=HttpResponseSnapshot(status_code=200, body={"marker": marker}, size_bytes=20),
            duration_ms=1,
            started_at=now,
            completed_at=now,
        )
        for attempt, marker in ((1, "first-observation"), (2, "last-observation"))
    )
    result = NodeResult(
        status=NodeStatus.FAILED,
        assertions=(NodeAssertion(name="amount", passed=False, expected=29900, actual=29901),),
        observations=observations,
        error=NodeResultError(code="ASSERTION_FAILED", message="金额断言失败"),
    )
    async with context.session_maker() as session:
        execution = await session.get(WorkflowExecution, context.execution_id)
        assert execution is not None
        execution.completed_at = None
        node = await session.scalar(
            select(WorkflowNodeExecution).where(
                WorkflowNodeExecution.workflow_execution_id == execution.id,
                WorkflowNodeExecution.node_id == "api",
            )
        )
        assert node is not None
        node.result = result.model_dump(mode="json")
        node.attempts = 2
        node.output = {"input_mappings": [{"source_node_id": "mapping-marker"}]}
        child = WorkflowExecution(
            project_id=execution.project_id,
            workflow_id=execution.workflow_id,
            workflow_version_id=execution.workflow_version_id,
            environment_id=execution.environment_id,
            triggered_by_id=execution.triggered_by_id,
            parent_execution_id=execution.id,
            dataset_row_index=0,
            status="failed",
            snapshot=execution.snapshot,
            context={},
            started_at=now,
            completed_at=now,
        )
        session.add(child)
        await session.flush()
        session.add(
            WorkflowNodeExecution(
                workflow_execution_id=child.id,
                node_id="child-api",
                node_type="api",
                name="子运行请求",
                status="failed",
                attempts=2,
                output={"frozen_child_marker": "retained-child-body"},
                result=result.model_dump(mode="json"),
                started_at=now,
                completed_at=now,
            )
        )
        session.add(
            WorkflowNodeExecution(
                workflow_execution_id=execution.id,
                node_id="loop",
                node_type="capability",
                name="循环证据",
                status="failed",
                attempts=1,
                output={"report_kind": "iteration", "report_paged": True, "record_count": 3},
                started_at=now,
                completed_at=now,
            )
        )
        instance_id = "__nested_request__:export-marker"
        session.add_all(
            WorkflowControlRecord(
                workflow_execution_id=execution.id,
                node_id="loop",
                kind="iteration",
                ordinal=ordinal,
                status="failed" if ordinal == 2 else "passed",
                test_verdict="failed" if ordinal == 2 else "passed",
                payload={
                    "input_index": ordinal,
                    "nodes": [{"node_id": "check", "instance_id": instance_id}]
                    if ordinal == 2
                    else [],
                },
            )
            for ordinal in range(3)
        )
        session.add_all(
            ExecutionCheckpoint(
                project_id=execution.project_id,
                execution_id=execution.id,
                node_id=instance_id,
                node_type="api",
                node_name="嵌套请求",
                phase="main",
                best_effort=False,
                attempt=attempt,
                status="failed",
                input_hash="a" * 64,
                output_digest="b" * 64,
                output={"amount": 29901},
                result=result.model_dump(mode="json"),
                started_at=now,
                finished_at=now,
            )
            for attempt in (1, 2)
        )
        await session.commit()
        return child.id


@pytest.mark.asyncio
async def test_report_preserves_protocol_assertions_and_control_output(
    reporting_context: ReportingContext,
) -> None:
    await _seed_report_evidence(reporting_context)
    headers = await _login_headers(reporting_context.client)
    response = await reporting_context.client.get(
        f"/api/v1/projects/{reporting_context.project_id}/reports/executions/"
        f"{reporting_context.execution_id}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    nodes = {node["node_id"]: node for node in response.json()["nodes"]}
    assert nodes["api"]["assertion"] == [
        {"name": "amount", "passed": False, "expected": 29900, "actual": 29901, "message": ""}
    ]
    assert nodes["api"]["result"]["observations"][0]["attempt"] == 1
    assert nodes["loop"]["output"]["record_count"] == 3


@pytest.mark.asyncio
async def test_html_export_preserves_all_frozen_evidence_and_unknown_duration(
    reporting_context: ReportingContext,
) -> None:
    child_id = await _seed_report_evidence(reporting_context)
    headers = await _login_headers(reporting_context.client)
    exported = await reporting_context.client.post(
        f"/api/v1/projects/{reporting_context.project_id}/reports/executions/"
        f"{reporting_context.execution_id}/exports/html",
        headers=headers,
    )
    assert exported.status_code == 201, exported.text
    downloaded = await reporting_context.client.get(
        f"/api/v1/projects/{reporting_context.project_id}/files/{exported.json()['id']}",
        headers=headers,
    )
    assert downloaded.status_code == 200
    evidence = json.loads(html.unescape(downloaded.text.split("<pre>")[1].split("</pre>")[0]))
    api_node = next(node for node in evidence["nodes"] if node["node_id"] == "api")
    assert [item["attempt"] for item in api_node["observations"]] == [1, 2]
    assert api_node["observations"][0]["response"]["body"]["marker"] == "first-observation"
    assert api_node["input_mappings"][0]["source_node_id"] == "mapping-marker"
    assert evidence["dataset_children"][0]["id"] == str(child_id)
    child = evidence["dataset_evidence"][0]
    assert child["summary"]["id"] == str(child_id)
    assert child["nodes"][0]["result"]["assertions"][0]["actual"] == 29901
    assert len(child["nodes"][0]["observations"]) == 2
    assert child["nodes"][0]["output"]["frozen_child_marker"] == "retained-child-body"
    assert child["snapshot"]["workflow"]["name"] == "失败分类流程"
    assert evidence["snapshot"]["workflow"]["version"] == 1
    assert (
        evidence["control_records"][2]["payload"]["nodes"][0]["instance_id"]
        == "__nested_request__:export-marker"
    )
    assert [item["attempt"] for item in evidence["checkpoints"]] == [1, 2]
    assert evidence["checkpoints"][0]["result"]["assertions"][0]["actual"] == 29901
    assert evidence["summary"]["duration_ms"] is None
    assert "耗时: 未提供" in downloaded.text
    assert "耗时: 0 ms" not in downloaded.text


async def test_report_name_uses_frozen_metadata_and_marks_legacy_current_names(
    reporting_context: ReportingContext,
) -> None:
    headers = await _login_headers(reporting_context.client)
    path = (
        f"/api/v1/projects/{reporting_context.project_id}/reports/executions/"
        f"{reporting_context.execution_id}"
    )
    async with reporting_context.session_maker() as session:
        execution = await session.get(WorkflowExecution, reporting_context.execution_id)
        assert execution is not None
        workflow = await session.get(Workflow, execution.workflow_id)
        assert workflow is not None
        workflow.name = "后续改名"
        await session.commit()
    frozen = await reporting_context.client.get(path, headers=headers)
    assert frozen.json()["summary"]["workflow_name"] == "失败分类流程"
    async with reporting_context.session_maker() as session:
        execution = await session.get(WorkflowExecution, reporting_context.execution_id)
        assert execution is not None
        snapshot = dict(execution.snapshot)
        metadata = dict(snapshot["workflow"])
        metadata.pop("name")
        snapshot["workflow"] = metadata
        execution.snapshot = snapshot
        await session.commit()
    legacy = await reporting_context.client.get(path, headers=headers)
    assert legacy.json()["summary"]["workflow_name"] == "后续改名(当前名称; 历史名称未提供)"
