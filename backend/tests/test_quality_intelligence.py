from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_ai_job_dispatcher
from app.core.config import settings
from app.core.database import get_session
from app.core.security import password_service
from app.domain.access import ProjectRole
from app.domain.quality_intelligence import (
    FailureObservation,
    RiskInput,
    calculate_release_risk,
    cluster_failures,
)
from app.main import app
from app.models import Base
from app.models.access import ProjectMember, User
from app.models.ai import AIChangeItem, AIChangeSet, AIJob
from app.models.impact import CoverageSnapshot, ImpactRun
from app.models.impact import TestSelection as ImpactTestSelection
from app.models.workflows import Workflow
from app.services.ai import AIJobRunner, AIProvider, AIProviderResult

ADMIN_EMAIL = "quality-intelligence@example.com"
ADMIN_PASSWORD = "quality-intelligence-password-123!"
VIEWER_EMAIL = "quality-intelligence-viewer@example.com"
VIEWER_PASSWORD = "quality-intelligence-viewer-password-123!"


@dataclass(slots=True)
class FakeQueue:
    job_ids: list[UUID] = field(default_factory=list)

    def start_ai_job(self, job_id: UUID) -> None:
        self.job_ids.append(job_id)


@dataclass(slots=True)
class QualityContext:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]
    queue: FakeQueue


class ChangeSetProvider:
    async def generate(
        self,
        *,
        job_type: str,
        sanitized_input: dict[str, JsonValue],
        output_schema: dict[str, JsonValue],
    ) -> AIProviderResult:
        assert job_type == "change_set"
        metadata = cast(dict[str, JsonValue], sanitized_input["metadata"])
        assert metadata["review_policy"] == {
            "automatic_execute": False,
            "automatic_publish": False,
            "draft_only": True,
            "max_items": 50,
        }
        assert output_schema["type"] == "object"
        return AIProviderResult(
            payload={
                "suggestions": [
                    {
                        "type": "workflow",
                        "title": "补充开票异常流程",
                        "content": {
                            "action": "create",
                            "name": "AI 变更集草稿流程",
                            "description": "只生成草稿",
                            "definition": _workflow_definition(),
                        },
                    }
                ]
            },
            token_usage={"input_tokens": 40, "output_tokens": 20},
        )


class ForbiddenAssetProvider:
    async def generate(
        self,
        *,
        job_type: str,
        sanitized_input: dict[str, JsonValue],
        output_schema: dict[str, JsonValue],
    ) -> AIProviderResult:
        assert job_type == "change_set"
        return AIProviderResult(
            payload={
                "suggestions": [
                    {
                        "type": "credential",
                        "title": "越权修改 Credential",
                        "content": {"action": "create", "name": "forbidden"},
                    }
                ]
            },
            token_usage={"input_tokens": 10, "output_tokens": 10},
        )


@dataclass(frozen=True, slots=True)
class UpdateWorkflowProvider:
    workflow_id: str

    async def generate(
        self,
        *,
        job_type: str,
        sanitized_input: dict[str, JsonValue],
        output_schema: dict[str, JsonValue],
    ) -> AIProviderResult:
        assert job_type == "change_set"
        return AIProviderResult(
            payload={
                "suggestions": [
                    {
                        "type": "workflow",
                        "title": "更新受影响流程",
                        "content": {
                            "action": "update",
                            "target_id": self.workflow_id,
                            "name": "AI 建议名称",
                            "definition": _workflow_definition(),
                        },
                    }
                ]
            },
            token_usage={"input_tokens": 20, "output_tokens": 20},
        )


@pytest.fixture
async def quality_context(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[QualityContext]:
    monkeypatch.setattr(settings, "feature_quality_intelligence_enabled", True)
    monkeypatch.setattr(settings, "feature_ai_enabled", True)
    monkeypatch.setattr(settings, "ai_base_url", "https://ai.example/v1")
    monkeypatch.setattr(settings, "ai_model", "quality-v3")
    monkeypatch.setattr(settings, "ai_api_key", "never-persist-provider-key")
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add_all(
            [
                User(
                    email=ADMIN_EMAIL,
                    display_name="Quality administrator",
                    password_hash=password_service.hash(ADMIN_PASSWORD),
                    is_active=True,
                    is_system_admin=True,
                    requires_password_change=False,
                ),
                User(
                    email=VIEWER_EMAIL,
                    display_name="Quality viewer",
                    password_hash=password_service.hash(VIEWER_PASSWORD),
                    is_active=True,
                    is_system_admin=False,
                    requires_password_change=False,
                ),
            ]
        )
        await session.commit()
    queue = FakeQueue()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_ai_job_dispatcher] = lambda: queue
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield QualityContext(client=client, sessions=sessions, queue=queue)
    app.dependency_overrides.clear()
    await engine.dispose()


def test_failure_clusters_are_deterministic_and_compare_baseline() -> None:
    now = datetime.now(UTC)
    workflow_id = uuid4()
    current = tuple(
        FailureObservation(
            execution_id=uuid4(),
            workflow_id=workflow_id,
            workflow_name="支付流程",
            category="timeout",
            error_code="HTTP_TIMEOUT",
            node_type="api",
            occurred_at=now - timedelta(minutes=index),
        )
        for index in range(3)
    )
    baseline = (current[0],)
    clusters = cluster_failures(current, baseline)
    assert len(clusters) == 1
    assert clusters[0].occurrence_count == 3
    assert clusters[0].baseline_count == 1
    assert clusters[0].regression_percent == 200
    assert clusters[0].affected_workflow_names == ("支付流程",)
    assert len(clusters[0].sample_execution_ids) == 3
    assert clusters == cluster_failures(tuple(reversed(current)), baseline)


def test_release_risk_score_is_bounded_and_explainable() -> None:
    result = calculate_release_risk(
        RiskInput(
            coverage_percent=60,
            breaking_changes=3,
            current_total=100,
            current_failures=20,
            baseline_total=100,
            baseline_failures=5,
            regressed_clusters=2,
            unsafe_contracts=1,
            unknown_contracts=1,
            performance_regression_percent=40,
            flaky_assets=2,
        )
    )
    assert result.score == 54
    assert result.level == "high"
    assert result.quality_score == 46
    assert [factor["code"] for factor in result.factors] == [
        "coverage_gap",
        "breaking_changes",
        "failure_regression",
        "failure_clusters",
        "contract_compatibility",
        "performance_regression",
        "flaky_assets",
    ]
    assert sum(float(cast(float, factor["score"])) for factor in result.factors) == result.score


