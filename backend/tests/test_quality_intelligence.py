from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock
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
from app.core.errors import AppError
from app.core.security import password_service
from app.domain.access import ProjectRole
from app.domain.ai import REDACTED
from app.domain.quality_intelligence import (
    FailureClusterEvidence,
    FailureObservation,
    RiskEvidenceSnapshot,
    RiskInput,
    calculate_release_risk,
    cluster_failures,
    evidence_fingerprint,
)
from app.engine.contracts import WorkflowDefinition
from app.main import app
from app.models import Base
from app.models.access import ProjectMember, User
from app.models.ai import AIChangeItem, AIChangeSet, AIJob
from app.models.impact import CoverageSnapshot, ImpactRun
from app.models.impact import TestSelection as ImpactTestSelection
from app.models.quality_intelligence import FailureCluster, ReleaseRisk
from app.models.test_assets import TestCase as CaseModel
from app.models.workflows import Workflow, WorkflowExecution, WorkflowNodeExecution
from app.repositories.ai_change_sets import AIChangeSetRepository
from app.repositories.quality_intelligence import QualityIntelligenceRepository
from app.schemas.test_assets import TestCaseDefinitionInput as CaseDefinitionInput
from app.services.ai import AIJobRunner, AIProvider, AIProviderResult
from app.services.ai_change_sets import (
    MAX_CHANGE_SET_ITEMS,
    AIChangeSetService,
    _rehydrate_test_case_definition,
    _rehydrate_workflow_definition,
    _target_definition_for_ai,
    _test_case_create,
    _test_case_update,
    _validate_assertion_workflow_change,
    _workflow_create,
    _workflow_update,
)
from app.services.quality_intelligence import (
    _execution_counts,
    _quality_trend,
    _risk_fingerprint_payload,
)
from app.services.test_assets import TestCaseService as CaseService

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


@dataclass(slots=True)
class ChangeSetProvider:
    seen_input: dict[str, JsonValue] | None = None

    async def generate(
        self,
        *,
        job_type: str,
        sanitized_input: dict[str, JsonValue],
        output_schema: dict[str, JsonValue],
    ) -> AIProviderResult:
        assert job_type == "change_set"
        self.seen_input = sanitized_input
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


@dataclass(frozen=True, slots=True)
class AssertionOnlyProvider:
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
                        "type": "assertion",
                        "title": "补充状态码断言",
                        "content": {
                            "action": "update",
                            "target_id": self.workflow_id,
                            "status_code": 200,
                        },
                    }
                ]
            },
            token_usage={"input_tokens": 20, "output_tokens": 10},
        )


@dataclass(frozen=True, slots=True)
class RedactedAssertionUpdateProvider:
    workflow_id: str

    async def generate(
        self,
        *,
        job_type: str,
        sanitized_input: dict[str, JsonValue],
        output_schema: dict[str, JsonValue],
    ) -> AIProviderResult:
        assert job_type == "change_set"
        metadata = cast(dict[str, JsonValue], sanitized_input["metadata"])
        allowed_targets = cast(list[dict[str, JsonValue]], metadata["allowed_targets"])
        definition = deepcopy(cast(dict[str, JsonValue], allowed_targets[0]["draft_definition"]))
        nodes = cast(list[dict[str, JsonValue]], definition["nodes"])
        assertion = next(node for node in nodes if node["id"] == "assert-status")
        config = cast(dict[str, JsonValue], assertion["config"])
        assert config["source_node_id"] == REDACTED
        assert config["expression"] == REDACTED
        config["expected"] = 201
        return AIProviderResult(
            payload={
                "suggestions": [
                    {
                        "type": "assertion",
                        "title": "更新状态码断言",
                        "content": {
                            "action": "update",
                            "target_id": self.workflow_id,
                            "definition": definition,
                        },
                    }
                ]
            },
            token_usage={"input_tokens": 30, "output_tokens": 20},
        )


@dataclass(frozen=True, slots=True)
class DuplicateUpdateProvider:
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
                        "title": "更新流程草稿",
                        "content": {
                            "action": "update",
                            "target_id": self.workflow_id,
                            "name": "AI 更名流程",
                        },
                    },
                    {
                        "type": "assertion",
                        "title": "更新同一流程断言",
                        "content": {
                            "action": "update",
                            "target_id": self.workflow_id,
                            "definition": _workflow_definition_with_assertion(
                                start_name="开始", expected=201
                            ),
                        },
                    },
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


