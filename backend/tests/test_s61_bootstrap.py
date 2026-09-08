"""S61B MCP bootstrap contract and authorization coverage."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.main import app
from app.models import Base
from app.models.access import Project, User
from app.models.api_assets import Environment
from app.models.governance import OrganizationIdempotencyRecord
from app.models.organizations import Organization
from app.models.service_targets import Service, ServiceEndpoint
from app.services.service_accounts import ServiceAccountService


@pytest.fixture
async def bootstrap_context() -> AsyncIterator[dict[str, Any]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        actor = User(
            email="bootstrap-admin@example.com",
            display_name="Bootstrap administrator",
            password_hash=password_service.hash("unused-password"),
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        organization = Organization(
            name="Bootstrap organization",
            slug=f"bootstrap-{uuid4().hex[:8]}",
            created_by_id=None,
        )
        session.add_all([actor, organization])
        await session.flush()
        organization.created_by_id = actor.id
        issued = await ServiceAccountService(session).create(
            actor=actor,
            organization_id=organization.id,
            name="Bootstrap account",
            account_key="bootstrap-account",
            scopes=["mcp:project:bootstrap"],
            expires_at=None,
            metadata={"purpose": "S61B tests"},
        )
        denied = await ServiceAccountService(session).create(
            actor=actor,
            organization_id=organization.id,
            name="Read account",
            account_key="read-account",
            scopes=["mcp:read"],
            expires_at=None,
            metadata={"purpose": "scope test"},
        )
        await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield {
            "client": client,
            "token": issued.token,
            "denied_token": denied.token,
            "organization_id": organization.id,
            "sessions": sessions,
        }
    app.dependency_overrides.clear()
    await engine.dispose()


def _headers(context: dict[str, Any], key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {context['token']}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


@pytest.mark.asyncio
async def test_bootstrap_project_is_strict_idempotent_and_dry_run_is_side_effect_free(
    bootstrap_context: dict[str, Any],
) -> None:
    client = bootstrap_context["client"]
    dry_run = await client.post(
        "/api/v1/mcp/bootstrap/projects/ensure",
        headers=_headers(bootstrap_context),
        json={"name": "Payments", "external_key": "payments", "dry_run": True},
    )
    assert dry_run.status_code == 200, dry_run.text
    assert dry_run.json()["operation"] == "dry_run"
    assert dry_run.json()["project_id"] is None

    async with bootstrap_context["sessions"]() as session:
        assert await session.scalar(select(func.count()).select_from(Project)) == 0
        assert (
            await session.scalar(select(func.count()).select_from(OrganizationIdempotencyRecord))
            == 0
        )

    created = await client.post(
        "/api/v1/mcp/bootstrap/projects/ensure",
        headers=_headers(bootstrap_context, "project-bootstrap-v1"),
        json={"name": "Payments", "external_key": "payments", "dry_run": False},
    )
    assert created.status_code == 200, created.text
    created_body = created.json()
    assert created_body["operation"] == "created"
    assert created_body["project_id"]
    project_id = created_body["project_id"]

    # A completed receipt is recoverable even after mutable project state
    # changes; the response is the historical result, not a fresh lookup.
    async with bootstrap_context["sessions"]() as session:
        project = await session.get(Project, UUID(project_id))
        assert project is not None
        project.name = "Renamed after bootstrap"
        await session.commit()

    repeated = await client.post(
        "/api/v1/mcp/bootstrap/projects/ensure",
        headers=_headers(bootstrap_context, "project-bootstrap-v1"),
        json={"name": "Payments", "external_key": "payments", "dry_run": False},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["project_id"] == project_id
    assert repeated.json()["project_name"] == "Payments"
    assert repeated.json()["idempotency_replayed"] is True

    conflict = await client.post(
        "/api/v1/mcp/bootstrap/projects/ensure",
        headers=_headers(bootstrap_context, "project-bootstrap-v1"),
        json={"name": "Different", "external_key": "payments", "dry_run": False},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    reused = await client.post(
        "/api/v1/mcp/bootstrap/projects/ensure",
        headers=_headers(bootstrap_context, "project-bootstrap-v2"),
        json={"name": "Different", "external_key": "payments", "dry_run": False},
    )
    assert reused.status_code == 200, reused.text
    assert reused.json()["operation"] == "reused"
    assert reused.json()["project_id"] == project_id


@pytest.mark.asyncio
async def test_bootstrap_environment_and_target_preserve_boundaries(
    bootstrap_context: dict[str, Any],
) -> None:
    client = bootstrap_context["client"]
    project = await client.post(
        "/api/v1/mcp/bootstrap/projects/ensure",
        headers=_headers(bootstrap_context, "assets-project"),
        json={"name": "Assets", "external_key": "assets"},
    )
    project_id = project.json()["project_id"]

    invalid_classification = await client.post(
        "/api/v1/mcp/bootstrap/environments/ensure",
        headers=_headers(bootstrap_context, "bad-environment"),
        json={
            "project_id": project_id,
            "name": "prod",
            "base_url": "https://example.com",
            "classification": "production",
        },
    )
    assert invalid_classification.status_code == 422

    environment = await client.post(
        "/api/v1/mcp/bootstrap/environments/ensure",
        headers=_headers(bootstrap_context, "environment-v1"),
        json={
            "project_id": project_id,
            "name": "local",
            "base_url": "https://example.com/api/",
            "classification": "test",
        },
    )
    assert environment.status_code == 200, environment.text
    environment_body = environment.json()
    assert environment_body["operation"] == "created"
    environment_id = environment_body["environment_id"]

    mismatch = await client.post(
        "/api/v1/mcp/bootstrap/environments/ensure",
        headers=_headers(bootstrap_context, "environment-v2"),
        json={
            "project_id": project_id,
            "name": "local",
            "base_url": "https://different.example.com",
            "classification": "test",
        },
    )
    assert mismatch.status_code == 409, mismatch.text
    assert mismatch.json()["error"]["code"] == "ENVIRONMENT_CONFIGURATION_CONFLICT"

    target = await client.post(
        "/api/v1/mcp/bootstrap/service-targets/ensure",
        headers=_headers(bootstrap_context, "target-v1"),
        json={
            "project_id": project_id,
            "environment_id": environment_id,
            "service_key": "payments",
            "name": "Payments API",
            "base_url": "https://example.com/api",
            "service_type": "https",
        },
    )
    assert target.status_code == 200, target.text
    target_body = target.json()
    assert target_body["operation"] == "created"
    assert target_body["service_id"]
    assert target_body["endpoint_id"]

    insecure = await client.post(
        "/api/v1/mcp/bootstrap/service-targets/ensure",
        headers=_headers(bootstrap_context, "target-insecure"),
        json={
            "project_id": project_id,
            "environment_id": environment_id,
            "service_key": "insecure",
            "name": "Insecure",
            "base_url": "https://example.com",
            "tls_verify": False,
        },
    )
    assert insecure.status_code == 422

    async with bootstrap_context["sessions"]() as session:
        assert await session.scalar(select(func.count()).select_from(Environment)) == 1
        assert await session.scalar(select(func.count()).select_from(Service)) == 2
        assert await session.scalar(select(func.count()).select_from(ServiceEndpoint)) == 2


@pytest.mark.asyncio
async def test_bootstrap_requires_scope_and_idempotency_key(
    bootstrap_context: dict[str, Any],
) -> None:
    client = bootstrap_context["client"]
    connection = await client.post(
        "/api/v1/mcp/connection",
        headers=_headers(bootstrap_context),
        json={},
    )
    assert connection.status_code == 200, connection.text
    assert "bootstrap_project_assets" in connection.json()["available_actions"]

    denied = await client.post(
        "/api/v1/mcp/bootstrap/projects/ensure",
        headers={"Authorization": f"Bearer {bootstrap_context['denied_token']}"},
        json={"name": "Denied"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "MCP_SCOPE_REQUIRED"

    missing_key = await client.post(
        "/api/v1/mcp/bootstrap/projects/ensure",
        headers=_headers(bootstrap_context),
        json={"name": "Needs key"},
    )
    assert missing_key.status_code == 422
    assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    unknown = await client.post(
        "/api/v1/mcp/bootstrap/projects/ensure",
        headers=_headers(bootstrap_context),
        json={"name": "Strict", "token": "must-not-be-accepted", "dry_run": True},
    )
    assert unknown.status_code == 422

    non_ascii_key = await client.post(
        "/api/v1/mcp/bootstrap/projects/ensure",
        headers=_headers(bootstrap_context),
        json={"name": "Strict", "external_key": "项目", "dry_run": True},
    )
    assert non_ascii_key.status_code == 422