@pytest.mark.asyncio
async def test_release_risk_api_persists_evidence_and_enforces_project_scope(
    quality_context: QualityContext,
) -> None:
    headers = await _login(quality_context.client)
    project_id = await _project(quality_context.client, headers, "质量智能项目")
    other_project_id = await _project(quality_context.client, headers, "隔离项目")
    impact_run_id = await _seed_impact(quality_context.sessions, project_id)
    created = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/release-risks",
        headers=headers,
        json={"impact_run_id": impact_run_id, "title": "候选版本风险", "window_days": 30},
    )
    assert created.status_code == 201, created.text
    risk = created.json()
    assert risk["score"] == 11.25
    assert risk["risk_level"] == "low"
    assert risk["evidence_snapshot"]["impact"]["coverage_percent"] == 75
    assert risk["evidence_snapshot"]["impact"]["breaking_change_count"] == 1
    assert risk["recommended_tests"][0]["target_id"] == "workflow-target"
    assert risk["failure_clusters"] == []
    assert len(risk["quality_trend"]) == 30

    listed = await quality_context.client.get(
        f"/api/v1/projects/{project_id}/release-risks", headers=headers
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    isolated = await quality_context.client.get(
        f"/api/v1/projects/{other_project_id}/release-risks/{risk['id']}", headers=headers
    )
    assert isolated.status_code == 404
    assert isolated.json()["error"]["code"] == "RELEASE_RISK_NOT_FOUND"


@pytest.mark.asyncio
async def test_ai_change_set_requires_item_review_and_only_creates_draft(
    quality_context: QualityContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = await _login(quality_context.client)
    project_id = await _project(quality_context.client, headers, "AI 变更集项目")
    impact_run_id = await _seed_impact(quality_context.sessions, project_id)
    risk_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/release-risks",
        headers=headers,
        json={"impact_run_id": impact_run_id, "title": "AI 风险证据", "window_days": 7},
    )
    assert risk_response.status_code == 201, risk_response.text
    risk_id = risk_response.json()["id"]
    created = await quality_context.client.post(
        "/api/v1/ai/change-sets",
        headers=headers,
        json={
            "project_id": project_id,
            "impact_run_id": impact_run_id,
            "release_risk_id": risk_id,
            "title": "开票变更集",
        },
    )
    assert created.status_code == 202, created.text
    change_set_id = created.json()["id"]
    assert created.json()["status"] == "generating"
    assert len(quality_context.queue.job_ids) == 1

    async with quality_context.sessions() as session:
        job = await session.get(AIJob, quality_context.queue.job_ids[0])
        assert job is not None
        completed = await AIJobRunner(session, ChangeSetProvider()).run(job.id)
        assert completed.status == "completed"

    detail = await quality_context.client.get(
        f"/api/v1/ai/change-sets/{change_set_id}", headers=headers
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "draft"
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["review_status"] == "pending"

    original_commit = AsyncSession.commit
    commit_count = 0

    async def tracked_commit(session: AsyncSession) -> None:
        nonlocal commit_count
        commit_count += 1
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, "commit", tracked_commit)
    accepted = await quality_context.client.post(
        f"/api/v1/ai/change-sets/{change_set_id}/items/{item['id']}/accept",
        headers=headers,
        json={"content": item["proposed_content"], "note": "人工核对后接受"},
    )
    assert accepted.status_code == 200, accepted.text
    assert commit_count == 1
    assert accepted.json()["materialized_resource_type"] == "workflow"
    async with quality_context.sessions() as session:
        workflow = await session.get(Workflow, UUID(accepted.json()["materialized_resource_id"]))
        assert workflow is not None
        assert workflow.current_version is None
        assert workflow.draft_revision == 1

    repeated = await quality_context.client.post(
        f"/api/v1/ai/change-sets/{change_set_id}/items/{item['id']}/reject",
        headers=headers,
        json={"note": "不能重复审核"},
    )
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "AI_CHANGE_ITEM_ALREADY_REVIEWED"


@pytest.mark.asyncio
async def test_ai_change_set_viewer_can_read_but_cannot_create_or_review(
    quality_context: QualityContext,
) -> None:
    admin_headers = await _login(quality_context.client)
    project_id = await _project(quality_context.client, admin_headers, "AI 只读权限项目")
    impact_run_id = await _seed_impact(quality_context.sessions, project_id)
    risk_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/release-risks",
        headers=admin_headers,
        json={"impact_run_id": impact_run_id, "title": "权限风险证据", "window_days": 7},
    )
    assert risk_response.status_code == 201, risk_response.text
    risk_id = risk_response.json()["id"]
    change_set_id, item_id = await _generate_change_set(
        quality_context,
        headers=admin_headers,
        project_id=project_id,
        impact_run_id=impact_run_id,
        risk_id=risk_id,
        provider=ChangeSetProvider(),
    )
    await _grant_viewer(quality_context.sessions, project_id)
    viewer_headers = await _login(
        quality_context.client, email=VIEWER_EMAIL, password=VIEWER_PASSWORD
    )

    listed = await quality_context.client.get(
        "/api/v1/ai/change-sets",
        headers=viewer_headers,
        params={"project_id": project_id},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    detail = await quality_context.client.get(
        f"/api/v1/ai/change-sets/{change_set_id}", headers=viewer_headers
    )
    assert detail.status_code == 200, detail.text

    forbidden_create = await quality_context.client.post(
        "/api/v1/ai/change-sets",
        headers=viewer_headers,
        json={
            "project_id": project_id,
            "impact_run_id": impact_run_id,
            "release_risk_id": risk_id,
            "title": "Viewer 不得创建",
        },
    )
    assert forbidden_create.status_code == 403
    assert forbidden_create.json()["error"]["code"] == "PROJECT_FORBIDDEN"
    forbidden_review = await quality_context.client.post(
        f"/api/v1/ai/change-sets/{change_set_id}/items/{item_id}/accept",
        headers=viewer_headers,
        json={"note": "Viewer 不得审核"},
    )
    assert forbidden_review.status_code == 403
    assert forbidden_review.json()["error"]["code"] == "PROJECT_FORBIDDEN"
    async with quality_context.sessions() as session:
        item = await session.get(AIChangeItem, item_id)
        assert item is not None
        assert item.review_status == "pending"
        assert (
            await session.scalar(select(Workflow).where(Workflow.project_id == UUID(project_id)))
            is None
        )


@pytest.mark.asyncio
async def test_ai_change_set_rejects_forbidden_asset_types_without_materialization(
    quality_context: QualityContext,
) -> None:
    headers = await _login(quality_context.client)
    project_id = await _project(quality_context.client, headers, "AI 越权类型项目")
    impact_run_id = await _seed_impact(quality_context.sessions, project_id)
    risk_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/release-risks",
        headers=headers,
        json={"impact_run_id": impact_run_id, "title": "越权风险证据", "window_days": 7},
    )
    assert risk_response.status_code == 201, risk_response.text
    created = await quality_context.client.post(
        "/api/v1/ai/change-sets",
        headers=headers,
        json={
            "project_id": project_id,
            "impact_run_id": impact_run_id,
            "release_risk_id": risk_response.json()["id"],
            "title": "禁止 Credential 变更",
        },
    )
    assert created.status_code == 202, created.text

    async with quality_context.sessions() as session:
        job = await session.get(AIJob, quality_context.queue.job_ids[-1])
        assert job is not None
        failed = await AIJobRunner(session, ForbiddenAssetProvider()).run(job.id)
        assert failed.status == "failed"
        assert failed.error_code == "AI_RESPONSE_INVALID"
        change_set = await session.scalar(
            select(AIChangeSet).where(AIChangeSet.ai_job_id == job.id)
        )
        assert change_set is not None
        assert change_set.status == "failed"
        assert (
            await session.scalar(
                select(AIChangeItem).where(AIChangeItem.change_set_id == change_set.id)
            )
            is None
        )
        assert (
            await session.scalar(select(Workflow).where(Workflow.project_id == UUID(project_id)))
            is None
        )


