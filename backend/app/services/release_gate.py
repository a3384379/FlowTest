from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import NoReturn, cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.release_gate import (
    ReleaseEvidenceFacts,
    ReleasePolicyRules,
    evaluate_release,
)
from app.models.access import User
from app.models.release_gate import ReleaseDecision, ReleasePolicy
from app.repositories.release_gate import (
    ImpactEvidenceBundle,
    PerformanceEvidenceBundle,
    QualityEvidenceBundle,
    ReleaseGateRepository,
    RunnerEvidenceBundle,
)
from app.schemas.release_gate import ReleaseDecisionCreate, ReleasePolicyWrite
from app.services.audit import AuditService
from app.services.projects import ProjectService

SNAPSHOT_VERSION = "release_decision_v1"


class ReleaseGateService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = ReleaseGateRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def create_policy(
        self, *, actor: User, project_id: UUID, payload: ReleasePolicyWrite
    ) -> ReleasePolicy:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        normalized_name = payload.name.strip()
        await self._validate_policy(
            project_id=project_id,
            payload=payload,
            normalized_name=normalized_name,
            excluding_id=None,
        )
        policy = ReleasePolicy(
            project_id=project_id,
            created_by_id=actor.id,
            **payload.model_dump(exclude={"name"}),
            name=normalized_name,
        )
        self._repository.add(policy)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="release_policy.created",
            resource_type="release_policy",
            resource_id=policy.id,
        )
        await self._session.commit()
        await self._session.refresh(policy)
        return policy

    async def update_policy(
        self,
        *,
        actor: User,
        project_id: UUID,
        policy_id: UUID,
        payload: ReleasePolicyWrite,
    ) -> ReleasePolicy:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        policy = await self._project_policy(project_id, policy_id)
        normalized_name = payload.name.strip()
        await self._validate_policy(
            project_id=project_id,
            payload=payload,
            normalized_name=normalized_name,
            excluding_id=policy.id,
        )
        for field, value in payload.model_dump(exclude={"name"}).items():
            setattr(policy, field, value)
        policy.name = normalized_name
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="release_policy.updated",
            resource_type="release_policy",
            resource_id=policy.id,
        )
        await self._session.commit()
        await self._session.refresh(policy)
        return policy

    async def list_policies(self, *, actor: User, project_id: UUID) -> list[ReleasePolicy]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_policies(project_id)

    async def create_decision(
        self, *, actor: User, project_id: UUID, payload: ReleaseDecisionCreate
    ) -> ReleaseDecision:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        policy = await self._project_policy(project_id, payload.release_policy_id)
        if not policy.enabled:
            raise AppError(
                code="RELEASE_POLICY_DISABLED", message="发布策略已停用", status_code=409
            )
        policy_snapshot = _policy_snapshot(policy)
        evidence_snapshot, facts = await self._evidence_snapshot(
            project_id=project_id, policy=policy, payload=payload
        )
        evaluation = evaluate_release(_policy_rules(policy), facts)
        reasons = [cast(dict[str, JsonValue], asdict(reason)) for reason in evaluation.reasons]
        fingerprint = _fingerprint(
            candidate_ref=payload.candidate_ref.strip(),
            policy_snapshot=policy_snapshot,
            evidence_snapshot=evidence_snapshot,
            reasons=reasons,
        )
        decision = ReleaseDecision(
            project_id=project_id,
            release_policy_id=policy.id,
            candidate_ref=payload.candidate_ref.strip(),
            status=evaluation.status,
            policy_snapshot=policy_snapshot,
            evidence_snapshot=evidence_snapshot,
            reasons=reasons,
            fingerprint=fingerprint,
            test_plan_run_id=payload.test_plan_run_id,
            deployment_check_id=payload.deployment_check_id,
            impact_run_id=payload.impact_run_id,
            release_risk_id=payload.release_risk_id,
            performance_run_id=payload.performance_run_id,
            runner_task_id=payload.runner_task_id,
            created_by_id=actor.id,
        )
        self._repository.add(decision)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="release_decision.created",
            resource_type="release_decision",
            resource_id=decision.id,
            details={
                "candidate_ref": decision.candidate_ref,
                "status": decision.status,
                "fingerprint": decision.fingerprint,
                "blocker_codes": [
                    reason["code"] for reason in reasons if reason["status"] == "blocked"
                ],
            },
        )
        await self._session.commit()
        await self._session.refresh(decision)
        return decision

    async def list_decisions(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[ReleaseDecision], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_decisions(
            project_id=project_id, offset=(page - 1) * page_size, limit=page_size
        )

    async def get_decision(
        self, *, actor: User, project_id: UUID, decision_id: UUID
    ) -> ReleaseDecision:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        decision = await self._repository.get_decision(decision_id)
        if decision is None or decision.project_id != project_id:
            raise AppError(
                code="RELEASE_DECISION_NOT_FOUND", message="发布判断不存在", status_code=404
            )
        return decision

    async def _validate_policy(
        self,
        *,
        project_id: UUID,
        payload: ReleasePolicyWrite,
        normalized_name: str,
        excluding_id: UUID | None,
    ) -> None:
        if await self._repository.policy_name_exists(
            project_id=project_id, name=normalized_name, excluding_id=excluding_id
        ):
            raise AppError(
                code="RELEASE_POLICY_NAME_EXISTS",
                message="项目中已存在同名发布策略",
                status_code=409,
            )
        if payload.quality_gate_id is None:
            return
        gate = await self._repository.get_quality_gate(payload.quality_gate_id)
        if gate is None or gate.project_id != project_id:
            raise AppError(code="QUALITY_GATE_NOT_FOUND", message="质量门禁不存在", status_code=404)

    async def _project_policy(self, project_id: UUID, policy_id: UUID) -> ReleasePolicy:
        policy = await self._repository.get_policy(policy_id)
        if policy is None or policy.project_id != project_id:
            raise AppError(
                code="RELEASE_POLICY_NOT_FOUND", message="发布策略不存在", status_code=404
            )
        return policy

    async def _evidence_snapshot(
        self, *, project_id: UUID, policy: ReleasePolicy, payload: ReleaseDecisionCreate
    ) -> tuple[dict[str, JsonValue], ReleaseEvidenceFacts]:
        quality = await self._quality_evidence(project_id, policy, payload.test_plan_run_id)
        contract = await self._contract_evidence(project_id, payload.deployment_check_id)
        impact = await self._impact_evidence(project_id, payload.impact_run_id)
        risk = await self._risk_evidence(project_id, payload.release_risk_id)
        performance = await self._performance_evidence(project_id, payload.performance_run_id)
        runner = await self._runner_evidence(project_id, payload.runner_task_id)
        if impact is not None and risk is not None and risk["impact_run_id"] != impact["run_id"]:
            raise AppError(
                code="RELEASE_EVIDENCE_MISMATCH",
                message="Release Risk 与 Impact Run 不匹配",
                status_code=409,
            )
        snapshot: dict[str, JsonValue] = {
            "snapshot_version": SNAPSHOT_VERSION,
            "quality_gate": cast(JsonValue, quality),
            "contract_compatibility": cast(JsonValue, contract),
            "impact": cast(JsonValue, impact),
            "release_risk": cast(JsonValue, risk),
            "performance": cast(JsonValue, performance),
            "runner": cast(JsonValue, runner),
        }
        facts = ReleaseEvidenceFacts(
            quality_gate_status=(str(quality["status"]) if quality else None),
            contract_decision=(str(contract["decision"]) if contract else None),
            impact_status=(str(impact["status"]) if impact else None),
            impact_coverage_percent=(
                float(cast(str | int | float, impact["coverage_percent"]))
                if impact and impact["coverage_percent"] is not None
                else None
            ),
            release_risk_score=(float(cast(str | int | float, risk["score"])) if risk else None),
            performance_status=(str(performance["status"]) if performance else None),
            performance_gate_statuses=(
                tuple(str(item) for item in cast(list[JsonValue], performance["gate_statuses"]))
                if performance
                else ()
            ),
            runner_task_status=(str(runner["status"]) if runner else None),
            runner_fencing_token=(
                int(cast(str | int, runner["fencing_token"])) if runner else None
            ),
            runner_completed_lease_count=(
                int(cast(str | int, runner["completed_lease_count"])) if runner else 0
            ),
        )
        return snapshot, facts

    async def _quality_evidence(
        self, project_id: UUID, policy: ReleasePolicy, run_id: UUID | None
    ) -> dict[str, JsonValue] | None:
        if run_id is None or policy.quality_gate_id is None:
            return None
        bundle = await self._repository.quality_evidence(
            run_id=run_id, gate_id=policy.quality_gate_id
        )
        if bundle is None or bundle.run.project_id != project_id:
            _evidence_not_found("QUALITY_EVIDENCE_NOT_FOUND", "质量门禁证据不存在")
        return _quality_snapshot(bundle, policy.quality_gate_id)

    async def _contract_evidence(
        self, project_id: UUID, check_id: UUID | None
    ) -> dict[str, JsonValue] | None:
        if check_id is None:
            return None
        check = await self._repository.deployment_check(check_id)
        if check is None or check.project_id != project_id:
            _evidence_not_found("CONTRACT_EVIDENCE_NOT_FOUND", "契约兼容证据不存在")
        return {
            "check_id": str(check.id),
            "provider_service_id": str(check.provider_service_id),
            "provider_version": check.provider_version,
            "decision": check.decision,
            "evidence": cast(JsonValue, check.evidence),
            "checked_at": check.created_at.isoformat(),
        }

    async def _impact_evidence(
        self, project_id: UUID, run_id: UUID | None
    ) -> dict[str, JsonValue] | None:
        if run_id is None:
            return None
        bundle = await self._repository.impact_evidence(run_id)
        if bundle is None or bundle.run.project_id != project_id:
            _evidence_not_found("IMPACT_EVIDENCE_NOT_FOUND", "影响分析证据不存在")
        return _impact_snapshot(bundle)

    async def _risk_evidence(
        self, project_id: UUID, risk_id: UUID | None
    ) -> dict[str, JsonValue] | None:
        if risk_id is None:
            return None
        risk = await self._repository.release_risk(risk_id)
        if risk is None or risk.project_id != project_id:
            _evidence_not_found("RELEASE_RISK_EVIDENCE_NOT_FOUND", "发布风险证据不存在")
        return {
            "risk_id": str(risk.id),
            "impact_run_id": str(risk.impact_run_id),
            "algorithm_version": risk.algorithm_version,
            "score": risk.score,
            "quality_score": risk.quality_score,
            "risk_level": risk.risk_level,
            "factors": cast(JsonValue, risk.factors),
            "evidence": cast(JsonValue, risk.evidence_snapshot),
            "fingerprint": risk.fingerprint,
            "created_at": risk.created_at.isoformat(),
        }

    async def _performance_evidence(
        self, project_id: UUID, run_id: UUID | None
    ) -> dict[str, JsonValue] | None:
        if run_id is None:
            return None
        bundle = await self._repository.performance_evidence(run_id)
        if bundle is None or bundle.run.project_id != project_id:
            _evidence_not_found("PERFORMANCE_EVIDENCE_NOT_FOUND", "性能证据不存在")
        return _performance_snapshot(bundle)

    async def _runner_evidence(
        self, project_id: UUID, task_id: UUID | None
    ) -> dict[str, JsonValue] | None:
        if task_id is None:
            return None
        bundle = await self._repository.runner_evidence(task_id)
        if bundle is None or bundle.task.project_id != project_id:
            _evidence_not_found("RUNNER_EVIDENCE_NOT_FOUND", "Runner 证据不存在")
        return _runner_snapshot(bundle)


def _policy_rules(policy: ReleasePolicy) -> ReleasePolicyRules:
    return ReleasePolicyRules(
        require_quality_gate=policy.require_quality_gate,
        require_contract_compatibility=policy.require_contract_compatibility,
        require_impact_evidence=policy.require_impact_evidence,
        min_impact_coverage_percent=policy.min_impact_coverage_percent,
        require_release_risk=policy.require_release_risk,
        max_release_risk_score=policy.max_release_risk_score,
        require_performance_evidence=policy.require_performance_evidence,
        require_runner_evidence=policy.require_runner_evidence,
    )


def _policy_snapshot(policy: ReleasePolicy) -> dict[str, JsonValue]:
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "policy_id": str(policy.id),
        "name": policy.name,
        "quality_gate_id": str(policy.quality_gate_id) if policy.quality_gate_id else None,
        **cast(dict[str, JsonValue], asdict(_policy_rules(policy))),
        "policy_updated_at": policy.updated_at.isoformat(),
    }


def _quality_snapshot(bundle: QualityEvidenceBundle, gate_id: UUID) -> dict[str, JsonValue]:
    evaluation = bundle.evaluation
    return {
        "test_plan_run_id": str(bundle.run.id),
        "quality_gate_id": str(gate_id),
        "run_status": bundle.run.status,
        "status": evaluation.status if evaluation else "missing",
        "quality_summary": cast(JsonValue, bundle.run.quality_summary),
        "metrics": cast(JsonValue, evaluation.metrics) if evaluation else None,
        "violations": cast(JsonValue, evaluation.violations) if evaluation else None,
        "evaluated_at": evaluation.evaluated_at.isoformat() if evaluation else None,
    }


def _impact_snapshot(bundle: ImpactEvidenceBundle) -> dict[str, JsonValue]:
    coverage = bundle.coverage
    return {
        "run_id": str(bundle.run.id),
        "status": bundle.run.status,
        "source_ref": bundle.run.source_ref,
        "source_fingerprint": bundle.run.source_fingerprint,
        "change_count": bundle.run.change_count,
        "summary": cast(JsonValue, bundle.run.summary),
        "coverage_percent": coverage.coverage_percent if coverage else None,
        "total_changes": coverage.total_changes if coverage else None,
        "covered_changes": coverage.covered_changes if coverage else None,
        "gaps": cast(JsonValue, coverage.gaps) if coverage else None,
        "created_at": bundle.run.created_at.isoformat(),
    }