def test_release_risk_fingerprint_binds_window_and_cluster_contents() -> None:
    ended_at = datetime.now(UTC)
    started_at = ended_at - timedelta(days=7)
    cluster = FailureClusterEvidence(
        fingerprint="a" * 64,
        title="ASSERTION_FAILED · assert",
        category="assertion",
        error_code="ASSERTION_FAILED",
        node_type="assert",
        occurrence_count=1,
        baseline_count=0,
        affected_workflow_ids=(str(uuid4()),),
        affected_workflow_names=("支付流程",),
        sample_execution_ids=(str(uuid4()),),
        confidence=0.638,
        regression_percent=100.0,
        recommendation="核对断言。",
    )
    risk_result = calculate_release_risk(
        RiskInput(
            coverage_percent=100,
            breaking_changes=0,
            current_total=1,
            current_failures=1,
            baseline_total=0,
            baseline_failures=0,
            regressed_clusters=1,
            unsafe_contracts=0,
            unknown_contracts=0,
            performance_regression_percent=0,
            flaky_assets=0,
        )
    )
    common = {
        "algorithm_version": "release_risk_v1",
        "started_at": started_at,
        "ended_at": ended_at,
        "baseline_started_at": started_at - timedelta(days=7),
        "baseline_ended_at": started_at,
        "risk_result": risk_result,
        "evidence": cast(RiskEvidenceSnapshot, {}),
        "quality_trend": [],
        "recommended_tests": [],
    }
    original = _risk_fingerprint_payload(clusters=(cluster,), **common)
    changed_cluster = _risk_fingerprint_payload(
        clusters=(replace(cluster, error_code="HTTP_TIMEOUT"),), **common
    )
    changed_window = _risk_fingerprint_payload(
        clusters=(cluster,),
        **{**common, "ended_at": ended_at + timedelta(seconds=1)},
    )

    assert evidence_fingerprint(original) != evidence_fingerprint(changed_cluster)
    assert evidence_fingerprint(original) != evidence_fingerprint(changed_window)


def test_quality_trend_includes_current_day_executions() -> None:
    ended_at = datetime.now(UTC)
    started_on = (ended_at - timedelta(days=7)).date()
    execution = WorkflowExecution(started_at=ended_at, status="passed")

    trend = _quality_trend([execution], started_on, 7)

    assert len(trend) == 8
    assert trend[-1] == {
        "date": ended_at.date().isoformat(),
        "total": 1,
        "passed": 1,
        "failed": 0,
        "pass_rate": 100.0,
    }
    assert trend[0] == {
        "date": started_on.isoformat(),
        "total": 0,
        "passed": 0,
        "failed": 0,
        "pass_rate": None,
    }


def test_assertion_change_must_modify_typed_assertion_nodes() -> None:
    current_definition = _workflow_definition_with_assertion(start_name="开始", expected=200)
    target = Workflow(draft_definition=current_definition)
    metadata_only_change = WorkflowDefinition.model_validate(
        _workflow_definition_with_assertion(start_name="更名开始", expected=200)
    )

    with pytest.raises(AppError) as unchanged:
        _validate_assertion_workflow_change(target, metadata_only_change)

    assert unchanged.value.code == "AI_ASSERTION_DRAFT_INVALID"
    changed_assertion = WorkflowDefinition.model_validate(
        _workflow_definition_with_assertion(start_name="开始", expected=201)
    )
    _validate_assertion_workflow_change(target, changed_assertion)


def test_test_case_update_rejects_unsupported_or_empty_content() -> None:
    for content in ({}, {"unexpected": True}, {"name": None}):
        with pytest.raises(AppError) as invalid:
            _test_case_update(cast(dict[str, JsonValue], content))
        assert invalid.value.code == "AI_TEST_CASE_DRAFT_INVALID"

    update = _test_case_update({"description": "人工确认后清空描述"})
    assert update.description == "人工确认后清空描述"


def test_test_case_create_enforces_asset_name_and_tag_constraints() -> None:
    definition: dict[str, JsonValue] = {
        "workflow_id": str(uuid4()),
        "environment_id": str(uuid4()),
    }
    invalid_contents = (
        {"name": "   ", "definition": definition},
        {"name": 123, "definition": definition},
        {"tags": [f"tag-{index}" for index in range(21)], "definition": definition},
        {"tags": ["x" * 51], "definition": definition},
        {"unexpected": True, "definition": definition},
    )
    for content in invalid_contents:
        with pytest.raises(AppError) as invalid:
            _test_case_create("合法草稿名称", cast(dict[str, JsonValue], content))
        assert invalid.value.code == "AI_TEST_CASE_DRAFT_INVALID"

    create = _test_case_create("默认草稿名称", {"definition": definition})
    assert create.name == "默认草稿名称"
    assert create.tags == []


def test_workflow_create_and_update_enforce_draft_metadata_constraints() -> None:
    definition = _workflow_definition()
    invalid_contents = (
        {"name": "   ", "definition": definition},
        {"name": {"value": "x"}, "definition": definition},
        {"description": "x" * 4001, "definition": definition},
        {"unexpected": True, "definition": definition},
    )
    for content in invalid_contents:
        with pytest.raises(AppError) as invalid:
            _workflow_create("合法 Workflow 草稿", cast(dict[str, JsonValue], content))
        assert invalid.value.code == "AI_WORKFLOW_DRAFT_INVALID"

    create = _workflow_create("默认 Workflow 草稿", {"definition": definition})
    assert create.name == "默认 Workflow 草稿"
    with pytest.raises(AppError) as invalid_update:
        _workflow_update({"name": "   "})
    assert invalid_update.value.code == "AI_WORKFLOW_DRAFT_INVALID"


