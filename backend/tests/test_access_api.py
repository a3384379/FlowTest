from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_session
from app.core.security import password_service
from app.domain.runtime_profiles import RuntimeProfile
from app.main import app
from app.models import Base
from app.models.access import User
from app.services.auth import bootstrap_administrator

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-password-123!"


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
                display_name="Administrator",
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
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_login_refresh_rotation_logout_and_password_change(client: AsyncClient) -> None:
    invalid = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"}
    )
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "INVALID_CREDENTIALS"

    login = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    access_token = login["access_token"]
    first_refresh = client.cookies.get("flowtest_refresh")
    assert first_refresh is not None
    assert login["expires_in"] == 900

    me = await client.get("/api/v1/auth/me", headers=_authorization(access_token))
    assert me.status_code == 200
    assert me.json()["email"] == ADMIN_EMAIL

    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    second_refresh = client.cookies.get("flowtest_refresh")
    assert second_refresh and second_refresh != first_refresh

    client.cookies.clear()
    client.cookies.set("flowtest_refresh", first_refresh, domain="test.local", path="/api/v1/auth")
    replay = await client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401

    client.cookies.clear()
    client.cookies.set("flowtest_refresh", second_refresh, domain="test.local", path="/api/v1/auth")
    too_short = await client.post(
        "/api/v1/auth/change-password",
        headers=_authorization(access_token),
        json={"current_password": ADMIN_PASSWORD, "new_password": "1234567"},
    )
    assert too_short.status_code == 422

    changed = await client.post(
        "/api/v1/auth/change-password",
        headers=_authorization(access_token),
        json={
            "current_password": ADMIN_PASSWORD,
            "new_password": "new-admin-password-123!",
        },
    )
    assert changed.status_code == 204
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401

    new_login = await _login(client, ADMIN_EMAIL, "new-admin-password-123!")
    logged_out = await client.post(
        "/api/v1/auth/logout", headers=_authorization(new_login["access_token"])
    )
    assert logged_out.status_code == 204
    assert client.cookies.get("flowtest_refresh") is None


@pytest.mark.asyncio
async def test_admin_login_alias_resolves_to_bootstrap_email(client: AsyncClient) -> None:
    admin_token = (await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD))["access_token"]
    short_password = await client.post(
        "/api/v1/users",
        headers=_authorization(admin_token),
        json={
            "email": "short-password@example.com",
            "display_name": "Short password",
            "password": "1234567",
            "is_system_admin": False,
        },
    )
    assert short_password.status_code == 422

    created = await client.post(
        "/api/v1/users",
        headers=_authorization(admin_token),
        json={
            "email": settings.bootstrap_admin_email,
            "display_name": "Bootstrap administrator",
            "password": "admin-password-123!",
            "is_system_admin": True,
        },
    )
    assert created.status_code == 201, created.text

    alias_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin", "password": "admin-password-123!"},
    )
    assert alias_login.status_code == 200, alias_login.text
    assert alias_login.json()["user"]["email"] == settings.bootstrap_admin_email


