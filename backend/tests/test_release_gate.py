from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.domain.release_gate import (
    ReleaseEvidenceFacts,
    ReleasePolicyRules,
    evaluate_release,
)
from app.main import app
from app.models import Base
from app.models.access import User
from app.models.contracts import DeploymentCompatibilityCheck, ServiceCatalogEntry
from app.models.impact import CoverageSnapshot, ImpactRun
from app.models.performance import PerformanceGateEvaluation, PerformanceRun, PerformanceScenario
from app.models.quality import QualityGate, QualityGateEvaluation
from app.models.quality_intelligence import ReleaseRisk
from app.models.release_gate import ReleaseDecision
from app.models.tasking import TestPlan as PlanModel
from app.models.tasking import TestPlanRun as PlanRunModel

ADMIN_EMAIL = "release-gate@example.com"
ADMIN_PASSWORD = "release-gate-password-123!"


@dataclass(frozen=True, slots=True)
class ReleaseGateContext:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class EvidenceIds:
    quality_gate_id: UUID
    test_plan_run_id: UUID
    deployment_check_id: UUID
    impact_run_id: UUID
    release_risk_id: UUID
    performance_run_id: UUID


@pytest.fixture
async def release_gate_context() -> AsyncIterator[ReleaseGateContext]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="Release administrator",
                password_hash=password_service.hash(ADMIN_PASSWORD),
                is_active=True,
                is_system_admin=True,
                requires_password_change=False,
            )
        )
        await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield ReleaseGateContext(client=client, sessions=sessions)
    app.dependency_overrides.clear()
    await engine.dispose()


def test_release_evaluation_explains_all_evidence_families() -> None:
    rules = _rules(require_runner_evidence=True)
    passed = evaluate_release(
        rules,
        ReleaseEvidenceFacts(
            quality_gate_status="passed",
            contract_decision="safe",
            impact_status="completed",
            impact_coverage_percent=95,
            release_risk_score=20,
            performance_status="passed",
            performance_gate_statuses=("passed",),
            runner_task_status="completed",
            runner_fencing_token=2,
            runner_completed_lease_count=1,
        ),
    )
    assert passed.status == "pass"
    assert len(passed.reasons) == 6
    assert {reason.status for reason in passed.reasons} == {"passed"}

    blocked = evaluate_release(
        rules,
        ReleaseEvidenceFacts(
            quality_gate_status="failed",
            contract_decision="unknown",
            impact_status="completed",
            impact_coverage_percent=50,
            release_risk_score=80,
            performance_status="failed",
            runner_task_status="completed",
            runner_fencing_token=2,
            runner_completed_lease_count=2,
        ),
    )
    assert blocked.status == "block"
    assert {reason.code for reason in blocked.reasons if reason.status == "blocked"} == {
        "QUALITY_GATE_BLOCKED",
        "CONTRACT_INCOMPATIBLE",
        "IMPACT_COVERAGE_BLOCKED",
        "RELEASE_RISK_TOO_HIGH",
        "PERFORMANCE_BLOCKED",
        "RUNNER_EVIDENCE_BLOCKED",
    }