@pytest.mark.asyncio
async def test_change_set_prompt_recommendations_match_capped_allowed_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    service = AIChangeSetService(session)
    service._repository.list_failure_clusters = AsyncMock(return_value=[])
    project_id = uuid4()
    recommendations = [
        {
            "target_type": "workflow",
            "target_id": str(uuid4()),
            "name": f"Workflow {index}",
        }
        for index in range(MAX_CHANGE_SET_ITEMS + 1)
    ]
    risk = ReleaseRisk(
        id=uuid4(),
        project_id=project_id,
        impact_run_id=uuid4(),
        score=10.0,
        risk_level="low",
        factors=[],
        evidence_snapshot={},
        recommended_tests=recommendations,
    )

    async def target_snapshot(
        target_type: str, target_id: UUID, target_project_id: UUID
    ) -> dict[str, JsonValue]:
        assert target_project_id == project_id
        return {
            "target_type": target_type,
            "target_id": str(target_id),
            "snapshot_sha256": "a" * 64,
        }

    monkeypatch.setattr(service, "_target_snapshot", target_snapshot)
    metadata = await service._source_metadata(risk, [])
    allowed_targets = cast(list[dict[str, JsonValue]], metadata["allowed_targets"])
    advertised = cast(
        list[dict[str, JsonValue]],
        cast(dict[str, JsonValue], metadata["release_risk"])["recommended_tests"],
    )

    assert len(allowed_targets) == len(advertised) == MAX_CHANGE_SET_ITEMS
    assert [item["target_id"] for item in advertised] == [
        item["target_id"] for item in allowed_targets
    ]


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
    assert len(risk["quality_trend"]) == 31
    assert risk["quality_trend"][-1]["date"] == risk["window_ended_at"][:10]

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
    async with quality_context.sessions() as session:
        session.add(
            FailureCluster(
                project_id=UUID(project_id),
                release_risk_id=UUID(risk_id),
                fingerprint="f" * 64,
                title="ASSERTION_FAILED · assert",
                failure_category="assertion",
                error_code="ASSERTION_FAILED",
                node_type="assert",
                occurrence_count=3,
                baseline_count=1,
                affected_workflow_ids=["workflow-target"],
                affected_workflow_names=["开票异常流程"],
                sample_execution_ids=[str(uuid4())],
                confidence=0.8,
                regression_percent=200,
                recommendation="核对响应字段后更新断言草稿",
            )
        )
        await session.commit()
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

    provider = ChangeSetProvider()
    async with quality_context.sessions() as session:
        job = await session.get(AIJob, quality_context.queue.job_ids[0])
        assert job is not None
        completed = await AIJobRunner(session, provider).run(job.id)
        assert completed.status == "completed"
    assert provider.seen_input is not None
    provider_metadata = cast(dict[str, JsonValue], provider.seen_input["metadata"])
    release_risk = cast(dict[str, JsonValue], provider_metadata["release_risk"])
    failure_clusters = cast(list[dict[str, JsonValue]], release_risk["failure_clusters"])
    assert failure_clusters == [
        {
            "affected_workflow_ids": ["workflow-target"],
            "affected_workflow_names": ["开票异常流程"],
            "baseline_count": 1,
            "confidence": 0.8,
            "error_code": "ASSERTION_FAILED",
            "failure_category": "assertion",
            "fingerprint": "f" * 64,
            "node_type": "assert",
            "occurrence_count": 3,
            "recommendation": "核对响应字段后更新断言草稿",
            "regression_percent": 200.0,
            "title": "ASSERTION_FAILED · assert",
        }
    ]

    detail = await quality_context.client.get(
        f"/api/v1/ai/change-sets/{change_set_id}", headers=headers
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "draft"
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["review_status"] == "pending"

    empty_edit = await quality_context.client.post(
        f"/api/v1/ai/change-sets/{change_set_id}/items/{item['id']}/accept",
        headers=headers,
        json={"content": {}, "note": "显式空内容不得回退到 AI 原文"},
    )
    assert empty_edit.status_code == 422, empty_edit.text
    async with quality_context.sessions() as session:
        unchanged_item = await session.get(AIChangeItem, UUID(item["id"]))
        assert unchanged_item is not None
        assert unchanged_item.review_status == "pending"
        assert (
            await session.scalar(select(Workflow).where(Workflow.project_id == UUID(project_id)))
            is None
        )

    original_commit = AsyncSession.commit
    commit_count = 0

    async def tracked_commit(session: AsyncSession) -> None:
        nonlocal commit_count
        commit_count += 1
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, "commit", tracked_commit)
    lock_order: list[str] = []
    original_parent_lock = AIChangeSetRepository.get_change_set_for_update
    original_item_lock = AIChangeSetRepository.get_item_for_update

    async def tracked_parent_lock(
        repository: AIChangeSetRepository, target_change_set_id: UUID
    ) -> AIChangeSet | None:
        lock_order.append("change_set")
        return await original_parent_lock(repository, target_change_set_id)

    async def tracked_item_lock(
        repository: AIChangeSetRepository, target_item_id: UUID
    ) -> AIChangeItem | None:
        lock_order.append("item")
        return await original_item_lock(repository, target_item_id)

    monkeypatch.setattr(AIChangeSetRepository, "get_change_set_for_update", tracked_parent_lock)
    monkeypatch.setattr(AIChangeSetRepository, "get_item_for_update", tracked_item_lock)
    accepted = await quality_context.client.post(
        f"/api/v1/ai/change-sets/{change_set_id}/items/{item['id']}/accept",
        headers=headers,
        json={"content": item["proposed_content"], "note": "人工核对后接受"},
    )
    assert accepted.status_code == 200, accepted.text
    assert lock_order == ["change_set", "item"]
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
async def test_ai_change_set_redacts_runtime_values_from_target_snapshot(
    quality_context: QualityContext,
) -> None:
    headers = await _login(quality_context.client)
    project_id = await _project(quality_context.client, headers, "AI 目标脱敏项目")
    workflow_definition = _workflow_definition()
    workflow_definition["variables"] = {
        "session_id": "opaque-session-material",
        "region": "cn-north-1",
    }
    workflow_definition["nodes"][0]["config"] = {
        "headers": {"X-Session": "opaque-node-secret"},
        "body": {"customer": {"reference": "opaque-reference"}},
        "attempt": 3,
    }
    workflow_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "含运行时变量的流程", "definition": workflow_definition},
    )
    assert workflow_response.status_code == 201, workflow_response.text
    workflow_id = workflow_response.json()["id"]
    impact_run_id = await _seed_impact(
        quality_context.sessions,
        project_id,
        target_id=workflow_id,
        unsupported_asset_count=MAX_CHANGE_SET_ITEMS,
    )
    risk_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/release-risks",
        headers=headers,
        json={"impact_run_id": impact_run_id, "title": "脱敏风险证据", "window_days": 7},
    )
    assert risk_response.status_code == 201, risk_response.text

    created = await quality_context.client.post(
        "/api/v1/ai/change-sets",
        headers=headers,
        json={
            "project_id": project_id,
            "impact_run_id": impact_run_id,
            "release_risk_id": risk_response.json()["id"],
            "title": "目标脱敏变更集",
        },
    )
    assert created.status_code == 202, created.text

    async with quality_context.sessions() as session:
        job = await session.get(AIJob, quality_context.queue.job_ids[-1])
        change_set = await session.get(AIChangeSet, UUID(created.json()["id"]))
        assert job is not None
        assert change_set is not None
        allowed_targets = job.sanitized_input["metadata"]["allowed_targets"]
        recommended_tests = job.sanitized_input["metadata"]["release_risk"]["recommended_tests"]
        assert len(recommended_tests) == len(allowed_targets) == 1
        assert recommended_tests[0]["target_id"] == workflow_id
        target = allowed_targets[0]
        assert target["draft_definition"]["variables"] == {
            "session_id": REDACTED,
            "region": REDACTED,
        }
        assert target["draft_definition"]["nodes"][0]["config"] == {
            "headers": {"X-Session": REDACTED},
            "body": {"customer": {"reference": REDACTED}},
            "attempt": REDACTED,
        }
        assert "opaque-session-material" not in str(job.sanitized_input)
        assert "opaque-node-secret" not in str(job.sanitized_input)
        assert "opaque-reference" not in str(job.sanitized_input)
        assert "cn-north-1" not in str(change_set.source_snapshot)