@pytest.mark.asyncio
async def test_user_project_isolation_roles_and_folder_invariants(client: AsyncClient) -> None:
    admin_token = (await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD))["access_token"]
    admin_headers = _authorization(admin_token)
    editor = await _create_user(client, admin_headers, "editor@example.com")
    viewer = await _create_user(client, admin_headers, "viewer@example.com")
    outsider = await _create_user(client, admin_headers, "outsider@example.com")

    project_response = await client.post(
        "/api/v1/projects",
        headers=admin_headers,
        json={"name": "Commerce", "description": "Order APIs"},
    )
    assert project_response.status_code == 201
    project = project_response.json()
    project_id = project["id"]
    assert project["role"] == "owner"
    admin_projects = await client.get("/api/v1/projects", headers=admin_headers)
    assert admin_projects.status_code == 200
    assert admin_projects.json()["total"] == 1

    editor_token = (await _login(client, editor["email"], "initial-password-123!"))["access_token"]
    outsider_token = (await _login(client, outsider["email"], "initial-password-123!"))[
        "access_token"
    ]
    hidden = await client.get(
        f"/api/v1/projects/{project_id}", headers=_authorization(outsider_token)
    )
    assert hidden.status_code == 404

    for member, role in ((editor, "editor"), (viewer, "viewer")):
        added = await client.put(
            f"/api/v1/projects/{project_id}/members/{member['id']}",
            headers=admin_headers,
            json={"user_id": member["id"], "role": role},
        )
        assert added.status_code == 200

    members = await client.get(f"/api/v1/projects/{project_id}/members", headers=admin_headers)
    assert members.status_code == 200
    assert len(members.json()) == 3
    mismatch = await client.put(
        f"/api/v1/projects/{project_id}/members/{viewer['id']}",
        headers=admin_headers,
        json={"user_id": editor["id"], "role": "viewer"},
    )
    assert mismatch.status_code == 422

    edited_project = await client.patch(
        f"/api/v1/projects/{project_id}",
        headers=_authorization(editor_token),
        json={"description": "Updated by editor"},
    )
    assert edited_project.status_code == 200
    assert edited_project.json()["description"] == "Updated by editor"
    editor_projects = await client.get("/api/v1/projects", headers=_authorization(editor_token))
    assert editor_projects.json()["items"][0]["role"] == "editor"

    root = await client.post(
        f"/api/v1/projects/{project_id}/folders",
        headers=_authorization(editor_token),
        json={"name": "Root"},
    )
    assert root.status_code == 201

    other_project = await client.post(
        "/api/v1/projects",
        headers=admin_headers,
        json={"name": "Other", "description": "Isolation"},
    )
    other_root = await client.post(
        f"/api/v1/projects/{other_project.json()['id']}/folders",
        headers=admin_headers,
        json={"name": "Other root"},
    )
    cross_project_parent = await client.post(
        f"/api/v1/projects/{project_id}/folders",
        headers=_authorization(editor_token),
        json={"name": "Cross", "parent_id": other_root.json()["id"]},
    )
    assert cross_project_parent.status_code == 404
    duplicate = await client.post(
        f"/api/v1/projects/{project_id}/folders",
        headers=_authorization(editor_token),
        json={"name": "Root"},
    )
    assert duplicate.status_code == 409
    child = await client.post(
        f"/api/v1/projects/{project_id}/folders",
        headers=_authorization(editor_token),
        json={"name": "Child", "parent_id": root.json()["id"]},
    )
    assert child.status_code == 201

    renamed = await client.patch(
        f"/api/v1/projects/{project_id}/folders/{child.json()['id']}",
        headers=_authorization(editor_token),
        json={"name": "Renamed child"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["parent_id"] == root.json()["id"]

    self_move = await client.patch(
        f"/api/v1/projects/{project_id}/folders/{child.json()['id']}",
        headers=_authorization(editor_token),
        json={"parent_id": child.json()["id"]},
    )
    assert self_move.status_code == 409

    cycle = await client.patch(
        f"/api/v1/projects/{project_id}/folders/{root.json()['id']}",
        headers=_authorization(editor_token),
        json={"parent_id": child.json()["id"]},
    )
    assert cycle.status_code == 409
    assert cycle.json()["error"]["code"] == "INVALID_FOLDER_MOVE"

    viewer_token = (await _login(client, viewer["email"], "initial-password-123!"))["access_token"]
    assert (
        await client.get(
            f"/api/v1/projects/{project_id}/folders",
            headers=_authorization(viewer_token),
        )
    ).status_code == 200
    forbidden = await client.post(
        f"/api/v1/projects/{project_id}/folders",
        headers=_authorization(viewer_token),
        json={"name": "Forbidden"},
    )
    assert forbidden.status_code == 403

    missing_member = await client.delete(
        f"/api/v1/projects/{project_id}/members/{outsider['id']}", headers=admin_headers
    )
    assert missing_member.status_code == 404
    removed_viewer = await client.delete(
        f"/api/v1/projects/{project_id}/members/{viewer['id']}", headers=admin_headers
    )
    assert removed_viewer.status_code == 204

    missing_folder = await client.patch(
        f"/api/v1/projects/{project_id}/folders/00000000-0000-0000-0000-000000000001",
        headers=_authorization(editor_token),
        json={"name": "Missing"},
    )
    assert missing_folder.status_code == 404

    deleted_child = await client.delete(
        f"/api/v1/projects/{project_id}/folders/{child.json()['id']}",
        headers=_authorization(editor_token),
    )
    assert deleted_child.status_code == 204

    remove_only_owner = await client.delete(
        f"/api/v1/projects/{project_id}/members/{project['created_by_id']}",
        headers=admin_headers,
    )
    assert remove_only_owner.status_code == 409
    assert remove_only_owner.json()["error"]["code"] == "LAST_PROJECT_OWNER"


@pytest.mark.asyncio
async def test_authentication_and_admin_boundaries(client: AsyncClient) -> None:
    unauthorized = await client.get("/api/v1/projects")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    invalid_token = await client.get(
        "/api/v1/projects", headers={"Authorization": "Bearer invalid"}
    )
    assert invalid_token.status_code == 401
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401

    admin_token = (await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD))["access_token"]
    admin_headers = _authorization(admin_token)
    user = await _create_user(client, admin_headers, "regular@example.com")
    first_login = await client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": "initial-password-123!"},
    )
    user_token = first_login.json()["access_token"]
    password_blocked = await client.get("/api/v1/projects", headers=_authorization(user_token))
    assert password_blocked.status_code == 403
    assert password_blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    changed = await client.post(
        "/api/v1/auth/change-password",
        headers=_authorization(user_token),
        json={
            "current_password": "initial-password-123!",
            "new_password": "changed-password-123!",
        },
    )
    assert changed.status_code == 204

    forbidden = await client.get("/api/v1/users", headers=_authorization(user_token))
    assert forbidden.status_code == 403
    users = await client.get("/api/v1/users?page=1&page_size=10", headers=admin_headers)
    assert users.status_code == 200
    assert users.json()["total"] == 2

    duplicate = await client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "email": user["email"].upper(),
            "display_name": "Duplicate",
            "password": "initial-password-123!",
        },
    )
    assert duplicate.status_code == 409

    updated = await client.patch(
        f"/api/v1/users/{user['id']}",
        headers=admin_headers,
        json={"display_name": "Updated user", "is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Updated user"
    assert (
        await client.get("/api/v1/auth/me", headers=_authorization(user_token))
    ).status_code == 401
    promoted = await client.patch(
        f"/api/v1/users/{user['id']}",
        headers=admin_headers,
        json={"is_active": True, "is_system_admin": True},
    )
    assert promoted.json()["is_system_admin"] is True


@pytest.mark.asyncio
async def test_password_validation_and_missing_resources(client: AsyncClient) -> None:
    token = (await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD))["access_token"]
    headers = _authorization(token)
    wrong_password = await client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": "wrong", "new_password": "new-password-123!"},
    )
    assert wrong_password.status_code == 400
    reused_password = await client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": ADMIN_PASSWORD, "new_password": ADMIN_PASSWORD},
    )
    assert reused_password.status_code == 400

    missing_project = await client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001", headers=headers
    )
    assert missing_project.status_code == 404
    missing_user = await client.patch(
        "/api/v1/users/00000000-0000-0000-0000-000000000001",
        headers=headers,
        json={"display_name": "Nobody"},
    )
    assert missing_user.status_code == 404

    client.cookies.clear()
    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204


