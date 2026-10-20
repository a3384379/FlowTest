from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_tasking_api import (
    AssetHistoryFixture,
)
from test_tasking_api import (
    asset_history_fixture as asset_history_fixture,
)
from test_tasking_api import (
    tasking_context as tasking_context,
)

from app.core.errors import AppError
from app.domain.asset_catalog import AssetCatalogScope, AssetPublication
from app.domain.test_assets import definition_fingerprint
from app.models import tasking as task_models
from app.models import test_assets as models
from app.models.access import User
from app.models.api_assets import Environment
from app.models.workflows import WorkflowExecution
from app.services.test_assets import TestCaseService as CaseService


@pytest.mark.asyncio
async def test_catalog_filters_latest_run_before_result_and_environment(
    asset_history_fixture: AssetHistoryFixture,
) -> None:
    fixture = asset_history_fixture
    root = f"/api/v1/projects/{fixture.project_id}"
    async with fixture.context.session_maker() as session:
        direct = await session.get(WorkflowExecution, fixture.direct_execution_id)
        assert direct is not None
        environment_id = str(direct.environment_id)
        children = (
            await session.scalars(
                select(WorkflowExecution).where(WorkflowExecution.parent_execution_id == direct.id)
            )
        ).all()
        for child in children:
            child.status = "failed"
        await session.commit()
    for resource, status, total in [
        ("test-cases", "passed", 1),
        ("test-cases", "failed", 0),
        ("test-suites", "queued", 1),
        ("test-suites", "passed", 0),
    ]:
        response = await fixture.context.client.get(
            f"{root}/{resource}",
            headers=fixture.headers,
            params={
                "publication": "published",
                "latest_result": status,
                "environment_id": environment_id,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == total
        if resource == "test-cases" and total:
            latest = response.json()["items"][0]["latest_run"]
            assert latest["execution_id"] == str(fixture.direct_execution_id)
            assert latest["asset_version"] == 2 and latest["status"] == "passed"
    counts = await fixture.context.client.get(
        f"{root}/test-assets/directory-counts",
        headers=fixture.headers,
        params={
            "publication": "published",
            "latest_result": "queued",
            "environment_id": environment_id,
        },
    )
    assert counts.status_code == 200, counts.text
    assert (counts.json()["case_total"], counts.json()["suite_total"]) == (0, 1)
    for resource in ["test-cases", "test-suites"]:
        unrun = await fixture.context.client.get(
            f"{root}/{resource}", headers=fixture.headers, params={"latest_result": "unrun"}
        )
        assert unrun.json()["total"] == 0
        unavailable = await fixture.context.client.get(
            f"{root}/{resource}", headers=fixture.headers, params={"environment_id": str(uuid4())}
        )
        assert unavailable.json()["total"] == 0


@pytest.mark.asyncio
async def test_catalog_scope_and_directory_counts_cover_more_than_one_hundred_cases(
    asset_history_fixture: AssetHistoryFixture,
) -> None:
    fixture = asset_history_fixture
    expected: set[str] = set()
    async with fixture.context.session_maker() as session:
        source = await session.get(models.TestCase, UUID(fixture.case_id))
        execution = await session.get(WorkflowExecution, fixture.direct_execution_id)
        assert source is not None and execution is not None
        for index in range(121):
            case = models.TestCase(
                id=uuid4(),
                project_id=source.project_id,
                name=f"范围筛选 {index:03}",
                tags=["范围筛选"],
                draft_definition=source.draft_definition,
                current_version=1,
                created_by_id=source.created_by_id,
            )
            session.add(case)
            await session.flush()
            session.add(
                models.TestCaseVersion(
                    test_case_id=case.id,
                    version=1,
                    definition=source.draft_definition,
                    fingerprint=definition_fingerprint(source.draft_definition),
                    created_by_id=source.created_by_id,
                )
            )
            session.add(
                WorkflowExecution(
                    project_id=source.project_id,
                    workflow_id=execution.workflow_id,
                    workflow_version_id=execution.workflow_version_id,
                    environment_id=execution.environment_id,
                    triggered_by_id=source.created_by_id,
                    source_case_id=case.id,
                    source_case_version=1,
                    source_trigger="direct",
                    status="failed",
                    snapshot=execution.snapshot,
                    started_at=execution.started_at + timedelta(seconds=index),
                )
            )
            expected.add(str(case.id))
        await session.commit()
        environment_id = str(execution.environment_id)
    root = f"/api/v1/projects/{fixture.project_id}"
    scope = {
        "tag": "范围筛选",
        "publication": "published",
        "latest_result": "failed",
        "environment_id": environment_id,
        "order": "name_asc",
    }
    rows: list[dict[str, object]] = []
    for page in [1, 2]:
        response = await fixture.context.client.get(
            f"{root}/test-cases",
            headers=fixture.headers,
            params={**scope, "page_size": 100, "page": page},
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 121
        rows.extend(response.json()["items"])
    assert len(rows) == 121 and {str(row["id"]) for row in rows} == expected
    assert [row["name"] for row in rows] == [f"范围筛选 {index:03}" for index in range(121)]
    counts = await fixture.context.client.get(
        f"{root}/test-assets/directory-counts", headers=fixture.headers, params=scope
    )
    assert counts.status_code == 200, counts.text
    assert counts.json()["case_total"] == counts.json()["published_case_total"] == 121
    assert counts.json()["unfiled_cases"] == 121 and counts.json()["suite_total"] == 0


@pytest.mark.asyncio
async def test_catalog_pending_plan_state_is_not_unrun_and_uses_latest_environment(
    asset_history_fixture: AssetHistoryFixture,
) -> None:
    fixture = asset_history_fixture
    async with fixture.context.session_maker() as session:
        source = await session.get(models.TestCase, UUID(fixture.case_id))
        direct = await session.get(WorkflowExecution, fixture.direct_execution_id)
        assert source is not None and direct is not None
        pending = await session.scalar(
            select(task_models.TestPlanRunItem).where(
                task_models.TestPlanRunItem.target_id == source.id,
                task_models.TestPlanRunItem.workflow_execution_id.is_(None),
            )
        )
        assert pending is not None
        plan_run = await session.get(task_models.TestPlanRun, pending.test_plan_run_id)
        assert plan_run is not None
        environment = Environment(
            project_id=source.project_id,
            name="已归档的后续运行环境",
            base_url="https://catalog.example.test",
            archived_at=datetime.now(UTC),
            created_by_id=source.created_by_id,
        )
        session.add(environment)
        await session.flush()
        pending.environment_id = environment.id
        plan_run.created_at = direct.started_at + timedelta(minutes=10)
        unrun = models.TestCase(
            project_id=source.project_id,
            name="仅草稿未运行",
            draft_definition=source.draft_definition,
            created_by_id=source.created_by_id,
        )
        session.add(unrun)
        await session.commit()
        pending_id, plan_run_id = pending.id, plan_run.id
        old_environment, new_environment = str(direct.environment_id), str(environment.id)
        unrun_id = str(unrun.id)
    root = f"/api/v1/projects/{fixture.project_id}"
    for status in ["queued", "running", "cancelled", "quarantined"]:
        async with fixture.context.session_maker() as session:
            pending = await session.get(task_models.TestPlanRunItem, pending_id)
            assert pending is not None
            pending.status = status
            await session.commit()
        for resource in ["test-cases", "test-suites"]:
            scoped = await fixture.context.client.get(
                f"{root}/{resource}",
                headers=fixture.headers,
                params={"latest_result": status, "environment_id": new_environment},
            )
            assert scoped.status_code == 200, scoped.text
            assert scoped.json()["total"] == 1
            if resource == "test-cases":
                latest = scoped.json()["items"][0]["latest_run"]
                assert latest["status"] == status and latest["execution_id"] is None
                assert latest["plan_run_id"] == str(plan_run_id)
                assert latest["asset_version"] == 1
            older = await fixture.context.client.get(
                f"{root}/{resource}",
                headers=fixture.headers,
                params={"latest_result": status, "environment_id": old_environment},
            )
            assert older.json()["total"] == 0
    unrun_response = await fixture.context.client.get(
        f"{root}/test-cases",
        headers=fixture.headers,
        params={"publication": "unpublished", "latest_result": "unrun"},
    )
    assert unrun_response.json()["total"] == 1
    assert unrun_response.json()["items"][0]["id"] == unrun_id
    assert unrun_response.json()["items"][0]["latest_run"] is None
    options = await fixture.context.client.get(
        f"{root}/test-assets/environment-options",
        headers=fixture.headers,
        params={"selected_id": new_environment},
    )
    assert options.status_code == 200, options.text
    assert options.json()["items"] == [{"id": new_environment, "name": "已归档的后续运行环境"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope",
    [
        {"latest_result": "unknown"},
        {"publication": "unknown"},
        {"order": "unknown"},
        {"environment_id": "invalid"},
    ],
)
async def test_catalog_invalid_scope_is_not_silently_broadened(
    asset_history_fixture: AssetHistoryFixture,
    scope: dict[str, str],
) -> None:
    fixture = asset_history_fixture
    for resource in ["test-cases", "test-suites", "test-assets/directory-counts"]:
        response = await fixture.context.client.get(
            f"/api/v1/projects/{fixture.project_id}/{resource}",
            headers=fixture.headers,
            params=scope,
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_catalog_policy_is_enforced_for_non_http_callers(
    asset_history_fixture: AssetHistoryFixture,
) -> None:
    fixture = asset_history_fixture
    async with fixture.context.session_maker() as session:
        model = await session.get(models.TestCase, UUID(fixture.case_id))
        assert model is not None
        user = await session.get(User, model.created_by_id)
        assert user is not None
        with pytest.raises(AppError, match="发布状态"):
            await CaseService(session).list_cases(
                actor=user,
                project_id=model.project_id,
                search=None,
                tag=None,
                is_template=None,
                page=1,
                page_size=20,
                scope=AssetCatalogScope(publication=cast(AssetPublication, "unknown")),
            )


@pytest.mark.asyncio
async def test_asset_history_environment_options_paginate_archives_and_isolate_projects(
    asset_history_fixture: AssetHistoryFixture,
) -> None:
    fixture = asset_history_fixture
    async with fixture.context.session_maker() as session:
        source = await session.get(models.TestCase, UUID(fixture.case_id))
        execution = await session.get(WorkflowExecution, fixture.direct_execution_id)
        assert source is not None and execution is not None
        for index in range(105):
            environment = Environment(
                project_id=source.project_id,
                name=f"历史环境{index:03}",
                base_url="https://catalog.example.test",
                archived_at=datetime.now(UTC),
                created_by_id=source.created_by_id,
            )
            session.add(environment)
            await session.flush()
            session.add(
                WorkflowExecution(
                    project_id=source.project_id,
                    workflow_id=execution.workflow_id,
                    workflow_version_id=execution.workflow_version_id,
                    environment_id=environment.id,
                    triggered_by_id=source.created_by_id,
                    source_case_id=source.id,
                    source_case_version=2,
                    source_trigger="direct",
                    status="passed",
                    snapshot=execution.snapshot,
                    started_at=execution.started_at + timedelta(seconds=index),
                )
            )
        from app.models.access import Project

        foreign_project = Project(
            name="环境目录隔离", description="", created_by_id=source.created_by_id
        )
        session.add(foreign_project)
        await session.flush()
        foreign_environment = Environment(
            project_id=foreign_project.id,
            name="历史环境越界",
            base_url="https://catalog.example.test",
            created_by_id=source.created_by_id,
        )
        session.add(foreign_environment)
        await session.commit()
        foreign_id = str(foreign_environment.id)
    path = f"/api/v1/projects/{fixture.project_id}/test-assets/environment-options"
    first = await fixture.context.client.get(
        path, headers=fixture.headers, params={"search": "历史环境", "page_size": 100}
    )
    second = await fixture.context.client.get(
        path, headers=fixture.headers, params={"search": "历史环境", "page_size": 100, "page": 2}
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 105
    assert len(first.json()["items"]) == 100 and len(second.json()["items"]) == 5
    assert second.json()["items"][-1]["name"] == "历史环境104"
    selected = await fixture.context.client.get(
        path, headers=fixture.headers, params={"selected_id": second.json()["items"][-1]["id"]}
    )
    assert selected.json()["items"] == second.json()["items"][-1:]
    foreign = await fixture.context.client.get(
        path, headers=fixture.headers, params={"selected_id": foreign_id}
    )
    assert foreign.json()["total"] == 0
    literal = await fixture.context.client.get(
        path, headers=fixture.headers, params={"search": "%"}
    )
    assert literal.json()["total"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["case", "suite", "report"])
async def test_catalog_page_total_and_evidence_share_one_read_snapshot(
    asset_history_fixture: AssetHistoryFixture,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    import asyncio
    from typing import Any

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.base import Executable

    fixture = asset_history_fixture
    captured = asyncio.Event()
    committed = asyncio.Event()
    intercepted = False
    execute = AsyncSession.execute
    scalars = AsyncSession.scalars

    async def capture(statement: Executable) -> None:
        nonlocal intercepted
        sql = str(statement).lower()
        marker = {
            "case": "test_cases.draft_definition",
            "suite": "test_suites.draft_definition",
            "report": "workflow_executions.snapshot",
        }[kind]
        if not intercepted and marker in sql:
            intercepted = True
            captured.set()
            await committed.wait()

    async def intercept(
        session: AsyncSession, statement: Executable, *args: Any, **kwargs: Any
    ) -> Any:
        result = await execute(session, statement, *args, **kwargs)
        await capture(statement)
        return result

    async def intercept_scalars(
        session: AsyncSession, statement: Executable, *args: Any, **kwargs: Any
    ) -> Any:
        result = await scalars(session, statement, *args, **kwargs)
        await capture(statement)
        return result

    async def write_later_run() -> None:
        await captured.wait()
        try:
            async with fixture.context.session_maker() as session:
                if kind == "suite":
                    item = await session.scalar(
                        select(task_models.TestPlanRunItem).where(
                            task_models.TestPlanRunItem.target_id == UUID(fixture.case_id),
                            task_models.TestPlanRunItem.status == "queued",
                        )
                    )
                    assert item is not None
                    item.status = "passed"
                    await session.commit()
                    return
                if kind == "report":
                    failed = await session.get(WorkflowExecution, fixture.retry_execution_id)
                    assert failed is not None
                    failed.status = "passed"
                    await session.commit()
                    return
                source = await session.get(WorkflowExecution, fixture.direct_execution_id)
                assert source is not None
                session.add(
                    WorkflowExecution(
                        project_id=source.project_id,
                        workflow_id=source.workflow_id,
                        workflow_version_id=source.workflow_version_id,
                        environment_id=source.environment_id,
                        triggered_by_id=source.triggered_by_id,
                        source_case_id=source.source_case_id,
                        source_case_version=source.source_case_version,
                        source_trigger="direct",
                        status="running",
                        snapshot=source.snapshot,
                        started_at=source.started_at + timedelta(hours=1),
                    )
                )
                await session.commit()
        finally:
            committed.set()

    monkeypatch.setattr(AsyncSession, "execute", intercept)
    monkeypatch.setattr(AsyncSession, "scalars", intercept_scalars)
    writer = asyncio.create_task(write_later_run())
    try:
        resource, params = {
            "case": ("test-cases", {"latest_result": "passed"}),
            "suite": ("test-suites", {"latest_result": "queued"}),
            "report": (
                "reports/executions",
                {
                    "status": "failed",
                    "source_case_id": fixture.case_id,
                    "started_from": "2026-09-01T00:00:00Z",
                    "started_until": "2026-09-02T00:00:00Z",
                },
            ),
        }[kind]
        response = await fixture.context.client.get(
            f"/api/v1/projects/{fixture.project_id}/{resource}",
            headers=fixture.headers,
            params=params,
        )
        await asyncio.wait_for(writer, 5)
    finally:
        writer.cancel()
        await asyncio.gather(writer, return_exceptions=True)
    assert intercepted
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    if kind == "case":
        assert response.json()["items"][0]["latest_run"]["status"] == "passed"
        assert response.json()["items"][0]["latest_run"]["execution_id"] == str(
            fixture.direct_execution_id
        )
    if kind == "report":
        assert response.json()["items"][0]["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["test-cases", "test-suites", "reports/executions"])
async def test_catalog_empty_page_preserves_full_scope_total(
    asset_history_fixture: AssetHistoryFixture, resource: str
) -> None:
    fixture = asset_history_fixture
    path = f"/api/v1/projects/{fixture.project_id}/{resource}"
    first = await fixture.context.client.get(path, headers=fixture.headers)
    outside = await fixture.context.client.get(path, headers=fixture.headers, params={"page": 1000})
    assert first.status_code == outside.status_code == 200
    assert first.json()["total"] > 0
    assert outside.json()["total"] == first.json()["total"]
    assert outside.json()["items"] == []
