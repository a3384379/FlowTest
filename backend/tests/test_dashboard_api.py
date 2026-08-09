from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.domain.access import ProjectRole
from app.main import app
from app.models import Base
from app.models.access import Project, ProjectMember, User
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.executions import APICallExecution
from app.models.workflows import Workflow, WorkflowExecution, WorkflowVersion

ADMIN_PASSWORD = "admin-password-123!"
VIEWER_PASSWORD = "viewer-password-123!"


@dataclass(frozen=True, slots=True)
class DashboardTestContext:
    client: AsyncClient
    visible_project_id: UUID
    hidden_project_id: UUID


@pytest.fixture
async def dashboard_context() -> AsyncIterator[DashboardTestContext]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        visible_project_id, hidden_project_id = await _seed_dashboard(session)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield DashboardTestContext(client, visible_project_id, hidden_project_id)
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_uses_real_accessible_assets_and_executions(
    dashboard_context: DashboardTestContext,
) -> None:
    headers = await _login_headers(
        dashboard_context.client,
        email="viewer@example.com",
        password=VIEWER_PASSWORD,
    )
    summary = await dashboard_context.client.get("/api/v1/dashboard/summary", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["project_count"] == 1
    assert summary.json()["api_count"] == 1
    assert summary.json()["workflow_count"] == 1
    assert summary.json()["today_total"] == 2
    assert summary.json()["today_passed"] == 1
    assert summary.json()["today_failed"] == 1
    assert summary.json()["pass_rate"] == 50.0
    assert len(summary.json()["trend"]) == 7

    recent = await dashboard_context.client.get(
        "/api/v1/dashboard/recent-executions?page_size=10", headers=headers
    )
    assert recent.status_code == 200
    assert recent.json()["total"] == 2
    assert {item["kind"] for item in recent.json()["items"]} == {"api", "workflow"}
    assert {item["project_id"] for item in recent.json()["items"]} == {
        str(dashboard_context.visible_project_id)
    }


@pytest.mark.asyncio
async def test_dashboard_project_scope_preserves_project_isolation(
    dashboard_context: DashboardTestContext,
) -> None:
    viewer_headers = await _login_headers(
        dashboard_context.client,
        email="viewer@example.com",
        password=VIEWER_PASSWORD,
    )
    hidden = await dashboard_context.client.get(
        "/api/v1/dashboard/summary",
        params={"project_id": str(dashboard_context.hidden_project_id)},
        headers=viewer_headers,
    )
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    admin_headers = await _login_headers(
        dashboard_context.client,
        email="admin@example.com",
        password=ADMIN_PASSWORD,
    )
    global_summary = await dashboard_context.client.get(
        "/api/v1/dashboard/summary", headers=admin_headers
    )
    assert global_summary.status_code == 200
    assert global_summary.json()["project_count"] == 2
    assert global_summary.json()["api_count"] == 2
    assert global_summary.json()["workflow_count"] == 2


async def _seed_dashboard(session: AsyncSession) -> tuple[UUID, UUID]:
    admin = _user("admin@example.com", ADMIN_PASSWORD, system_admin=True)
    viewer = _user("viewer@example.com", VIEWER_PASSWORD, system_admin=False)
    visible = _project("Visible", admin.id)
    hidden = _project("Hidden", admin.id)
    session.add_all(
        [
            admin,
            viewer,
            visible,
            hidden,
            ProjectMember(
                project_id=visible.id,
                user_id=viewer.id,
                role=ProjectRole.VIEWER,
            ),
        ]
    )
    now = datetime.now(UTC)
    _add_project_activity(
        session,
        visible,
        admin,
        now,
        api_status="passed",
        workflow_status="failed",
    )
    _add_project_activity(
        session,
        hidden,
        admin,
        now - timedelta(minutes=1),
        api_status="passed",
        workflow_status="passed",
    )
    await session.commit()
    return visible.id, hidden.id


def _add_project_activity(
    session: AsyncSession,
    project: Project,
    actor: User,
    started_at: datetime,
    *,
    api_status: str,
    workflow_status: str,
) -> None:
    environment = Environment(
        id=uuid4(),
        project_id=project.id,
        name="Test",
        base_url="https://example.com",
        variables={},
        headers={},
        created_by_id=actor.id,
    )
    definition = APIDefinition(
        id=uuid4(),
        project_id=project.id,
        name="Health API",
        description="",
        current_version=1,
        is_active=True,
        created_by_id=actor.id,
    )
    api_version = APIVersion(
        id=uuid4(),
        api_definition_id=definition.id,
        version=1,
        method="GET",
        path="/health",
        query_parameters=[],
        headers={},
        body_kind="none",
        body=None,
        auth_kind="none",
        auth_config={},
        created_by_id=actor.id,
    )
    workflow = Workflow(
        id=uuid4(),
        project_id=project.id,
        name="Health Workflow",
        description="",
        draft_definition=_workflow_definition(),
        draft_revision=1,
        current_version=1,
        created_by_id=actor.id,
    )
    workflow_version = WorkflowVersion(
        id=uuid4(),
        workflow_id=workflow.id,
        version=1,
        definition=_workflow_definition(),
        fingerprint="a" * 64,
        created_by_id=actor.id,
        published_at=started_at,
    )
    completed_at = started_at + timedelta(milliseconds=25)
    session.add_all(
        [
            environment,
            definition,
            api_version,
            workflow,
            workflow_version,
            APICallExecution(
                project_id=project.id,
                api_definition_id=definition.id,
                api_version_id=api_version.id,
                environment_id=environment.id,
                triggered_by_id=actor.id,
                status=api_status,
                request_method="GET",
                request_url="https://example.com/health",
                request_headers={},
                request_body=None,
                response_status=200,
                response_headers={},
                response_body={"ok": True},
                response_artifact_id=None,
                response_size_bytes=11,
                elapsed_ms=25,
                error_code=None,
                error_message=None,
                started_at=started_at,
                completed_at=completed_at,
            ),
            WorkflowExecution(
                project_id=project.id,
                workflow_id=workflow.id,
                workflow_version_id=workflow_version.id,
                environment_id=environment.id,
                triggered_by_id=actor.id,
                parent_execution_id=None,
                dataset_row_index=None,
                status=workflow_status,
                snapshot={},
                context={},
                error_code="ASSERTION_FAILED" if workflow_status == "failed" else None,
                error_message="failed" if workflow_status == "failed" else None,
                cancel_requested_at=None,
                started_at=started_at,
                completed_at=completed_at,
                run_payload_ciphertext=None,
                run_payload_nonce=None,
            ),
        ]
    )


def _user(email: str, password: str, *, system_admin: bool) -> User:
    return User(
        id=uuid4(),
        email=email,
        display_name=email.split("@", maxsplit=1)[0],
        password_hash=password_service.hash(password),
        is_active=True,
        is_system_admin=system_admin,
        requires_password_change=False,
    )


def _project(name: str, creator_id: UUID) -> Project:
    return Project(
        id=uuid4(),
        name=name,
        description="",
        variables={},
        headers={},
        outbound_allowed_hosts=[],
        outbound_allowed_private_cidrs=[],
        retention_days=90,
        created_by_id=creator_id,
    )


def _workflow_definition() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "variables": {},
        "nodes": [],
        "edges": [],
        "settings": {
            "fail_fast": True,
            "concurrency": 20,
            "default_timeout_seconds": 30,
        },
    }


async def _login_headers(client: AsyncClient, *, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
