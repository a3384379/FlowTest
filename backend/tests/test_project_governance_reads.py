from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from test_access_api import ADMIN_EMAIL, ADMIN_PASSWORD, _authorization, _login
from test_access_api import client as client

from app.core.database import get_session
from app.domain.access import ProjectRole
from app.main import app
from app.models.access import AuditLog, ProjectMember, Team, User
from app.models.organizations import OrganizationMember


@pytest.mark.asyncio
async def test_audit_pages_include_actor_identity_and_keep_all_records_reachable(
    client: AsyncClient,
) -> None:
    headers = _authorization((await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD))["access_token"])
    actor = await client.get("/api/v1/auth/me", headers=headers)
    created = await client.post(
        "/api/v1/projects", headers=headers, json={"name": "审计分页治理项目"}
    )
    assert created.status_code == 201, created.text
    project = created.json()
    project_id = UUID(project["id"])
    async for session in app.dependency_overrides[get_session]():
        session.add_all(
            [
                AuditLog(
                    actor_user_id=UUID(actor.json()["id"]),
                    organization_id=UUID(project["organization_id"]),
                    project_id=project_id,
                    action="api.updated",
                    resource_type="api_definition",
                    resource_id=uuid4(),
                    details={"trace_id": f"audit-read-{index}", "name": f"治理接口{index}"},
                    created_at=datetime(2026, 10, 21, tzinfo=UTC),
                )
                for index in range(61)
            ]
        )
        await session.commit()
    seen: set[str] = set()
    ordered: list[str] = []
    for page in range(1, 5):
        response = await client.get(
            f"/api/v1/projects/{project_id}/audit-logs",
            headers=headers,
            params={"page": page, "page_size": 20, "action": "api.updated"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 61 and body["page"] == page
        for record in body["items"]:
            assert record["actor_display_name"] == "Administrator"
            assert record["actor_user_id"] == actor.json()["id"]
            assert record["resource_id"] and record["details"]["trace_id"]
            assert record["id"] not in seen
            seen.add(record["id"])
            ordered.append(record["id"])
    assert len(seen) == 61
    assert ordered == sorted(ordered, reverse=True)
    foreign = await client.get(f"/api/v1/projects/{uuid4()}/audit-logs", headers=headers)
    assert foreign.status_code == 404 and foreign.json()["error"]["trace_id"]
    organization = await client.post(
        "/api/v1/organizations", headers=headers, json={"name": "其他组织", "slug": "audit-other"}
    )
    assert organization.status_code == 201
    outside_headers = {**headers, "X-Organization-Id": organization.json()["id"]}
    denied = await client.get(f"/api/v1/projects/{project_id}/audit-logs", headers=outside_headers)
    assert denied.status_code == 404 and denied.json()["error"]["trace_id"]
    denied_candidates = await client.post(
        f"/api/v1/projects/{project_id}/member-candidates/search", headers=outside_headers, json={}
    )
    assert denied_candidates.status_code == 404 and denied_candidates.json()["error"]["trace_id"]
    async for session in app.dependency_overrides[get_session]():
        session.add(
            AuditLog(
                project_id=project_id,
                actor_user_id=None,
                action="legacy.audit",
                resource_type="legacy",
                resource_id=None,
                details={},
                created_at=datetime(2026, 10, 21, tzinfo=UTC),
            )
        )
        await session.commit()
    legacy = await client.get(
        f"/api/v1/projects/{project_id}/audit-logs",
        headers=headers,
        params={"action": "legacy.audit"},
    )
    assert legacy.json()["items"][0]["actor_display_name"] is None
    assert legacy.json()["items"][0]["actor_user_id"] is None
    assert legacy.json()["items"][0]["details"] == {}


@pytest.mark.asyncio
async def test_owner_directory_is_scoped_searchable_and_paged_without_global_user_access(
    client: AsyncClient,
) -> None:
    admin_headers = _authorization(
        (await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD))["access_token"]
    )
    project = (
        await client.post("/api/v1/projects", headers=admin_headers, json={"name": "成员目录项目"})
    ).json()
    async for session in app.dependency_overrides[get_session]():
        admin = (await session.scalars(select(User).where(User.email == ADMIN_EMAIL))).one()
        people = [
            User(
                email=f"candidate-{index:03}@example.com",
                display_name=f"候选成员{index:03}",
                password_hash=admin.password_hash,
                is_active=True,
                is_system_admin=False,
                requires_password_change=False,
            )
            for index in range(106)
        ]
        outsider = User(
            email="outside-private@example.com",
            display_name="外部不可发现成员",
            password_hash=admin.password_hash,
            is_active=True,
            requires_password_change=False,
        )
        inactive = User(
            email="inactive-candidate@example.com",
            display_name="停用成员",
            password_hash=admin.password_hash,
            is_active=False,
            requires_password_change=False,
        )
        session.add_all([*people, outsider, inactive])
        await session.flush()
        session.add_all(
            [
                OrganizationMember(
                    organization_id=UUID(project["organization_id"]),
                    user_id=person.id,
                    role="member",
                )
                for person in [*people, inactive]
            ]
        )
        session.add_all(
            [
                ProjectMember(
                    project_id=UUID(project["id"]), user_id=people[0].id, role=ProjectRole.OWNER
                ),
                ProjectMember(
                    project_id=UUID(project["id"]), user_id=people[1].id, role=ProjectRole.VIEWER
                ),
            ]
        )
        session.add_all(
            [Team(name=f"目录团队{index:03}", created_by_id=admin.id) for index in range(106)]
        )
        await session.commit()
        owner_id = str(people[0].id)
    owner_headers = _authorization(
        (await _login(client, "candidate-000@example.com", ADMIN_PASSWORD))["access_token"]
    )
    endpoint = f"/api/v1/projects/{project['id']}/member-candidates/search"
    page = await client.post(
        endpoint, headers=owner_headers, json={"query": "candidate-", "page": 2, "page_size": 100}
    )
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 106 and len(page.json()["items"]) == 6
    assert all(
        set(item) == {"id", "email", "display_name", "is_active"} for item in page.json()["items"]
    )
    selected = await client.post(endpoint, headers=owner_headers, json={"query": "candidate-105"})
    assert [item["email"] for item in selected.json()["items"]] == ["candidate-105@example.com"]
    for term in ["outside-private", "inactive-candidate", "%_"]:
        hidden = await client.post(endpoint, headers=owner_headers, json={"query": term})
        assert hidden.status_code == 200 and hidden.json()["total"] == 0
    denied = await client.post(
        "/api/v1/users/search", headers=owner_headers, json={"query": "outside"}
    )
    assert denied.status_code == 403 and denied.json()["error"]["trace_id"]
    members = await client.get(f"/api/v1/projects/{project['id']}/members", headers=owner_headers)
    owner = next(item for item in members.json() if item["user_id"] == owner_id)
    assert owner["display_name"] == "候选成员000" and owner["email"] == "candidate-000@example.com"
    teams = await client.post(
        "/api/v1/teams/search",
        headers=owner_headers,
        json={"query": "目录团队", "page": 2, "page_size": 100},
    )
    assert (
        teams.status_code == 200
        and teams.json()["total"] == 106
        and len(teams.json()["items"]) == 6
    )
    viewer_headers = _authorization(
        (await _login(client, "candidate-001@example.com", ADMIN_PASSWORD))["access_token"]
    )
    viewer = await client.post(endpoint, headers=viewer_headers, json={"query": "candidate"})
    assert viewer.status_code == 403 and viewer.json()["error"]["trace_id"]
    missing = await client.post(
        f"/api/v1/projects/{uuid4()}/member-candidates/search",
        headers=owner_headers,
        json={"query": "candidate"},
    )
    assert missing.status_code == 404 and missing.json()["error"]["trace_id"]
    admin_users = await client.post(
        "/api/v1/users/search", headers=admin_headers, json={"query": "outside-private"}
    )
    assert admin_users.status_code == 200 and admin_users.json()["total"] == 1
    for payload in [{"page_size": 101}, {"page": 2_147_483_648}, {"unrecognized": True}]:
        invalid = await client.post(endpoint, headers=owner_headers, json=payload)
        assert invalid.status_code == 422 and invalid.json()["error"]["trace_id"]
    team = (
        await client.post("/api/v1/teams", headers=admin_headers, json={"name": "身份摘要验证团队"})
    ).json()
    added = await client.put(
        f"/api/v1/teams/{team['id']}/members/{owner_id}",
        headers=admin_headers,
        json={"user_id": owner_id},
    )
    assert added.status_code == 200
    team_members = await client.get(f"/api/v1/teams/{team['id']}/members", headers=admin_headers)
    assert team_members.json()[0]["display_name"] == "候选成员000"
    assert team_members.json()[0]["email"] == "candidate-000@example.com"
    hidden_members = await client.get(f"/api/v1/teams/{team['id']}/members", headers=owner_headers)
    assert hidden_members.status_code == 403 and hidden_members.json()["error"]["trace_id"]
    grant = await client.put(
        f"/api/v1/projects/{project['id']}/team-grants/{team['id']}",
        headers=owner_headers,
        json={"team_id": team["id"], "role": "viewer"},
    )
    assert grant.status_code == 200
    grants = await client.get(
        f"/api/v1/projects/{project['id']}/team-grants", headers=owner_headers
    )
    assert grants.json()[0]["team_name"] == team["name"]