@pytest.mark.asyncio
async def test_non_system_owner_can_manage_members_and_transfer_ownership(
    client: AsyncClient,
) -> None:
    admin_token = (await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD))["access_token"]
    admin_headers = _authorization(admin_token)
    owner = await _create_user(client, admin_headers, "owner@example.com")
    successor = await _create_user(client, admin_headers, "successor@example.com")
    inactive = await _create_user(client, admin_headers, "inactive@example.com")
    await client.patch(
        f"/api/v1/users/{inactive['id']}",
        headers=admin_headers,
        json={"is_active": False},
    )

    owner_token = (await _login(client, owner["email"], "initial-password-123!"))["access_token"]
    owner_headers = _authorization(owner_token)
    project = await client.post(
        "/api/v1/projects",
        headers=owner_headers,
        json={"name": "Owned project"},
    )
    project_id = project.json()["id"]

    inactive_member = await client.put(
        f"/api/v1/projects/{project_id}/members/{inactive['id']}",
        headers=owner_headers,
        json={"user_id": inactive["id"], "role": "viewer"},
    )
    assert inactive_member.status_code == 404

    successor_member = await client.put(
        f"/api/v1/projects/{project_id}/members/{successor['id']}",
        headers=owner_headers,
        json={"user_id": successor["id"], "role": "owner"},
    )
    assert successor_member.status_code == 200
    demoted = await client.put(
        f"/api/v1/projects/{project_id}/members/{owner['id']}",
        headers=owner_headers,
        json={"user_id": owner["id"], "role": "editor"},
    )
    assert demoted.status_code == 200
    assert demoted.json()["role"] == "editor"

    forbidden = await client.put(
        f"/api/v1/projects/{project_id}/members/{owner['id']}",
        headers=owner_headers,
        json={"user_id": owner["id"], "role": "owner"},
    )
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_permission_matrix_security_policy_and_audit_access(client: AsyncClient) -> None:
    admin_headers = _authorization(
        (await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD))["access_token"]
    )
    owner = await _create_user(client, admin_headers, "governance-owner@example.com")
    editor = await _create_user(client, admin_headers, "governance-editor@example.com")
    viewer = await _create_user(client, admin_headers, "governance-viewer@example.com")
    owner_headers = _authorization(
        (await _login(client, owner["email"], "initial-password-123!"))["access_token"]
    )
    project = await client.post(
        "/api/v1/projects",
        headers=owner_headers,
        json={"name": "Governed project"},
    )
    project_id = project.json()["id"]
    for member, role in ((editor, "editor"), (viewer, "viewer")):
        response = await client.put(
            f"/api/v1/projects/{project_id}/members/{member['id']}",
            headers=owner_headers,
            json={"user_id": member["id"], "role": role},
        )
        assert response.status_code == 200

    editor_headers = _authorization(
        (await _login(client, editor["email"], "initial-password-123!"))["access_token"]
    )
    viewer_headers = _authorization(
        (await _login(client, viewer["email"], "initial-password-123!"))["access_token"]
    )
    owner_permissions = await client.get(
        f"/api/v1/projects/{project_id}/permissions", headers=owner_headers
    )
    editor_permissions = await client.get(
        f"/api/v1/projects/{project_id}/permissions", headers=editor_headers
    )
    viewer_permissions = await client.get(
        f"/api/v1/projects/{project_id}/permissions", headers=viewer_headers
    )
    assert owner_permissions.json()["capabilities"] == [
        "edit",
        "execute",
        "manage_members",
        "manage_security",
        "read",
        "view_audit",
    ]
    assert editor_permissions.json()["capabilities"] == ["edit", "execute", "read"]
    assert viewer_permissions.json()["capabilities"] == ["read"]
    assert set(owner_permissions.json()["matrix"]) == {"owner", "editor", "viewer"}

    trace_id = "governance-policy-test"
    policy = await client.put(
        f"/api/v1/projects/{project_id}/security-policy",
        headers={**owner_headers, "X-Trace-ID": trace_id},
        json={
            "allowed_hosts": ["*.example.com", "api.internal"],
            "allowed_private_cidrs": ["10.20.0.1/16"],
        },
    )
    assert policy.status_code == 200, policy.text
    assert policy.json() == {
        "allowed_hosts": ["*.example.com", "api.internal"],
        "allowed_private_cidrs": ["10.20.0.0/16"],
    }
    assert (
        await client.put(
            f"/api/v1/projects/{project_id}/security-policy",
            headers=editor_headers,
            json={"allowed_hosts": [], "allowed_private_cidrs": []},
        )
    ).status_code == 403
    invalid = await client.put(
        f"/api/v1/projects/{project_id}/security-policy",
        headers=owner_headers,
        json={"allowed_hosts": [], "allowed_private_cidrs": ["169.254.0.0/16"]},
    )
    assert invalid.status_code == 422

    retention = await client.put(
        f"/api/v1/projects/{project_id}/retention-policy",
        headers=owner_headers,
        json={"retention_days": 120},
    )
    assert retention.status_code == 200
    assert retention.json() == {"retention_days": 120, "maximum_days": 3650}
    readable_retention = await client.get(
        f"/api/v1/projects/{project_id}/retention-policy", headers=viewer_headers
    )
    assert readable_retention.json()["retention_days"] == 120
    forbidden_retention = await client.put(
        f"/api/v1/projects/{project_id}/retention-policy",
        headers=editor_headers,
        json={"retention_days": 30},
    )
    assert forbidden_retention.status_code == 403

    audit = await client.get(
        f"/api/v1/projects/{project_id}/audit-logs",
        headers=owner_headers,
        params={"action": "project.security_policy_updated"},
    )
    assert audit.status_code == 200
    assert audit.json()["total"] == 1
    assert audit.json()["items"][0]["details"]["trace_id"] == trace_id
    forbidden_audit = await client.get(
        f"/api/v1/projects/{project_id}/audit-logs", headers=viewer_headers
    )
    assert forbidden_audit.status_code == 403


@pytest.mark.asyncio
async def test_team_grants_and_direct_membership_precedence(client: AsyncClient) -> None:
    admin_headers = _authorization(
        (await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD))["access_token"]
    )
    owner = await _create_user(client, admin_headers, "team-owner@example.com")
    direct_viewer = await _create_user(client, admin_headers, "direct-viewer@example.com")
    team_editor = await _create_user(client, admin_headers, "team-editor@example.com")
    owner_headers = _authorization(
        (await _login(client, owner["email"], "initial-password-123!"))["access_token"]
    )
    direct_viewer_headers = _authorization(
        (await _login(client, direct_viewer["email"], "initial-password-123!"))["access_token"]
    )
    team_editor_headers = _authorization(
        (await _login(client, team_editor["email"], "initial-password-123!"))["access_token"]
    )

    forbidden_team = await client.post(
        "/api/v1/teams",
        headers=owner_headers,
        json={"name": "Forbidden team"},
    )
    assert forbidden_team.status_code == 403
    team_response = await client.post(
        "/api/v1/teams",
        headers=admin_headers,
        json={"name": "Quality", "description": "API quality team"},
    )
    assert team_response.status_code == 201, team_response.text
    team_id = team_response.json()["id"]
    members = await client.get(f"/api/v1/teams/{team_id}/members", headers=admin_headers)
    assert members.status_code == 200
    forbidden_members = await client.get(f"/api/v1/teams/{team_id}/members", headers=owner_headers)
    assert forbidden_members.status_code == 403
    for user in (direct_viewer, team_editor):
        member = await client.put(
            f"/api/v1/teams/{team_id}/members/{user['id']}",
            headers=admin_headers,
            json={"user_id": user["id"]},
        )
        assert member.status_code == 200, member.text

    project_response = await client.post(
        "/api/v1/projects",
        headers=owner_headers,
        json={"name": "Team access project"},
    )
    project_id = project_response.json()["id"]
    direct = await client.put(
        f"/api/v1/projects/{project_id}/members/{direct_viewer['id']}",
        headers=owner_headers,
        json={"user_id": direct_viewer["id"], "role": "viewer"},
    )
    assert direct.status_code == 200
    grant = await client.put(
        f"/api/v1/projects/{project_id}/team-grants/{team_id}",
        headers=owner_headers,
        json={"team_id": team_id, "role": "editor"},
    )
    assert grant.status_code == 200, grant.text

    team_projects = await client.get("/api/v1/projects", headers=team_editor_headers)
    assert team_projects.json()["items"][0]["role"] == "editor"
    edited = await client.patch(
        f"/api/v1/projects/{project_id}",
        headers=team_editor_headers,
        json={"description": "Edited through team grant"},
    )
    assert edited.status_code == 200

    direct_permissions = await client.get(
        f"/api/v1/projects/{project_id}/permissions",
        headers=direct_viewer_headers,
    )
    assert direct_permissions.json()["effective_role"] == "viewer"
    direct_edit = await client.patch(
        f"/api/v1/projects/{project_id}",
        headers=direct_viewer_headers,
        json={"description": "Direct membership must win"},
    )
    assert direct_edit.status_code == 403

    grants = await client.get(f"/api/v1/projects/{project_id}/team-grants", headers=owner_headers)
    assert grants.status_code == 200
    assert grants.json()[0]["role"] == "editor"
    removed = await client.delete(
        f"/api/v1/teams/{team_id}/members/{team_editor['id']}", headers=admin_headers
    )
    assert removed.status_code == 204
    hidden = await client.get(f"/api/v1/projects/{project_id}", headers=team_editor_headers)
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_bootstrap_administrator_is_idempotent() -> None:
    test_engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        await bootstrap_administrator(session)
        await bootstrap_administrator(session)
        total = await session.scalar(select(func.count()).select_from(User))
        administrator = await session.scalar(select(User))
    assert total == 1
    assert administrator is not None
    assert administrator.is_system_admin
    assert administrator.requires_password_change
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_standalone_bootstrap_uses_simple_password_without_forced_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "runtime_profile", RuntimeProfile.STANDALONE)
    monkeypatch.setattr(settings, "bootstrap_admin_password", "admin")
    test_engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        await bootstrap_administrator(session)
        administrator = await session.scalar(select(User))
    assert administrator is not None
    assert not administrator.requires_password_change
    assert password_service.verify(administrator.password_hash, "admin")
    await test_engine.dispose()


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, Any]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    login = response.json()
    if login["user"]["requires_password_change"]:
        changed = await client.post(
            "/api/v1/auth/change-password",
            headers=_authorization(login["access_token"]),
            json={
                "current_password": password,
                "new_password": "changed-password-123!",
            },
        )
        assert changed.status_code == 204, changed.text
    return login


async def _create_user(client: AsyncClient, headers: dict[str, str], email: str) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "email": email,
            "display_name": email.split("@", maxsplit=1)[0],
            "password": "initial-password-123!",
            "is_system_admin": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _authorization(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}
