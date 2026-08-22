from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import password_service
from app.domain.runtime_profiles import RuntimeProfile
from app.main import app
from app.models import Base
from app.models.access import User
from app.models.organizations import Organization
from app.services.service_accounts import ServiceAccountService

ADMIN_EMAIL = "organization-admin@example.com"
ADMIN_PASSWORD = "organization-password-123!"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="Organization administrator",
                password_hash=password_service.hash(ADMIN_PASSWORD),
                is_active=True,
                is_system_admin=True,
                requires_password_change=False,
            )
        )
        await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_organizations_scope_projects_and_service_account_lifecycle(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = await _login(client)
    headers = _authorization(token)

    organizations = await client.get("/api/v1/organizations", headers=headers)
    assert organizations.status_code == 200, organizations.text
    assert len(organizations.json()) == 1
    default_organization = organizations.json()[0]
    assert default_organization["slug"] == "default"
    default_id = default_organization["id"]

    created_organization = await client.post(
        "/api/v1/organizations",
        headers=headers,
        json={"name": "Payments", "slug": "payments", "description": "Payments team"},
    )
    assert created_organization.status_code == 201, created_organization.text
    organization_id = created_organization.json()["id"]
    organization_headers = {
        **headers,
        "X-Organization-Id": organization_id,
    }
    duplicate_organization = await client.post(
        "/api/v1/organizations",
        headers=headers,
        json={"name": "Duplicate", "slug": "payments"},
    )
    assert duplicate_organization.status_code == 409

    member_user = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "email": "payments-viewer@example.com",
            "display_name": "Payments viewer",
            "password": "viewer-password-123!",
            "is_system_admin": False,
        },
    )
    assert member_user.status_code == 201, member_user.text
    member_user_id = member_user.json()["id"]
    member = await client.put(
        f"/api/v1/organizations/{organization_id}/members/{member_user_id}",
        headers=organization_headers,
        json={"user_id": member_user_id, "role": "member"},
    )
    assert member.status_code == 200, member.text
    members = await client.get(
        f"/api/v1/organizations/{organization_id}/members",
        headers=organization_headers,
    )
    assert members.status_code == 200
    assert {item["user_id"] for item in members.json()} == {
        member_user_id,
        (
            await client.get(
                f"/api/v1/organizations/{organization_id}", headers=organization_headers
            )
        ).json()["created_by_id"],
    }
    updated_member = await client.put(
        f"/api/v1/organizations/{organization_id}/members/{member_user_id}",
        headers=organization_headers,
        json={"user_id": member_user_id, "role": "viewer"},
    )
    assert updated_member.status_code == 200
    monkeypatch.setattr("app.core.config.settings.runtime_profile", RuntimeProfile.STANDALONE)
    member_headers = _authorization(
        await _login(client, "payments-viewer@example.com", "viewer-password-123!")
    )
    member_organizations = await client.get("/api/v1/organizations", headers=member_headers)
    assert member_organizations.status_code == 200
    assert {item["id"] for item in member_organizations.json()} == {default_id, organization_id}
    removed_member = await client.delete(
        f"/api/v1/organizations/{organization_id}/members/{member_user_id}",
        headers=organization_headers,
    )
    assert removed_member.status_code == 204

    project = await client.post(
        "/api/v1/projects",
        headers=organization_headers,
        json={"name": "Payments API", "description": "Tenant scoped project"},
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    assert project.json()["organization_id"] == organization_id

    hidden_from_default = await client.get(
        f"/api/v1/projects/{project_id}",
        headers=headers,
    )
    assert hidden_from_default.status_code == 404
    visible_in_organization = await client.get(
        f"/api/v1/projects/{project_id}",
        headers=organization_headers,
    )
    assert visible_in_organization.status_code == 200

    monkeypatch.setattr("app.core.config.settings.feature_runner_fabric_enabled", True)
    pool = await client.post(
        "/api/v1/execution-fabric/pools",
        headers=organization_headers,
        json={"name": "Payments runners", "runner_type": "general"},
    )
    assert pool.status_code == 201, pool.text
    default_pools = await client.get(
        "/api/v1/execution-fabric/pools",
        headers=headers,
    )
    assert default_pools.status_code == 200
    assert default_pools.json()["total"] == 0
    organization_pools = await client.get(
        "/api/v1/execution-fabric/pools",
        headers=organization_headers,
    )
    assert organization_pools.status_code == 200
    assert organization_pools.json()["total"] == 1

    updated_organization = await client.patch(
        f"/api/v1/organizations/{organization_id}",
        headers=organization_headers,
        json={"name": "Payments Platform", "description": "Updated", "enabled": True},
    )
    assert updated_organization.status_code == 200, updated_organization.text
    assert updated_organization.json()["name"] == "Payments Platform"

    accounts = await client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts",
        headers=organization_headers,
        json={
            "name": "Regression runner",
            "account_key": "regression-runner",
            "scopes": ["project:read", "execution:trigger"],
            "metadata": {"owner": "qa"},
        },
    )
    assert accounts.status_code == 201, accounts.text
    issued = accounts.json()
    original_token = issued["token"]
    assert original_token.startswith("ftsa_")
    assert issued["scopes"] == ["execution:trigger", "project:read"]

    listed = await client.get(
        f"/api/v1/organizations/{organization_id}/service-accounts",
        headers=organization_headers,
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    assert "token" not in listed.json()[0]
    assert "token_hash" not in listed.json()[0]

    rotated = await client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts/{issued['id']}/rotate",
        headers=organization_headers,
    )
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["token"] != original_token

    revoked = await client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts/{issued['id']}/revoke",
        headers=organization_headers,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["enabled"] is False
    rotate_revoked = await client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts/{issued['id']}/rotate",
        headers=organization_headers,
    )
    assert rotate_revoked.status_code == 409
    assert rotate_revoked.json()["error"]["code"] == "SERVICE_ACCOUNT_REVOKED"

    default_projects = await client.get("/api/v1/projects", headers=headers)
    assert default_projects.status_code == 200
    assert default_projects.json()["total"] == 0
    assert default_id != organization_id


@pytest.fixture
async def service_account_sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield sessions
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_service_account_authentication_is_scoped_and_revocable(
    service_account_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with service_account_sessions() as session:
        actor = User(
            email="service-account-admin@example.com",
            display_name="Service account administrator",
            password_hash=password_service.hash(ADMIN_PASSWORD),
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        organization = Organization(
            name="Service account organization",
            slug="service-account-org",
            description="",
            enabled=True,
            created_by_id=None,
        )
        session.add_all([actor, organization])
        await session.commit()

        service = ServiceAccountService(session)
        issued = await service.create(
            actor=actor,
            organization_id=organization.id,
            name="MCP reader",
            account_key="mcp-reader",
            scopes=["org:read"],
            expires_at=None,
            metadata={},
        )
        account, tenant = await service.authenticate(issued.token)
        assert account.id == issued.account.id
        assert account.token_hash != issued.token
        assert tenant.organization_id == organization.id
        assert tenant.service_account_id == account.id
        assert tenant.allows("org:read")

        await service.revoke(
            actor=actor,
            organization_id=organization.id,
            account_id=account.id,
        )
        with pytest.raises(AppError) as invalid:
            await service.authenticate(issued.token)
        assert invalid.value.code == "INVALID_SERVICE_ACCOUNT_TOKEN"


async def _login(
    client: AsyncClient,
    email: str = ADMIN_EMAIL,
    password: str = ADMIN_PASSWORD,
) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