def test_ai_target_snapshot_redacts_test_case_runtime_maps_without_mutating_source() -> None:
    definition = {
        "workflow_id": str(uuid4()),
        "environment_id": str(uuid4()),
        "runtime_variables": {"session_id": "opaque-value"},
        "runtime_headers": {"X-Session": "opaque-header"},
    }

    safe_definition = _target_definition_for_ai("test_case", definition)

    assert safe_definition["runtime_variables"] == {"session_id": REDACTED}
    assert safe_definition["runtime_headers"] == {"X-Session": REDACTED}
    assert definition["runtime_variables"] == {"session_id": "opaque-value"}
    assert definition["runtime_headers"] == {"X-Session": "opaque-header"}


def test_ai_test_case_update_restores_only_known_redacted_runtime_values() -> None:
    workflow_id = uuid4()
    environment_id = uuid4()
    current = {
        "workflow_id": str(workflow_id),
        "environment_id": str(environment_id),
        "runtime_variables": {"session_id": "opaque-value"},
        "runtime_headers": {"X-Session": "opaque-header"},
    }
    proposed = CaseDefinitionInput.model_validate(
        {
            **current,
            "runtime_variables": {"session_id": REDACTED},
            "runtime_headers": {"X-Session": REDACTED},
        }
    )

    restored = _rehydrate_test_case_definition(proposed, current)

    assert restored is not None
    assert restored.runtime_variables == {"session_id": "opaque-value"}
    assert restored.runtime_headers == {"X-Session": "opaque-header"}
    omitted = CaseDefinitionInput.model_validate(
        {"workflow_id": str(workflow_id), "environment_id": str(environment_id)}
    )
    restored_omitted = _rehydrate_test_case_definition(omitted, current)
    assert restored_omitted is not None
    assert restored_omitted.runtime_variables == {"session_id": "opaque-value"}
    assert restored_omitted.runtime_headers == {"X-Session": "opaque-header"}
    explicit_empty = CaseDefinitionInput.model_validate(
        {
            "workflow_id": str(workflow_id),
            "environment_id": str(environment_id),
            "runtime_variables": {},
            "runtime_headers": {},
        }
    )
    restored_empty = _rehydrate_test_case_definition(explicit_empty, current)
    assert restored_empty is not None
    assert restored_empty.runtime_variables == {}
    assert restored_empty.runtime_headers == {}
    unknown_placeholder = proposed.model_copy(update={"runtime_variables": {"new_value": REDACTED}})
    with pytest.raises(AppError) as invalid:
        _rehydrate_test_case_definition(unknown_placeholder, current)
    assert invalid.value.code == "AI_REDACTED_VALUE_INVALID"


