from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, TypedDict
from uuid import UUID

from pydantic import JsonValue


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class FailureObservation:
    execution_id: UUID
    workflow_id: UUID
    workflow_name: str
    category: str
    error_code: str | None
    node_type: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class FailureClusterEvidence:
    fingerprint: str
    title: str
    category: str
    error_code: str | None
    node_type: str | None
    occurrence_count: int
    baseline_count: int
    affected_workflow_ids: tuple[str, ...]
    affected_workflow_names: tuple[str, ...]
    sample_execution_ids: tuple[str, ...]
    confidence: float
    regression_percent: float | None
    recommendation: str


@dataclass(frozen=True, slots=True)
class RiskInput:
    coverage_percent: float
    breaking_changes: int
    current_total: int
    current_failures: int
    baseline_total: int
    baseline_failures: int
    regressed_clusters: int
    unsafe_contracts: int
    unknown_contracts: int
    performance_regression_percent: float
    flaky_assets: int


class RiskFactor(TypedDict):
    code: str
    label: str
    score: float
    max_score: int
    value: JsonValue


class RiskImpactEvidence(TypedDict):
    run_id: str
    source_fingerprint: str
    change_count: int
    breaking_change_count: int
    selection_id: str
    selection_strategy: str
    selected_asset_count: int
    coverage_snapshot_id: str
    coverage_percent: float
    coverage_gap_count: int


class RiskExecutionEvidence(TypedDict):
    current_total: int
    current_failures: int
    baseline_total: int
    baseline_failures: int


class RiskFailureClusterEvidence(TypedDict):
    count: int
    regressed_count: int


class RiskContractEvidence(TypedDict):
    unsafe: int
    unknown: int
    safe: int


class RiskPerformanceEvidence(TypedDict):
    run_id: str | None
    p95_regression_percent: float


class RiskEvidenceSnapshot(TypedDict):
    impact: RiskImpactEvidence
    executions: RiskExecutionEvidence
    failure_clusters: RiskFailureClusterEvidence
    contracts: RiskContractEvidence
    performance: RiskPerformanceEvidence
    flaky_assets: int


class QualityTrendPoint(TypedDict):
    date: str
    total: int
    passed: int
    failed: int
    pass_rate: float


class RecommendedTest(TypedDict):
    target_type: str
    target_id: str
    name: str
    version: str | int | None
    priority: Literal["high", "medium"]
    reasons: list[str]
    change_keys: list[str]


class RiskWindowFingerprint(TypedDict):
    current_started_at: str
    current_ended_at: str
    baseline_started_at: str
    baseline_ended_at: str


class RiskScoreFingerprint(TypedDict):
    score: float
    quality_score: float
    risk_level: str
    factors: list[RiskFactor]


class RiskClusterFingerprint(TypedDict):
    fingerprint: str
    title: str
    category: str
    error_code: str | None
    node_type: str | None
    occurrence_count: int
    baseline_count: int
    affected_workflow_ids: list[str]
    affected_workflow_names: list[str]
    sample_execution_ids: list[str]
    confidence: float
    regression_percent: float | None
    recommendation: str


class RiskFingerprintPayload(TypedDict):
    algorithm_version: str
    window: RiskWindowFingerprint
    score: RiskScoreFingerprint
    evidence: RiskEvidenceSnapshot
    failure_clusters: list[RiskClusterFingerprint]
    quality_trend: list[QualityTrendPoint]
    recommended_tests: list[RecommendedTest]


@dataclass(frozen=True, slots=True)
class RiskResult:
    score: float
    level: RiskLevel
    quality_score: float
    factors: tuple[RiskFactor, ...]


def cluster_failures(
    current: tuple[FailureObservation, ...],
    baseline: tuple[FailureObservation, ...],
) -> tuple[FailureClusterEvidence, ...]:
    current_groups = _group_observations(current)
    baseline_counts = {
        signature: len(items) for signature, items in _group_observations(baseline).items()
    }
    clusters = [
        _cluster(signature, observations, baseline_counts.get(signature, 0))
        for signature, observations in current_groups.items()
    ]
    return tuple(sorted(clusters, key=lambda item: (-item.occurrence_count, item.fingerprint)))