@pytest.mark.asyncio
async def test_release_decision_persists_immutable_explainable_snapshot(
    release_gate_context: ReleaseGateContext,
) -> None:
    headers = await _login(release_gate_context.client)
    project_id = await _project(release_gate_context.client, headers, "发布门禁项目")
    evidence = await _seed_evidence(release_gate_context.sessions, project_id)
    policy = await _create_policy(
        release_gate_context.client,
        headers,
        project_id,
        quality_gate_id=evidence.quality_gate_id,
        require_performance_evidence=True,
    )
    created = await release_gate_context.client.post(
        f"/api/v1/projects/{project_id}/release-decisions",
        headers=headers,
        json={
            "release_policy_id": policy["id"],
            "candidate_ref": "v3.0.0-rc.1",
            "test_plan_run_id": str(evidence.test_plan_run_id),
            "deployment_check_id": str(evidence.deployment_check_id),
            "impact_run_id": str(evidence.impact_run_id),
            "release_risk_id": str(evidence.release_risk_id),
            "performance_run_id": str(evidence.performance_run_id),
        },
    )
    assert created.status_code == 201, created.text
    decision = created.json()
    assert decision["status"] == "pass"
    assert len(decision["fingerprint"]) == 64
    assert {reason["evidence_type"] for reason in decision["reasons"]} == {
        "quality_gate",
        "contract_compatibility",
        "impact",
        "release_risk",
        "performance",
        "runner",
    }
    assert {reason["status"] for reason in decision["reasons"]} == {"passed"}
    assert decision["policy_snapshot"]["max_release_risk_score"] == 50
    assert decision["evidence_snapshot"]["contract_compatibility"]["decision"] == "safe"
    assert decision["evidence_snapshot"]["impact"]["coverage_percent"] == 90

    updated_policy = {**_policy_payload(str(evidence.quality_gate_id)), "max_release_risk_score": 5}
    updated = await release_gate_context.client.put(
        f"/api/v1/projects/{project_id}/release-policies/{policy['id']}",
        headers=headers,
        json=updated_policy,
    )
    assert updated.status_code == 200, updated.text
    fetched = await release_gate_context.client.get(
        f"/api/v1/projects/{project_id}/release-decisions/{decision['id']}", headers=headers
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["policy_snapshot"]["max_release_risk_score"] == 50
    assert fetched.json()["fingerprint"] == decision["fingerprint"]
    unsupported_update = await release_gate_context.client.put(
        f"/api/v1/projects/{project_id}/release-decisions/{decision['id']}",
        headers=headers,
        json={"candidate_ref": "tampered"},
    )
    assert unsupported_update.status_code == 405

    async with release_gate_context.sessions() as session:
        stored = await session.get(ReleaseDecision, UUID(decision["id"]))
        assert stored is not None
        stored.candidate_ref = "tampered"
        with pytest.raises(ValueError, match="immutable"):
            await session.flush()
        await session.rollback()
        stored = await session.get(ReleaseDecision, UUID(decision["id"]))
        assert stored is not None
        await session.delete(stored)
        with pytest.raises(ValueError, match="immutable"):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_release_decision_records_block_when_required_evidence_is_missing(
    release_gate_context: ReleaseGateContext,
) -> None:
    headers = await _login(release_gate_context.client)
    project_id = await _project(release_gate_context.client, headers, "缺失证据项目")
    evidence = await _seed_evidence(release_gate_context.sessions, project_id)
    policy = await _create_policy(
        release_gate_context.client,
        headers,
        project_id,
        quality_gate_id=evidence.quality_gate_id,
        require_performance_evidence=True,
    )
    response = await release_gate_context.client.post(
        f"/api/v1/projects/{project_id}/release-decisions",
        headers=headers,
        json={"release_policy_id": policy["id"], "candidate_ref": "v3.0.0-rc.2"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "block"
    assert {reason["code"] for reason in body["reasons"] if reason["status"] == "blocked"} == {
        "QUALITY_GATE_EVIDENCE_MISSING",
        "CONTRACT_EVIDENCE_MISSING",
        "IMPACT_EVIDENCE_MISSING",
        "RELEASE_RISK_EVIDENCE_MISSING",
        "PERFORMANCE_EVIDENCE_MISSING",
    }
    listed = await release_gate_context.client.get(
        f"/api/v1/projects/{project_id}/release-decisions", headers=headers
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


@pytest.mark.asyncio
async def test_release_gate_rejects_invalid_policy_and_evidence_references(
    release_gate_context: ReleaseGateContext,
) -> None:
    headers = await _login(release_gate_context.client)
    project_id = await _project(release_gate_context.client, headers, "引用边界项目")
    evidence = await _seed_evidence(release_gate_context.sessions, project_id)
    policy = await _create_policy(
        release_gate_context.client,
        headers,
        project_id,
        quality_gate_id=evidence.quality_gate_id,
        require_performance_evidence=True,
    )
    base = {"release_policy_id": policy["id"], "candidate_ref": "v3.0.0-invalid"}
    invalid_fields = {
        "test_plan_run_id": "QUALITY_EVIDENCE_NOT_FOUND",
        "deployment_check_id": "CONTRACT_EVIDENCE_NOT_FOUND",
        "impact_run_id": "IMPACT_EVIDENCE_NOT_FOUND",
        "release_risk_id": "RELEASE_RISK_EVIDENCE_NOT_FOUND",
        "performance_run_id": "PERFORMANCE_EVIDENCE_NOT_FOUND",
        "runner_task_id": "RUNNER_EVIDENCE_NOT_FOUND",
    }
    for field, code in invalid_fields.items():
        response = await release_gate_context.client.post(
            f"/api/v1/projects/{project_id}/release-decisions",
            headers=headers,
            json={**base, field: str(uuid4())},
        )
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == code

    unknown_policy = await release_gate_context.client.post(
        f"/api/v1/projects/{project_id}/release-decisions",
        headers=headers,
        json={"release_policy_id": str(uuid4()), "candidate_ref": "unknown"},
    )
    unknown_decision = await release_gate_context.client.get(
        f"/api/v1/projects/{project_id}/release-decisions/{uuid4()}", headers=headers
    )
    assert unknown_policy.status_code == 404
    assert unknown_policy.json()["error"]["code"] == "RELEASE_POLICY_NOT_FOUND"
    assert unknown_decision.status_code == 404
    assert unknown_decision.json()["error"]["code"] == "RELEASE_DECISION_NOT_FOUND"


@pytest.mark.asyncio
async def test_release_policy_validation_disable_and_evidence_pairing(
    release_gate_context: ReleaseGateContext,
) -> None:
    headers = await _login(release_gate_context.client)
    project_id = await _project(release_gate_context.client, headers, "策略边界项目")
    evidence = await _seed_evidence(release_gate_context.sessions, project_id)
    policy = await _create_policy(
        release_gate_context.client,
        headers,
        project_id,
        quality_gate_id=evidence.quality_gate_id,
        require_performance_evidence=False,
    )
    listed = await release_gate_context.client.get(
        f"/api/v1/projects/{project_id}/release-policies", headers=headers
    )
    duplicate = await release_gate_context.client.post(
        f"/api/v1/projects/{project_id}/release-policies",
        headers=headers,
        json=_policy_payload(str(evidence.quality_gate_id)),
    )
    bad_gate = await release_gate_context.client.post(
        f"/api/v1/projects/{project_id}/release-policies",
        headers=headers,
        json={**_policy_payload(str(uuid4())), "name": "Unknown gate"},
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [policy["id"]]
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "RELEASE_POLICY_NAME_EXISTS"
    assert bad_gate.status_code == 404
    assert bad_gate.json()["error"]["code"] == "QUALITY_GATE_NOT_FOUND"

    other_impact_id = await _seed_other_impact(release_gate_context.sessions, project_id)
    mismatch = await release_gate_context.client.post(
        f"/api/v1/projects/{project_id}/release-decisions",
        headers=headers,
        json={
            "release_policy_id": policy["id"],
            "candidate_ref": "mismatch",
            "impact_run_id": str(other_impact_id),
            "release_risk_id": str(evidence.release_risk_id),
        },
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "RELEASE_EVIDENCE_MISMATCH"

    disabled_payload = _policy_payload(str(evidence.quality_gate_id))
    disabled_payload["enabled"] = False
    updated = await release_gate_context.client.put(
        f"/api/v1/projects/{project_id}/release-policies/{policy['id']}",
        headers=headers,
        json=disabled_payload,
    )
    disabled = await release_gate_context.client.post(
        f"/api/v1/projects/{project_id}/release-decisions",
        headers=headers,
        json={"release_policy_id": policy["id"], "candidate_ref": "disabled"},
    )
    assert updated.status_code == 200
    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "RELEASE_POLICY_DISABLED"


@pytest.mark.asyncio
async def test_release_gate_rejects_blank_policy_names_and_candidate_refs(
    release_gate_context: ReleaseGateContext,
) -> None:
    headers = await _login(release_gate_context.client)
    project_id = await _project(release_gate_context.client, headers, "空白输入项目")

    blank_policy = await release_gate_context.client.post(
        f"/api/v1/projects/{project_id}/release-policies",
        headers=headers,
        json={**_policy_payload(None), "name": "   ", "require_quality_gate": False},
    )
    assert blank_policy.status_code == 422

    policy = await release_gate_context.client.post(
        f"/api/v1/projects/{project_id}/release-policies",
        headers=headers,
        json={**_policy_payload(None), "name": "  规范化策略  ", "require_quality_gate": False},
    )
    assert policy.status_code == 201, policy.text
    assert policy.json()["name"] == "规范化策略"

    blank_candidate = await release_gate_context.client.post(
        f"/api/v1/projects/{project_id}/release-decisions",
        headers=headers,
        json={"release_policy_id": policy.json()["id"], "candidate_ref": "   "},
    )
    assert blank_candidate.status_code == 422

    normalized_candidate = await release_gate_context.client.post(
        f"/api/v1/projects/{project_id}/release-decisions",
        headers=headers,
        json={"release_policy_id": policy.json()["id"], "candidate_ref": "  rc.1  "},
    )
    assert normalized_candidate.status_code == 201, normalized_candidate.text
    assert normalized_candidate.json()["candidate_ref"] == "rc.1"


@pytest.mark.asyncio
async def test_release_gate_rejects_cross_project_evidence(
    release_gate_context: ReleaseGateContext,
) -> None:
    headers = await _login(release_gate_context.client)
    project_id = await _project(release_gate_context.client, headers, "发布项目")
    policy_evidence = await _seed_evidence(release_gate_context.sessions, project_id)
    policy = await _create_policy(
        release_gate_context.client,
        headers,
        project_id,
        quality_gate_id=policy_evidence.quality_gate_id,
        require_performance_evidence=True,
    )
    other_project_id = await _project(release_gate_context.client, headers, "其他项目")
    other = await _seed_evidence(release_gate_context.sessions, other_project_id)
    cross_project_fields = {
        "test_plan_run_id": (other.test_plan_run_id, "QUALITY_EVIDENCE_NOT_FOUND"),
        "deployment_check_id": (other.deployment_check_id, "CONTRACT_EVIDENCE_NOT_FOUND"),
        "impact_run_id": (other.impact_run_id, "IMPACT_EVIDENCE_NOT_FOUND"),
        "release_risk_id": (other.release_risk_id, "RELEASE_RISK_EVIDENCE_NOT_FOUND"),
        "performance_run_id": (other.performance_run_id, "PERFORMANCE_EVIDENCE_NOT_FOUND"),
    }
    for field, (evidence_id, code) in cross_project_fields.items():
        response = await release_gate_context.client.post(
            f"/api/v1/projects/{project_id}/release-decisions",
            headers=headers,
            json={
                "release_policy_id": policy["id"],
                "candidate_ref": f"cross-project-{field}",
                field: str(evidence_id),
            },
        )
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == code


async def _login(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _project(client: AsyncClient, headers: dict[str, str], name: str) -> str:
    response = await client.post(
        "/api/v1/projects", headers=headers, json={"name": name, "description": "S31"}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _create_policy(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    *,
    quality_gate_id: UUID,
    require_performance_evidence: bool,
) -> dict[str, object]:
    payload = _policy_payload(str(quality_gate_id))
    payload["require_performance_evidence"] = require_performance_evidence
    response = await client.post(
        f"/api/v1/projects/{project_id}/release-policies", headers=headers, json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def _policy_payload(quality_gate_id: str | None) -> dict[str, object]:
    return {
        "name": "V3 GA 发布策略",
        "enabled": True,
        "quality_gate_id": quality_gate_id,
        "require_quality_gate": True,
        "require_contract_compatibility": True,
        "require_impact_evidence": True,
        "min_impact_coverage_percent": 80,
        "require_release_risk": True,
        "max_release_risk_score": 50,
        "require_performance_evidence": True,
        "require_runner_evidence": False,
    }


async def _seed_evidence(
    sessions: async_sessionmaker[AsyncSession], project_id: str
) -> EvidenceIds:
    now = datetime.now(UTC)
    project_uuid = UUID(project_id)
    async with sessions() as session:
        actor_id = await session.scalar(select(User.id).where(User.email == ADMIN_EMAIL))
        assert actor_id is not None
        gate = QualityGate(
            project_id=project_uuid,
            name="GA Quality Gate",
            enabled=True,
            min_pass_rate=100,
            max_failed=0,
            max_flaky=0,
            max_duration_regression_percent=20,
            require_no_breaking_changes=True,
            created_by_id=actor_id,
        )
        plan = PlanModel(
            project_id=project_uuid,
            name="GA Test Plan",
            description="",
            enabled=True,
            schedule_interval_seconds=None,
            schedule_cron=None,
            schedule_timezone="Asia/Shanghai",
            queue_priority=5,
            next_run_at=None,
            webhook_secret_ciphertext=b"ciphertext",
            webhook_secret_nonce=b"nonce",
            created_by_id=actor_id,
        )
        session.add_all([gate, plan])
        await session.flush()
        plan_run = PlanRunModel(
            project_id=project_uuid,
            test_plan_id=plan.id,
            requested_by_id=actor_id,
            status="passed",
            trigger_type="ci",
            queue_priority=5,
            queue_name="general",
            quality_summary={"pass_rate": 100, "failed": 0},
            started_at=now - timedelta(minutes=5),
            completed_at=now,
        )
        service = ServiceCatalogEntry(
            project_id=project_uuid,
            service_key="billing",
            display_name="Billing",
            description="",
            created_by_id=actor_id,
        )
        impact = ImpactRun(
            project_id=project_uuid,
            title="RC impact",
            source_ref="v3.0.0-rc.1",
            status="completed",
            source_fingerprint="a" * 64,
            source_summary={"git": {"file_count": 10}},
            change_count=10,
            changes=[],
            graph={"nodes": [], "edges": []},
            summary={"coverage_percent": 90},
            created_by_id=actor_id,
        )
        scenario = PerformanceScenario(
            project_id=project_uuid,
            name="GA Performance",
            description="",
            version=1,
            status="published",
            target_type="rest",
            definition={"vus": 1, "duration_seconds": 1},
            compiled_sha256="b" * 64,
            published_at=now,
            created_by_id=actor_id,
        )
        session.add_all([plan_run, service, impact, scenario])
        await session.flush()
        quality_evaluation = QualityGateEvaluation(
            project_id=project_uuid,
            quality_gate_id=gate.id,
            test_plan_run_id=plan_run.id,
            status="passed",
            metrics={"pass_rate": 100},
            violations=[],
            evaluated_at=now,
        )
        deployment = DeploymentCompatibilityCheck(
            project_id=project_uuid,
            provider_service_id=service.id,
            provider_version="3.0.0-rc.1",
            decision="safe",
            evidence={"blockers": [], "pending": [], "evaluated_contract_count": 2},
            checked_by_id=actor_id,
        )
        coverage = CoverageSnapshot(
            project_id=project_uuid,
            impact_run_id=impact.id,
            total_changes=10,
            covered_changes=9,
            coverage_percent=90,
            matrix=[],
            gaps=[{"change_key": "docs/readme.md"}],
            created_by_id=actor_id,
        )
        risk = ReleaseRisk(
            project_id=project_uuid,
            impact_run_id=impact.id,
            title="RC risk",
            algorithm_version="release_risk_v1",
            window_days=14,
            window_started_at=now - timedelta(days=14),
            window_ended_at=now,
            baseline_started_at=now - timedelta(days=28),
            baseline_ended_at=now - timedelta(days=14),
            score=20,
            quality_score=80,
            risk_level="low",
            factors=[],
            evidence_snapshot={"quality": {"pass_rate": 100}},
            quality_trend=[],
            recommended_tests=[],
            fingerprint="c" * 64,
            created_by_id=actor_id,
        )
        performance_run = PerformanceRun(
            project_id=project_uuid,
            scenario_id=scenario.id,
            scenario_version=1,
            status="passed",
            definition_snapshot=scenario.definition,
            compiled_sha256=scenario.compiled_sha256,
            summary={"http_req_duration_p95_ms": 100},
            threshold_results=[{"metric": "p95", "status": "passed"}],
            started_at=now - timedelta(minutes=2),
            completed_at=now,
            created_by_id=actor_id,
        )
        session.add_all([quality_evaluation, deployment, coverage, risk, performance_run])
        await session.flush()
        session.add(
            PerformanceGateEvaluation(
                project_id=project_uuid,
                quality_gate_id=gate.id,
                performance_run_id=performance_run.id,
                status="passed",
                metrics={"p95_ms": 100},
                violations=[],
                evaluated_at=now,
            )
        )
        await session.commit()
        return EvidenceIds(
            quality_gate_id=gate.id,
            test_plan_run_id=plan_run.id,
            deployment_check_id=deployment.id,
            impact_run_id=impact.id,
            release_risk_id=risk.id,
            performance_run_id=performance_run.id,
        )


async def _seed_other_impact(sessions: async_sessionmaker[AsyncSession], project_id: str) -> UUID:
    async with sessions() as session:
        actor_id = await session.scalar(select(User.id).where(User.email == ADMIN_EMAIL))
        assert actor_id is not None
        impact = ImpactRun(
            project_id=UUID(project_id),
            title="Other RC impact",
            source_ref="v3.0.0-rc.other",
            status="completed",
            source_fingerprint="d" * 64,
            source_summary={"git": {"file_count": 1}},
            change_count=1,
            changes=[],
            graph={"nodes": [], "edges": []},
            summary={"coverage_percent": 100},
            created_by_id=actor_id,
        )
        session.add(impact)
        await session.commit()
        return impact.id


def _rules(*, require_runner_evidence: bool) -> ReleasePolicyRules:
    return ReleasePolicyRules(
        require_quality_gate=True,
        require_contract_compatibility=True,
        require_impact_evidence=True,
        min_impact_coverage_percent=80,
        require_release_risk=True,
        max_release_risk_score=50,
        require_performance_evidence=True,
        require_runner_evidence=require_runner_evidence,
    )