def test_ai_workflow_update_preserves_omitted_runtime_fields_but_allows_explicit_empty() -> None:
    current = _workflow_definition()
    current["variables"] = {"session_id": "opaque-session"}
    current["nodes"][0]["config"] = {"headers": {"X-Session": "opaque-header"}}
    omitted_raw = deepcopy(current)
    omitted_raw.pop("variables")
    omitted_raw["nodes"][0].pop("config")
    omitted = WorkflowDefinition.model_validate(omitted_raw)

    restored = _rehydrate_workflow_definition(omitted, current)

    assert restored is not None
    assert restored.variables == {"session_id": "opaque-session"}
    assert restored.nodes[0].config == {"headers": {"X-Session": "opaque-header"}}
    explicit_empty_raw = deepcopy(omitted_raw)
    explicit_empty_raw["variables"] = {}
    explicit_empty_raw["nodes"][0]["config"] = {}
    explicit_empty = WorkflowDefinition.model_validate(explicit_empty_raw)
    restored_empty = _rehydrate_workflow_definition(explicit_empty, current)
    assert restored_empty is not None
    assert restored_empty.variables == {}
    assert restored_empty.nodes[0].config == {}


@pytest.mark.asyncio
async def test_regular_test_case_update_takes_same_row_lock_as_ai_acceptance() -> None:
    session = AsyncMock(spec=AsyncSession)
    project_id = uuid4()
    case_id = uuid4()
    actor = User(id=uuid4(), email="editor@example.com", display_name="Editor")
    model = CaseModel(
        id=case_id,
        project_id=project_id,
        name="并发更新用例",
        description="原描述",
        tags=[],
        is_template=False,
        draft_definition={},
        current_version=None,
        created_by_id=actor.id,
    )
    service = CaseService(session)
    service._projects.authorize = AsyncMock()
    service._assets.get_case_for_update = AsyncMock(return_value=model)

    updated = await service.update(
        actor=actor,
        project_id=project_id,
        case_id=case_id,
        name=None,
        description="人工更新",
        folder_id=None,
        change_folder=False,
        tags=None,
        is_template=None,
        definition=None,
    )

    service._assets.get_case_for_update.assert_awaited_once_with(case_id)
    assert updated.description == "人工更新"


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
async def test_ai_change_set_rejects_duplicate_update_targets(
    quality_context: QualityContext,
) -> None:
    headers = await _login(quality_context.client)
    project_id = await _project(quality_context.client, headers, "AI 重复更新项目")
    workflow_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "重复更新目标", "definition": _workflow_definition()},
    )
    assert workflow_response.status_code == 201, workflow_response.text
    workflow_id = workflow_response.json()["id"]
    impact_run_id = await _seed_impact(quality_context.sessions, project_id, target_id=workflow_id)
    risk_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/release-risks",
        headers=headers,
        json={"impact_run_id": impact_run_id, "title": "重复更新风险", "window_days": 7},
    )
    assert risk_response.status_code == 201, risk_response.text
    created = await quality_context.client.post(
        "/api/v1/ai/change-sets",
        headers=headers,
        json={
            "project_id": project_id,
            "impact_run_id": impact_run_id,
            "release_risk_id": risk_response.json()["id"],
            "title": "拒绝重复更新",
        },
    )
    assert created.status_code == 202, created.text

    async with quality_context.sessions() as session:
        job = await session.get(AIJob, quality_context.queue.job_ids[-1])
        assert job is not None
        failed = await AIJobRunner(session, DuplicateUpdateProvider(workflow_id)).run(job.id)
        assert failed.status == "failed"
        assert failed.error_code == "AI_RESPONSE_INVALID"
        change_set = await session.get(AIChangeSet, UUID(created.json()["id"]))
        assert change_set is not None
        assert change_set.status == "failed"
        assert (
            await session.scalar(
                select(AIChangeItem).where(AIChangeItem.change_set_id == change_set.id)
            )
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


@pytest.mark.asyncio
async def test_ai_change_set_preserves_target_snapshot_captured_before_generation(
    quality_context: QualityContext,
) -> None:
    headers = await _login(quality_context.client)
    project_id = await _project(quality_context.client, headers, "AI 生成期目标漂移项目")
    workflow_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={
            "name": "生成期人工维护流程",
            "description": "AI Provider 返回前发生变化",
            "definition": _workflow_definition(),
        },
    )
    assert workflow_response.status_code == 201, workflow_response.text
    workflow_id = workflow_response.json()["id"]
    impact_run_id = await _seed_impact(quality_context.sessions, project_id, target_id=workflow_id)
    risk_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/release-risks",
        headers=headers,
        json={"impact_run_id": impact_run_id, "title": "生成期漂移证据", "window_days": 7},
    )
    assert risk_response.status_code == 201, risk_response.text
    created = await quality_context.client.post(
        "/api/v1/ai/change-sets",
        headers=headers,
        json={
            "project_id": project_id,
            "impact_run_id": impact_run_id,
            "release_risk_id": risk_response.json()["id"],
            "title": "生成期漂移变更集",
        },
    )
    assert created.status_code == 202, created.text

    async with quality_context.sessions() as session:
        workflow = await session.get(Workflow, UUID(workflow_id))
        assert workflow is not None
        workflow.draft_revision += 1
        await session.commit()
        job = await session.get(AIJob, quality_context.queue.job_ids[-1])
        assert job is not None
        completed = await AIJobRunner(session, UpdateWorkflowProvider(workflow_id)).run(job.id)
        assert completed.status == "completed"
        item = await session.scalar(
            select(AIChangeItem).where(AIChangeItem.change_set_id == UUID(created.json()["id"]))
        )
        assert item is not None

    conflicted = await quality_context.client.post(
        f"/api/v1/ai/change-sets/{created.json()['id']}/items/{item.id}/accept",
        headers=headers,
        json={"note": "生成期间的人工修改不得被覆盖"},
    )
    assert conflicted.status_code == 409, conflicted.text
    assert conflicted.json()["error"]["code"] == "AI_CHANGE_TARGET_CONFLICT"