def calculate_release_risk(value: RiskInput) -> RiskResult:
    coverage_score = round(max(0.0, min(25.0, (100.0 - value.coverage_percent) * 0.25)), 2)
    breaking_score = float(min(20, value.breaking_changes * 5))
    current_rate = _rate(value.current_failures, value.current_total)
    baseline_rate = _rate(value.baseline_failures, value.baseline_total)
    failure_score = round(
        min(20.0, current_rate * 10.0 + max(current_rate - baseline_rate, 0.0) * 20.0),
        2,
    )
    cluster_score = float(min(15, value.regressed_clusters * 5))
    contract_score = float(min(10, value.unsafe_contracts * 5 + value.unknown_contracts * 2))
    performance_score = round(
        min(5.0, max(value.performance_regression_percent, 0.0) / 20.0 * 5.0), 2
    )
    flaky_score = float(min(5, value.flaky_assets))
    factors = (
        _factor("coverage_gap", "覆盖缺口", coverage_score, 25, value.coverage_percent),
        _factor("breaking_changes", "破坏性变更", breaking_score, 20, value.breaking_changes),
        _factor(
            "failure_regression",
            "失败回归",
            failure_score,
            20,
            {
                "current_rate": round(current_rate * 100, 2),
                "baseline_rate": round(baseline_rate * 100, 2),
            },
        ),
        _factor("failure_clusters", "回归失败簇", cluster_score, 15, value.regressed_clusters),
        _factor(
            "contract_compatibility",
            "契约兼容性",
            contract_score,
            10,
            {"unsafe": value.unsafe_contracts, "unknown": value.unknown_contracts},
        ),
        _factor(
            "performance_regression",
            "性能回归",
            performance_score,
            5,
            round(value.performance_regression_percent, 2),
        ),
        _factor("flaky_assets", "Flaky 资产", flaky_score, 5, value.flaky_assets),
    )
    score = round(
        coverage_score
        + breaking_score
        + failure_score
        + cluster_score
        + contract_score
        + performance_score
        + flaky_score,
        2,
    )
    return RiskResult(
        score=score,
        level=_risk_level(score),
        quality_score=round(100.0 - score, 2),
        factors=factors,
    )


def evidence_fingerprint(value: RiskFingerprintPayload) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _group_observations(
    observations: tuple[FailureObservation, ...],
) -> dict[str, list[FailureObservation]]:
    groups: dict[str, list[FailureObservation]] = defaultdict(list)
    for observation in observations:
        groups[_signature(observation)].append(observation)
    return groups


def _signature(observation: FailureObservation) -> str:
    return "|".join(
        (
            observation.category,
            observation.error_code or "UNCLASSIFIED",
            observation.node_type or "execution",
        )
    )


def _cluster(
    signature: str,
    observations: list[FailureObservation],
    baseline_count: int,
) -> FailureClusterEvidence:
    first = observations[0]
    workflow_pairs = sorted({(str(item.workflow_id), item.workflow_name) for item in observations})
    occurrence_count = len(observations)
    confidence = round(min(0.99, 0.55 + occurrence_count / (occurrence_count + 4) * 0.44), 4)
    return FailureClusterEvidence(
        fingerprint=hashlib.sha256(signature.encode()).hexdigest(),
        title=_cluster_title(first.category, first.error_code, first.node_type),
        category=first.category,
        error_code=first.error_code,
        node_type=first.node_type,
        occurrence_count=occurrence_count,
        baseline_count=baseline_count,
        affected_workflow_ids=tuple(item[0] for item in workflow_pairs),
        affected_workflow_names=tuple(item[1] for item in workflow_pairs),
        sample_execution_ids=tuple(
            str(item.execution_id)
            for item in sorted(observations, key=lambda value: value.occurred_at, reverse=True)[:5]
        ),
        confidence=confidence,
        regression_percent=_regression_percent(occurrence_count, baseline_count),
        recommendation=_recommendation(first.category),
    )


def _cluster_title(category: str, error_code: str | None, node_type: str | None) -> str:
    parts = [error_code or _category_label(category)]
    if node_type:
        parts.append(node_type)
    return " · ".join(parts)[:200]


def _category_label(category: str) -> str:
    labels = {
        "assertion": "断言失败",
        "timeout": "执行超时",
        "network": "网络失败",
        "http_client": "HTTP 客户端错误",
        "http_server": "HTTP 服务端错误",
        "configuration": "配置错误",
        "runtime": "运行时错误",
        "cancelled": "执行取消",
    }
    return labels.get(category, "未分类失败")


def _recommendation(category: str) -> str:
    recommendations = {
        "assertion": "先核对契约与响应字段变更。再更新断言草稿。",
        "timeout": "检查目标服务延迟、性能基线与 Runner 网络区。",
        "network": "检查目标可达性、DNS/CIDR 策略与 Runner 网络区。",
        "http_client": "检查变更后的请求契约、认证和测试数据。",
        "http_server": "优先检查目标服务日志与最近部署变更。",
        "configuration": "检查环境、变量、Credential 引用和版本快照。",
        "cancelled": "确认取消来源与上游失败传播是否符合预期。",
    }
    return recommendations.get(category, "下钻样本执行并按稳定错误码定位根因。")


def _regression_percent(current: int, baseline: int) -> float | None:
    if baseline == 0:
        return None if current == 0 else 100.0
    return round((current - baseline) / baseline * 100.0, 2)


def _rate(count: int, total: int) -> float:
    return count / total if total > 0 else 0.0


def _factor(
    code: str,
    label: str,
    score: float,
    maximum: int,
    value: JsonValue,
) -> RiskFactor:
    return {
        "code": code,
        "label": label,
        "score": score,
        "max_score": maximum,
        "value": value,
    }


def _risk_level(score: float) -> RiskLevel:
    if score >= 75:
        return RiskLevel.CRITICAL
    if score >= 50:
        return RiskLevel.HIGH
    if score >= 30:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW
