from datetime import UTC, datetime, timedelta
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
async def test_flaky_summary_counts_the_complete_project_and_authorizes_viewers(
    tasking_context: TaskingTestContext,
) -> None:
    context = tasking_context
    headers = await _login_headers(context.client)
    created = await context.client.post(
        "/api/v1/projects", headers=headers, json={"name": "Full Flaky summary fixture"}
    )
    foreign = await context.client.post(
        "/api/v1/projects", headers=headers, json={"name": "Foreign summary fixture"}
    )
    project_id = UUID(created.json()["id"])
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    async with context.session_maker() as session:
        project = await session.get(Project, project_id)
        assert project is not None
        viewer = User(
            email="summary-viewer@example.com",
            display_name="Summary viewer",
            password_hash=password_service.hash("summary-viewer-fixture-123!"),
            is_active=True,
            is_system_admin=False,
            requires_password_change=False,
        )
        session.add(viewer)
        await session.flush()
        session.add(
            OrganizationMember(
                organization_id=project.organization_id, user_id=viewer.id, role="member"
            )
        )
        session.add(
            ProjectMember(project_id=project_id, user_id=viewer.id, role=ProjectRole.VIEWER)
        )
        for index in range(150):
            session.add(
                FlakyRecord(
                    project_id=project_id,
                    target_type="workflow",
                    target_id=uuid4(),
                    target_version=1,
                    flaky_score=5 if index < 120 else 0,
                    quarantined=index < 10 or 100 <= index < 120,
                    updated_at=stamp + timedelta(seconds=index),
                )
            )
        session.add(
            FlakyRecord(
                project_id=UUID(foreign.json()["id"]),
                target_type="workflow",
                target_id=uuid4(),
                target_version=1,
                flaky_score=100,
                quarantined=True,
            )
        )
        await session.commit()
    login = await context.client.post(
        "/api/v1/auth/login",
        json={"email": viewer.email, "password": "summary-viewer-fixture-123!"},
    )
    assert login.status_code == 200
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    async with context.session_maker() as session:
        audit_count = await session.scalar(select(func.count()).select_from(AuditLog))
    for authorization in [headers, viewer_headers]:
        response = await context.client.get(
            f"/api/v1/projects/{project_id}/flaky-tests/summary", headers=authorization
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["project_id"] == str(project_id)
        assert data["scope"] == "project_cumulative"
        assert data["record_total"] == data["asset_total"] == 150
        assert data["flaky_total"] == data["flaky_version_total"] == 120
        assert data["quarantined_total"] == data["quarantined_version_total"] == 30
        assert datetime.fromisoformat(data["oldest_updated_at"].replace("Z", "+00:00")) == stamp
        assert datetime.fromisoformat(
            data["latest_updated_at"].replace("Z", "+00:00")
        ) == stamp + timedelta(seconds=149)
        assert datetime.fromisoformat(data["observed_at"].replace("Z", "+00:00")) >= stamp
    denied = await context.client.get(
        f"/api/v1/projects/{foreign.json()['id']}/flaky-tests/summary", headers=viewer_headers
    )
    assert denied.status_code == 404
    assert denied.json()["error"]["trace_id"]
    missing = await context.client.get(
        f"/api/v1/projects/{uuid4()}/flaky-tests/summary", headers=headers
    )
    assert missing.status_code == 404 and missing.json()["error"]["trace_id"]
    assert (
        await context.client.get(f"/api/v1/projects/{project_id}/flaky-tests/summary")
    ).status_code == 401
    async with context.session_maker() as session:
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == audit_count


@pytest.mark.asyncio
async def test_flaky_summary_distinguishes_assets_versions_zero_scores_and_empty_projects(
    tasking_context: TaskingTestContext,
) -> None:
    context = tasking_context
    headers = await _login_headers(context.client)
    created = await context.client.post(
        "/api/v1/projects", headers=headers, json={"name": "Version summary fixture"}
    )
    project_id = UUID(created.json()["id"])
    path = f"/api/v1/projects/{project_id}/flaky-tests/summary"
    empty = await context.client.get(path, headers=headers)
    assert empty.status_code == 200, empty.text
    assert all(
        empty.json()[field] == 0
        for field in [
            "asset_total",
            "record_total",
            "flaky_total",
            "flaky_version_total",
            "quarantined_total",
            "quarantined_version_total",
        ]
    )
    assert empty.json()["oldest_updated_at"] is None
    assert empty.json()["latest_updated_at"] is None
    target_id = uuid4()
    async with context.session_maker() as session:
        for kind, identifier, version, score, isolated in [
            ("workflow", target_id, 1, 25, True),
            ("workflow", target_id, 2, 0, False),
            ("workflow", target_id, 3, 25, True),
            ("case", target_id, 1, 25, True),
            ("workflow", uuid4(), 1, 0, True),
        ]:
            session.add(
                FlakyRecord(
                    project_id=project_id,
                    target_type=kind,
                    target_id=identifier,
                    target_version=version,
                    flaky_score=score,
                    quarantined=isolated,
                )
            )
        await session.commit()
    result = await context.client.get(path, headers=headers)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["asset_total"] == 3 and data["record_total"] == 5
    assert data["flaky_total"] == 2 and data["flaky_version_total"] == 3
    assert data["quarantined_total"] == 3 and data["quarantined_version_total"] == 4