@pytest.mark.asyncio
async def test_ai_assertion_change_requires_complete_workflow_definition(
    quality_context: QualityContext,
) -> None:
    headers = await _login(quality_context.client)
    project_id = await _project(quality_context.client, headers, "AI 断言变更项目")
    workflow_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "断言目标流程", "definition": _workflow_definition()},
    )
    assert workflow_response.status_code == 201, workflow_response.text
    workflow_id = workflow_response.json()["id"]
    impact_run_id = await _seed_impact(quality_context.sessions, project_id, target_id=workflow_id)
    risk_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/release-risks",
        headers=headers,
        json={"impact_run_id": impact_run_id, "title": "断言风险证据", "window_days": 7},
    )
    assert risk_response.status_code == 201, risk_response.text
    change_set_id, item_id = await _generate_change_set(
        quality_context,
        headers=headers,
        project_id=project_id,
        impact_run_id=impact_run_id,
        risk_id=risk_response.json()["id"],
        provider=AssertionOnlyProvider(workflow_id),
    )

    rejected = await quality_context.client.post(
        f"/api/v1/ai/change-sets/{change_set_id}/items/{item_id}/accept",
        headers=headers,
        json={"note": "缺少完整 Workflow Definition"},
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "AI_ASSERTION_DRAFT_INVALID"
    async with quality_context.sessions() as session:
        workflow = await session.get(Workflow, UUID(workflow_id))
        item = await session.get(AIChangeItem, item_id)
        assert workflow is not None
        assert workflow.draft_revision == 1
        assert item is not None
        assert item.review_status == "pending"


@pytest.mark.asyncio
async def test_ai_workflow_update_restores_redacted_values_before_writing_draft(
    quality_context: QualityContext,
) -> None:
    headers = await _login(quality_context.client)
    project_id = await _project(quality_context.client, headers, "AI 脱敏值恢复项目")
    definition = _workflow_definition_with_assertion(start_name="开始", expected=200)
    definition["variables"] = {"session_id": "opaque-session-material"}
    definition["nodes"][0]["config"] = {
        "headers": {"X-Session": "opaque-node-secret"},
        "retries": [1, 2],
    }
    workflow_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "脱敏恢复流程", "definition": definition},
    )
    assert workflow_response.status_code == 201, workflow_response.text
    workflow_id = workflow_response.json()["id"]
    impact_run_id = await _seed_impact(quality_context.sessions, project_id, target_id=workflow_id)
    risk_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/release-risks",
        headers=headers,
        json={"impact_run_id": impact_run_id, "title": "脱敏恢复风险", "window_days": 7},
    )
    assert risk_response.status_code == 201, risk_response.text
    change_set_id, item_id = await _generate_change_set(
        quality_context,
        headers=headers,
        project_id=project_id,
        impact_run_id=impact_run_id,
        risk_id=risk_response.json()["id"],
        provider=RedactedAssertionUpdateProvider(workflow_id),
    )

    accepted = await quality_context.client.post(
        f"/api/v1/ai/change-sets/{change_set_id}/items/{item_id}/accept",
        headers=headers,
        json={"note": "确认断言变更并恢复脱敏字段"},
    )
    assert accepted.status_code == 200, accepted.text
    async with quality_context.sessions() as session:
        workflow = await session.get(Workflow, UUID(workflow_id))
        assert workflow is not None
        assert workflow.draft_definition["variables"] == {"session_id": "opaque-session-material"}
        nodes = cast(list[dict[str, JsonValue]], workflow.draft_definition["nodes"])
        start = next(node for node in nodes if node["id"] == "start")
        assertion = next(node for node in nodes if node["id"] == "assert-status")
        assert start["config"] == {
            "headers": {"X-Session": "opaque-node-secret"},
            "retries": [1, 2],
        }
        assert assertion["config"] == {
            "source_node_id": "start",
            "expression": "$.status_code",
            "operator": "equals",
            "expected": 201,
        }
        assert REDACTED not in str(workflow.draft_definition)


