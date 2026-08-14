from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

ReleaseDecisionStatus = Literal["pass", "block"]
EvidenceStatus = Literal["passed", "blocked"]


@dataclass(frozen=True, slots=True)
class ReleasePolicyRules:
    require_quality_gate: bool
    require_contract_compatibility: bool
    require_impact_evidence: bool
    min_impact_coverage_percent: float
    require_release_risk: bool
    max_release_risk_score: float
    require_performance_evidence: bool
    require_runner_evidence: bool


@dataclass(frozen=True, slots=True)
class ReleaseEvidenceFacts:
    quality_gate_status: str | None = None
    contract_decision: str | None = None
    impact_status: str | None = None
    impact_coverage_percent: float | None = None
    release_risk_score: float | None = None
    performance_status: str | None = None
    performance_gate_statuses: tuple[str, ...] = ()
    runner_task_status: str | None = None
    runner_fencing_token: int | None = None
    runner_completed_lease_count: int = 0


@dataclass(frozen=True, slots=True)
class ReleaseReason:
    code: str
    evidence_type: str
    status: EvidenceStatus
    message: str
    actual: JsonValue
    expected: JsonValue


@dataclass(frozen=True, slots=True)
class ReleaseEvaluation:
    status: ReleaseDecisionStatus
    reasons: tuple[ReleaseReason, ...]


def evaluate_release(
    rules: ReleasePolicyRules, evidence: ReleaseEvidenceFacts
) -> ReleaseEvaluation:
    reasons = (
        _quality_reason(rules, evidence),
        _contract_reason(rules, evidence),
        _impact_reason(rules, evidence),
        _risk_reason(rules, evidence),
        _performance_reason(rules, evidence),
        _runner_reason(rules, evidence),
    )
    return ReleaseEvaluation(
        status="block" if any(reason.status == "blocked" for reason in reasons) else "pass",
        reasons=reasons,
    )


def _quality_reason(rules: ReleasePolicyRules, evidence: ReleaseEvidenceFacts) -> ReleaseReason:
    if evidence.quality_gate_status is None:
        return _missing("quality_gate", "QUALITY_GATE_EVIDENCE_MISSING", rules.require_quality_gate)
    passed = evidence.quality_gate_status == "passed"
    return _reason(
        code="QUALITY_GATE_PASSED" if passed else "QUALITY_GATE_BLOCKED",
        evidence_type="quality_gate",
        passed=passed,
        message="质量门禁通过" if passed else "质量门禁未通过",
        actual=evidence.quality_gate_status,
        expected="passed",
    )


def _contract_reason(rules: ReleasePolicyRules, evidence: ReleaseEvidenceFacts) -> ReleaseReason:
    if evidence.contract_decision is None:
        return _missing(
            "contract_compatibility",
            "CONTRACT_EVIDENCE_MISSING",
            rules.require_contract_compatibility,
        )
    passed = evidence.contract_decision == "safe"
    return _reason(
        code="CONTRACT_COMPATIBLE" if passed else "CONTRACT_INCOMPATIBLE",
        evidence_type="contract_compatibility",
        passed=passed,
        message="契约兼容判断安全" if passed else "契约兼容判断不是安全状态",
        actual=evidence.contract_decision,
        expected="safe",
    )


def _impact_reason(rules: ReleasePolicyRules, evidence: ReleaseEvidenceFacts) -> ReleaseReason:
    if evidence.impact_status is None or evidence.impact_coverage_percent is None:
        return _missing("impact", "IMPACT_EVIDENCE_MISSING", rules.require_impact_evidence)
    passed = (
        evidence.impact_status == "completed"
        and evidence.impact_coverage_percent >= rules.min_impact_coverage_percent
    )
    return _reason(
        code="IMPACT_COVERAGE_PASSED" if passed else "IMPACT_COVERAGE_BLOCKED",
        evidence_type="impact",
        passed=passed,
        message="影响分析覆盖率达到策略要求" if passed else "影响分析未完成或覆盖率不足",
        actual=evidence.impact_coverage_percent,
        expected=rules.min_impact_coverage_percent,
    )


def _risk_reason(rules: ReleasePolicyRules, evidence: ReleaseEvidenceFacts) -> ReleaseReason:
    if evidence.release_risk_score is None:
        return _missing("release_risk", "RELEASE_RISK_EVIDENCE_MISSING", rules.require_release_risk)
    passed = evidence.release_risk_score <= rules.max_release_risk_score
    return _reason(
        code="RELEASE_RISK_ACCEPTED" if passed else "RELEASE_RISK_TOO_HIGH",
        evidence_type="release_risk",
        passed=passed,
        message="发布风险分数在策略范围内" if passed else "发布风险分数超过策略上限",
        actual=evidence.release_risk_score,
        expected=rules.max_release_risk_score,
    )


def _performance_reason(rules: ReleasePolicyRules, evidence: ReleaseEvidenceFacts) -> ReleaseReason:
    if evidence.performance_status is None:
        return _missing(
            "performance",
            "PERFORMANCE_EVIDENCE_MISSING",
            rules.require_performance_evidence,
        )
    passed = evidence.performance_status == "passed" and all(
        status == "passed" for status in evidence.performance_gate_statuses
    )
    return _reason(
        code="PERFORMANCE_PASSED" if passed else "PERFORMANCE_BLOCKED",
        evidence_type="performance",
        passed=passed,
        message="性能运行及门禁通过" if passed else "性能运行或性能门禁未通过",
        actual={
            "run_status": evidence.performance_status,
            "gate_statuses": list(evidence.performance_gate_statuses),
        },
        expected="passed",
    )


def _runner_reason(rules: ReleasePolicyRules, evidence: ReleaseEvidenceFacts) -> ReleaseReason:
    if evidence.runner_task_status is None:
        return _missing("runner", "RUNNER_EVIDENCE_MISSING", rules.require_runner_evidence)
    passed = (
        evidence.runner_task_status == "completed"
        and evidence.runner_fencing_token is not None
        and evidence.runner_fencing_token >= 1
        and evidence.runner_completed_lease_count == 1
    )
    return _reason(
        code="RUNNER_EVIDENCE_PASSED" if passed else "RUNNER_EVIDENCE_BLOCKED",
        evidence_type="runner",
        passed=passed,
        message="Runner 任务具有唯一受 Fence 保护的终态"
        if passed
        else "Runner 终态或 Fence 证据不完整",
        actual={
            "task_status": evidence.runner_task_status,
            "fencing_token": evidence.runner_fencing_token,
            "completed_lease_count": evidence.runner_completed_lease_count,
        },
        expected={"task_status": "completed", "minimum_fencing_token": 1, "completed_leases": 1},
    )


def _missing(evidence_type: str, code: str, required: bool) -> ReleaseReason:
    return ReleaseReason(
        code=code if required else f"{code}_OPTIONAL",
        evidence_type=evidence_type,
        status="blocked" if required else "passed",
        message="缺少策略要求的证据" if required else "策略未要求此类证据",
        actual=None,
        expected="required" if required else "optional",
    )


def _reason(
    *,
    code: str,
    evidence_type: str,
    passed: bool,
    message: str,
    actual: JsonValue,
    expected: JsonValue,
) -> ReleaseReason:
    return ReleaseReason(
        code=code,
        evidence_type=evidence_type,
        status="passed" if passed else "blocked",
        message=message,
        actual=actual,
        expected=expected,
    )