@pytest.mark.asyncio
async def test_ai_change_set_detects_changed_target_before_applying_update(
    quality_context: QualityContext,
) -> None:
    headers = await _login(quality_context.client)
    project_id = await _project(quality_context.client, headers, "AI 目标漂移项目")
    workflow_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={
            "name": "人工维护流程",
            "description": "在 AI 审核前发生变化",
            "definition": _workflow_definition(),
        },
    )
    assert workflow_response.status_code == 201, workflow_response.text
    workflow_id = workflow_response.json()["id"]
    impact_run_id = await _seed_impact(quality_context.sessions, project_id, target_id=workflow_id)
    risk_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/release-risks",
        headers=headers,
        json={"impact_run_id": impact_run_id, "title": "目标漂移证据", "window_days": 7},
    )
    assert risk_response.status_code == 201, risk_response.text
    change_set_id, item_id = await _generate_change_set(
        quality_context,
        headers=headers,
        project_id=project_id,
        impact_run_id=impact_run_id,
        risk_id=risk_response.json()["id"],
        provider=UpdateWorkflowProvider(workflow_id),
    )

    async with quality_context.sessions() as session:
        workflow = await session.get(Workflow, UUID(workflow_id))
        assert workflow is not None
        workflow.draft_revision += 1
        await session.commit()

    conflicted = await quality_context.client.post(
        f"/api/v1/ai/change-sets/{change_set_id}/items/{item_id}/accept",
        headers=headers,
        json={"note": "目标已变化。不得覆盖"},
    )
    assert conflicted.status_code == 409, conflicted.text
    assert conflicted.json()["error"]["code"] == "AI_CHANGE_TARGET_CONFLICT"
    async with quality_context.sessions() as session:
        item = await session.get(AIChangeItem, item_id)
        workflow = await session.get(Workflow, UUID(workflow_id))
        assert item is not None
        assert item.review_status == "pending"
        assert workflow is not None
        assert workflow.name == "人工维护流程"
        assert workflow.draft_revision == 2