@pytest.mark.asyncio
async def test_quality_repository_uses_complete_terminal_failure_population() -> None:
    session = AsyncMock(spec=AsyncSession)
    empty_rows = MagicMock()
    empty_rows.tuples.return_value.all.return_value = []
    session.execute.return_value = empty_rows
    repository = QualityIntelligenceRepository(session)
    ended_at = datetime.now(UTC)
    started_at = ended_at - timedelta(days=7)

    terminal = await repository.terminal_execution_snapshot(
        project_id=uuid4(), started_at=started_at, ended_at=ended_at
    )

    assert terminal == ()
    terminal_statement = session.execute.await_args.args[0]
    terminal_query = str(terminal_statement)
    assert " LIMIT " not in terminal_query.upper()
    assert "workflow_executions.completed_at IS NOT NULL" in terminal_query
    assert "workflow_executions.completed_at <=" in terminal_query
    assert ["passed", "failed"] in terminal_statement.compile().params.values()

    observations = await repository.failure_observations(
        project_id=uuid4(),
        started_at=started_at,
        ended_at=ended_at,
        terminal_executions=terminal,
    )
    assert observations == ()
    assert session.execute.await_count == 1

    executions = (
        (WorkflowExecution(status="passed"), "成功流程"),
        (WorkflowExecution(status="failed"), "失败流程"),
    )
    assert _execution_counts(executions) == (2, 1)


@pytest.mark.asyncio
async def test_failure_node_selection_orders_by_execution_timestamps() -> None:
    session = AsyncMock(spec=AsyncSession)
    execution = WorkflowExecution(
        id=uuid4(),
        workflow_id=uuid4(),
        status="failed",
        error_code="EXECUTION_FAILED",
        started_at=datetime.now(UTC),
    )
    execution_rows = MagicMock()
    execution_rows.tuples.return_value.all.return_value = [(execution, "确定性失败流程")]
    evidence_rows = MagicMock()
    evidence_rows.all.return_value = []
    session.execute.side_effect = [execution_rows, evidence_rows]
    repository = QualityIntelligenceRepository(session)

    await repository.failure_observations(
        project_id=uuid4(),
        started_at=execution.started_at - timedelta(hours=1),
        ended_at=execution.started_at + timedelta(hours=1),
    )

    node_query = str(session.execute.await_args_list[1].args[0])
    order_clause = node_query.split("ORDER BY", maxsplit=1)[1]
    assert "workflow_executions.parent_execution_id IS NOT NULL" in order_clause
    assert "workflow_node_executions.started_at ASC NULLS LAST" in order_clause
    assert "workflow_node_executions.completed_at" in order_clause
    assert "workflow_node_executions.id" in order_clause


@pytest.mark.asyncio
async def test_failure_observation_counts_dataset_root_and_uses_child_node_evidence(
    quality_context: QualityContext,
) -> None:
    headers = await _login(quality_context.client)
    project_id = await _project(quality_context.client, headers, "Dataset 失败聚类项目")
    workflow_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "Dataset 根因流程", "definition": _workflow_definition()},
    )
    assert workflow_response.status_code == 201, workflow_response.text
    workflow_id = UUID(workflow_response.json()["id"])
    occurred_at = datetime.now(UTC)
    root_id = uuid4()
    child_id = uuid4()
    async with quality_context.sessions() as session:
        actor_id = await session.scalar(select(User.id).where(User.email == ADMIN_EMAIL))
        assert actor_id is not None
        common = {
            "project_id": UUID(project_id),
            "workflow_id": workflow_id,
            "workflow_version_id": uuid4(),
            "environment_id": uuid4(),
            "triggered_by_id": actor_id,
            "status": "failed",
            "snapshot": {},
            "context": {},
            "started_at": occurred_at,
            "completed_at": occurred_at,
        }
        session.add_all(
            [
                WorkflowExecution(
                    id=root_id,
                    parent_execution_id=None,
                    dataset_row_index=None,
                    error_code="DATASET_ROWS_FAILED",
                    **common,
                ),
                WorkflowExecution(
                    id=child_id,
                    parent_execution_id=root_id,
                    dataset_row_index=0,
                    error_code="WORKFLOW_NODE_FAILED",
                    **common,
                ),
                WorkflowNodeExecution(
                    workflow_execution_id=child_id,
                    node_id="assert-status",
                    node_type="assert",
                    name="校验状态码",
                    status="failed",
                    attempts=1,
                    output=None,
                    result=None,
                    error_code="ASSERTION_FAILED",
                    error_message="状态码不符合预期",
                    started_at=occurred_at,
                    completed_at=occurred_at,
                ),
            ]
        )
        await session.commit()
        observations = await QualityIntelligenceRepository(session).failure_observations(
            project_id=UUID(project_id),
            started_at=occurred_at - timedelta(minutes=1),
            ended_at=occurred_at + timedelta(minutes=1),
        )

    assert len(observations) == 1
    assert observations[0].execution_id == root_id
    assert observations[0].error_code == "ASSERTION_FAILED"
    assert observations[0].node_type == "assert"
    assert observations[0].category == "assertion"


