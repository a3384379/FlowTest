from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_tasking_api import TaskingTestContext, _login_headers
from test_tasking_api import tasking_context as tasking_context

from app.core.security import password_service
from app.domain.access import ProjectRole
from app.models.access import AuditLog, Project, ProjectMember, User
from app.models.organizations import OrganizationMember
from app.models.quality import FlakyRecord


@pytest.mark.asyncio
async def test_exact_flaky_read_keeps_off_page_version_and_project_authorization(
    tasking_context: TaskingTestContext,
) -> None:
    context = tasking_context
    admin = await _login_headers(context.client)
    project = await context.client.post(
        "/api/v1/projects", headers=admin, json={"name": "Quality reader fixture"}
    )
    other = await context.client.post(
        "/api/v1/projects", headers=admin, json={"name": "Foreign quality fixture"}
    )
    assert project.status_code == other.status_code == 201
    project_id = UUID(project.json()["id"])
    target_id, record_id = uuid4(), uuid4()
    async with context.session_maker() as session:
        owner_project = await session.get(Project, project_id)
        assert owner_project is not None
        viewer = User(
            email="quality-viewer@example.com",
            display_name="Quality viewer",
            password_hash=password_service.hash("quality-viewer-fixture-123!"),
            is_active=True,
            is_system_admin=False,
            requires_password_change=False,
        )
        session.add(viewer)
        await session.flush()
        session.add(
            OrganizationMember(
                organization_id=owner_project.organization_id, user_id=viewer.id, role="member"
            )
        )
        session.add(
            ProjectMember(project_id=project_id, user_id=viewer.id, role=ProjectRole.VIEWER)
        )
        for version in range(1, 23):
            session.add(
                FlakyRecord(
                    id=record_id if version == 1 else uuid4(),
                    project_id=project_id,
                    target_type="workflow",
                    target_id=target_id,
                    target_version=version,
                    total_runs=8,
                    passed_runs=6,
                    failed_runs=2,
                    transitions=3,
                    flaky_score=version,
                    quarantined=version == 1,
                )
            )
        await session.commit()
        audit_count = await session.scalar(select(func.count()).select_from(AuditLog))
    login = await context.client.post(
        "/api/v1/auth/login",
        json={"email": viewer.email, "password": "quality-viewer-fixture-123!"},
    )
    assert login.status_code == 200
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    async with context.session_maker() as session:
        audit_count = await session.scalar(select(func.count()).select_from(AuditLog))
    root = f"/api/v1/projects/{project_id}/flaky-tests"
    first_page = await context.client.get(root, headers=viewer_headers)
    assert first_page.json()["total"] == 22
    assert record_id.hex not in {UUID(item["id"]).hex for item in first_page.json()["items"]}
    exact = await context.client.get(f"{root}/{record_id}", headers=viewer_headers)
    assert exact.status_code == 200, exact.text
    assert exact.json()["target_id"] == str(target_id)
    assert exact.json()["target_version"] == 1
    assert exact.json()["quarantined"] is True
    for path in [
        f"{root}/{uuid4()}",
        f"/api/v1/projects/{other.json()['id']}/flaky-tests/{record_id}",
    ]:
        missing = await context.client.get(path, headers=admin)
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "FLAKY_RECORD_NOT_FOUND"
        assert missing.json()["error"]["trace_id"]
    denied = await context.client.get(
        f"/api/v1/projects/{other.json()['id']}/flaky-tests/{record_id}", headers=viewer_headers
    )
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    assert denied.json()["error"]["trace_id"]
    assert (await context.client.get(f"{root}/{record_id}")).status_code == 401
    async with context.session_maker() as session:
        # Resource reads must add no audit events.
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == audit_count


@pytest.mark.asyncio
async def test_flaky_catalog_uses_a_stable_order_for_equal_scores_and_timestamps(
    tasking_context: TaskingTestContext,
) -> None:
    context = tasking_context
    headers = await _login_headers(context.client)
    created = await context.client.post(
        "/api/v1/projects", headers=headers, json={"name": "Equal score pagination fixture"}
    )
    assert created.status_code == 201
    project_id = UUID(created.json()["id"])
    indices = [*range(0, 46, 2), *range(1, 46, 2)]
    async with context.session_maker() as session:
        for index in indices:
            session.add(
                FlakyRecord(
                    id=UUID(int=1000 + index),
                    project_id=project_id,
                    target_type="workflow",
                    target_id=UUID(int=2000 + index),
                    target_version=1,
                    flaky_score=25,
                    updated_at=datetime(2026, 10, 1, tzinfo=UTC),
                )
            )
        await session.commit()
    ids: list[str] = []
    for page in [1, 2, 3]:
        response = await context.client.get(
            f"/api/v1/projects/{project_id}/flaky-tests",
            headers=headers,
            params={"page": page, "page_size": 20},
        )
        assert response.status_code == 200
        assert response.json()["total"] == 46
        ids.extend(item["id"] for item in response.json()["items"])
    assert ids == [str(UUID(int=1000 + index)) for index in range(46)]
    assert len(ids) == len(set(ids)) == 46