async def _login(
    client: AsyncClient, *, email: str = ADMIN_EMAIL, password: str = ADMIN_PASSWORD
) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _project(client: AsyncClient, headers: dict[str, str], name: str) -> str:
    response = await client.post(
        "/api/v1/projects", headers=headers, json={"name": name, "description": "S30"}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _generate_change_set(
    context: QualityContext,
    *,
    headers: dict[str, str],
    project_id: str,
    impact_run_id: str,
    risk_id: str,
    provider: AIProvider,
) -> tuple[str, UUID]:
    created = await context.client.post(
        "/api/v1/ai/change-sets",
        headers=headers,
        json={
            "project_id": project_id,
            "impact_run_id": impact_run_id,
            "release_risk_id": risk_id,
            "title": "权限变更集",
        },
    )
    assert created.status_code == 202, created.text
    async with context.sessions() as session:
        job = await session.get(AIJob, context.queue.job_ids[-1])
        assert job is not None
        completed = await AIJobRunner(session, provider).run(job.id)
        assert completed.status == "completed"
        change_set = await session.scalar(
            select(AIChangeSet).where(AIChangeSet.ai_job_id == job.id)
        )
        assert change_set is not None
        item_id = await session.scalar(
            select(AIChangeItem.id).where(AIChangeItem.change_set_id == change_set.id)
        )
        assert item_id is not None
        return str(change_set.id), item_id


async def _grant_viewer(sessions: async_sessionmaker[AsyncSession], project_id: str) -> None:
    async with sessions() as session:
        viewer_id = await session.scalar(select(User.id).where(User.email == VIEWER_EMAIL))
        assert viewer_id is not None
        session.add(
            ProjectMember(project_id=UUID(project_id), user_id=viewer_id, role=ProjectRole.VIEWER)
        )
        await session.commit()


async def _seed_impact(
    sessions: async_sessionmaker[AsyncSession],
    project_id: str,
    *,
    target_id: str = "workflow-target",
) -> str:
    async with sessions() as session:
        actor_id = await session.scalar(select(User.id).where(User.email == ADMIN_EMAIL))
        assert actor_id is not None
        run = ImpactRun(
            project_id=UUID(project_id),
            title="开票变更",
            source_ref="feature/invoice",
            status="completed",
            source_fingerprint="a" * 64,
            source_summary={"git": {"file_count": 1}},
            change_count=2,
            changes=[
                {
                    "key": "change-1",
                    "source_kind": "git",
                    "source_key": "invoice.py",
                    "change_type": "changed",
                    "severity": "breaking",
                    "label": "invoice.py",
                    "detail": "字段发生变化",
                    "before": None,
                    "after": None,
                },
                {
                    "key": "change-2",
                    "source_kind": "git",
                    "source_key": "invoice_test.py",
                    "change_type": "changed",
                    "severity": "info",
                    "label": "invoice_test.py",
                    "detail": "测试变化",
                    "before": None,
                    "after": None,
                },
            ],
            graph={"nodes": [], "edges": []},
            summary={"coverage_percent": 75.0},
            created_by_id=actor_id,
        )
        session.add(run)
        await session.flush()
        session.add(
            ImpactTestSelection(
                project_id=UUID(project_id),
                impact_run_id=run.id,
                strategy="explicit_mapping_v1",
                selected_assets=[
                    {
                        "asset_type": "workflow",
                        "target_type": "workflow",
                        "target_id": target_id,
                        "name": "开票流程",
                        "version": 1,
                        "risk": "high",
                        "change_keys": ["change-1"],
                        "reasons": ["显式 Mapping"],
                    }
                ],
                explanations=[],
                created_by_id=actor_id,
            )
        )
        session.add(
            CoverageSnapshot(
                project_id=UUID(project_id),
                impact_run_id=run.id,
                total_changes=2,
                covered_changes=1,
                coverage_percent=75.0,
                matrix=[],
                gaps=[{"change_key": "change-2"}],
                created_by_id=actor_id,
            )
        )
        await session.commit()
        return str(run.id)


def _workflow_definition() -> dict[str, JsonValue]:
    return {
        "schema_version": "1.0",
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "name": "开始",
                "position": {"x": 0, "y": 0},
                "config": {},
            },
            {
                "id": "end",
                "type": "end",
                "name": "结束",
                "position": {"x": 240, "y": 0},
                "config": {},
            },
        ],
        "edges": [{"id": "start-end", "source": "start", "target": "end"}],
    }