@pytest.mark.asyncio
async def test_failure_observation_uses_earliest_dataset_child_before_node_detail(
    quality_context: QualityContext,
) -> None:
    headers = await _login(quality_context.client)
    project_id = await _project(quality_context.client, headers, "Dataset 首次失败项目")
    workflow_response = await quality_context.client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "Dataset 首次失败流程", "definition": _workflow_definition()},
    )
    assert workflow_response.status_code == 201, workflow_response.text
    workflow_id = UUID(workflow_response.json()["id"])
    occurred_at = datetime.now(UTC)
    root_id = uuid4()
    first_child_id = uuid4()
    later_child_id = uuid4()
    async with quality_context.sessions() as session:
        actor_id = await session.scalar(select(User.id).where(User.email == ADMIN_EMAIL))
        assert actor_id is not None

        def execution(
            *,
            execution_id: UUID,
            parent_execution_id: UUID | None,
            row_index: int | None,
            error_code: str,
            started_at: datetime,
        ) -> WorkflowExecution:
            return WorkflowExecution(
                id=execution_id,
                project_id=UUID(project_id),
                workflow_id=workflow_id,
                workflow_version_id=uuid4(),
                environment_id=uuid4(),
                triggered_by_id=actor_id,
                parent_execution_id=parent_execution_id,
                dataset_row_index=row_index,
                status="failed",
                snapshot={},
                context={},
                error_code=error_code,
                started_at=started_at,
                completed_at=started_at,
            )

        later_at = occurred_at + timedelta(seconds=1)
        session.add_all(
            [
                execution(
                    execution_id=root_id,
                    parent_execution_id=None,
                    row_index=None,
                    error_code="DATASET_ROWS_FAILED",
                    started_at=occurred_at,
                ),
                execution(
                    execution_id=first_child_id,
                    parent_execution_id=root_id,
                    row_index=0,
                    error_code="NETWORK_FAILED",
                    started_at=occurred_at,
                ),
                execution(
                    execution_id=later_child_id,
                    parent_execution_id=root_id,
                    row_index=1,
                    error_code="WORKFLOW_NODE_FAILED",
                    started_at=later_at,
                ),
                WorkflowNodeExecution(
                    workflow_execution_id=later_child_id,
                    node_id="assert-status",
                    node_type="assert",
                    name="校验状态码",
                    status="failed",
                    attempts=1,
                    output=None,
                    result=None,
                    error_code="ASSERTION_FAILED",
                    error_message="状态码不符合预期",
                    started_at=later_at,
                    completed_at=later_at,
                ),
            ]
        )
        await session.commit()
        observations = await QualityIntelligenceRepository(session).failure_observations(
            project_id=UUID(project_id),
            started_at=occurred_at - timedelta(minutes=1),
            ended_at=later_at + timedelta(minutes=1),
        )

    assert len(observations) == 1
    assert observations[0].execution_id == root_id
    assert observations[0].error_code == "NETWORK_FAILED"
    assert observations[0].node_type is None
    assert observations[0].category == "network"


@pytest.mark.asyncio
async def test_deployment_decisions_select_latest_record_per_service_without_limit() -> None:
    session = AsyncMock(spec=AsyncSession)
    decision_rows = MagicMock()
    decision_rows.all.return_value = ["safe", "unsafe"]
    session.scalars.return_value = decision_rows
    repository = QualityIntelligenceRepository(session)

    decisions = await repository.deployment_decisions(uuid4())

    assert decisions == ["safe", "unsafe"]
    query = str(session.scalars.await_args.args[0])
    normalized = query.upper()
    assert "ROW_NUMBER() OVER" in normalized
    assert "PARTITION BY DEPLOYMENT_COMPATIBILITY_CHECKS.PROVIDER_SERVICE_ID" in normalized
    assert "DECISION_RANK" in normalized
    assert " LIMIT " not in normalized


@pytest.mark.asyncio
async def test_flaky_asset_count_groups_historical_versions_by_target() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = 2
    repository = QualityIntelligenceRepository(session)

    count = await repository.flaky_asset_count(uuid4())

    assert count == 2
    query = str(session.scalar.await_args.args[0]).upper()
    assert "GROUP BY FLAKY_RECORDS.TARGET_TYPE, FLAKY_RECORDS.TARGET_ID" in query
    group_clause = query.split("GROUP BY", maxsplit=1)[1]
    assert "TARGET_VERSION" not in group_clause


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
    unsupported_asset_count: int = 0,
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
                    *[
                        {
                            "asset_type": "openapi_contract",
                            "target_type": "openapi_contract",
                            "target_id": f"!contract-{index:03d}",
                            "name": f"契约 {index}",
                            "version": 1,
                            "risk": "high",
                            "change_keys": ["change-1"],
                            "reasons": ["契约关联"],
                        }
                        for index in range(unsupported_asset_count)
                    ],
                    {
                        "asset_type": "workflow",
                        "target_type": "workflow",
                        "target_id": target_id,
                        "name": "开票流程",
                        "version": 1,
                        "risk": "high",
                        "change_keys": ["change-1"],
                        "reasons": ["显式 Mapping"],
                    },
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


def _workflow_definition_with_assertion(*, start_name: str, expected: int) -> dict[str, JsonValue]:
    return {
        "schema_version": "1.0",
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "name": start_name,
                "position": {"x": 0, "y": 0},
                "config": {},
            },
            {
                "id": "assert-status",
                "type": "assert",
                "name": "状态码断言",
                "position": {"x": 160, "y": 0},
                "config": {
                    "source_node_id": "start",
                    "expression": "$.status_code",
                    "operator": "equals",
                    "expected": expected,
                },
            },
            {
                "id": "end",
                "type": "end",
                "name": "结束",
                "position": {"x": 320, "y": 0},
                "config": {},
            },
        ],
        "edges": [
            {"id": "start-assert", "source": "start", "target": "assert-status"},
            {"id": "assert-end", "source": "assert-status", "target": "end"},
        ],
    }