def _performance_snapshot(bundle: PerformanceEvidenceBundle) -> dict[str, JsonValue]:
    return {
        "run_id": str(bundle.run.id),
        "scenario_id": str(bundle.run.scenario_id),
        "scenario_version": bundle.run.scenario_version,
        "status": bundle.run.status,
        "summary": cast(JsonValue, bundle.run.summary),
        "threshold_results": cast(JsonValue, bundle.run.threshold_results),
        "gate_statuses": cast(JsonValue, [item.status for item in bundle.evaluations]),
        "gate_evaluations": cast(
            JsonValue,
            [
                {
                    "id": str(item.id),
                    "quality_gate_id": str(item.quality_gate_id),
                    "status": item.status,
                    "metrics": item.metrics,
                    "violations": item.violations,
                    "evaluated_at": item.evaluated_at.isoformat(),
                }
                for item in bundle.evaluations
            ],
        ),
        "completed_at": bundle.run.completed_at.isoformat() if bundle.run.completed_at else None,
    }


def _runner_snapshot(bundle: RunnerEvidenceBundle) -> dict[str, JsonValue]:
    completed = sum(item.status == "completed" for item in bundle.leases)
    return {
        "task_id": str(bundle.task.id),
        "execution_id": str(bundle.task.execution_id),
        "status": bundle.task.status,
        "attempts": bundle.task.attempts,
        "fencing_token": bundle.task.fencing_token,
        "completed_lease_count": completed,
        "leases": cast(
            JsonValue,
            [
                {
                    "id": str(item.id),
                    "runner_id": str(item.runner_id),
                    "fencing_token": item.fencing_token,
                    "status": item.status,
                    "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                }
                for item in bundle.leases
            ],
        ),
        "completed_at": bundle.task.completed_at.isoformat() if bundle.task.completed_at else None,
    }


def _fingerprint(
    *,
    candidate_ref: str,
    policy_snapshot: dict[str, JsonValue],
    evidence_snapshot: dict[str, JsonValue],
    reasons: list[dict[str, JsonValue]],
) -> str:
    payload = {
        "candidate_ref": candidate_ref,
        "policy": policy_snapshot,
        "evidence": evidence_snapshot,
        "reasons": reasons,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _evidence_not_found(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=404)
