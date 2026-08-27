"""Deterministic failure-triage rules over structured execution evidence."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FailureClassification = Literal[
    "PRODUCT_DEFECT",
    "BAD_TEST",
    "BAD_TEST_DATA",
    "ENVIRONMENT_FAILURE",
    "SERVICE_ENDPOINT_FAILURE",
    "UPSTREAM_SERVICE_FAILURE",
    "CONTRACT_DRIFT",
    "AUTH_FAILURE",
    "NETWORK_FAILURE",
    "TIMEOUT",
    "FLAKY",
    "CANCELLED",
    "UNKNOWN",
]


class FailureSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_ref: str = Field(min_length=1, max_length=512)
    item_status: str = Field(min_length=1, max_length=32)
    attempts: int = Field(ge=0, le=100)
    error_code: str | None = Field(default=None, max_length=100)
    retryable: bool = False
    http_status: int | None = Field(default=None, ge=100, le=599)
    affected_service: str | None = Field(default=None, max_length=255)
    endpoint_variant: str | None = Field(default=None, max_length=80)
    affected_operation: str | None = Field(default=None, max_length=2048)
    response_received: bool = False
    assertion_failed: bool = False
    contract_assertion_failed: bool = False


class FailureTriageResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    algorithm_version: Literal["s47-failure-triage-v2"] = "s47-failure-triage-v2"
    primary_classification: FailureClassification
    secondary_candidates: list[FailureClassification] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    affected_service: str | None = None
    endpoint_variant: str | None = None
    affected_operation: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    retry_signal: bool = False
    recommended_action: str
    recommended_regression: list[str] = Field(default_factory=list)


def triage_failures(signals: list[FailureSignal]) -> FailureTriageResult:
    if not signals:
        return _result("UNKNOWN", signals, ["NO_STRUCTURED_FAILURE_EVIDENCE"])
    candidates = [_classify(signal) for signal in signals]
    primary = _primary(candidates, signals)
    reasons = sorted({reason for _, reason in candidates})
    if primary == "SERVICE_ENDPOINT_FAILURE" and _multi_node_service(signals):
        reasons.append("MULTIPLE_NODES_SAME_SERVICE")
    secondary = _secondary(primary, candidates, signals)
    return _result(primary, signals, sorted(set(reasons)), secondary)


def _classify(signal: FailureSignal) -> tuple[FailureClassification, str]:
    status_result = _status_classification(signal)
    if status_result is not None:
        return status_result
    if signal.http_status in {401, 403}:
        return "AUTH_FAILURE", "HTTP_AUTH_STATUS"
    if signal.contract_assertion_failed:
        return "CONTRACT_DRIFT", "CONTRACT_ASSERTION_FAILED"
    if (
        signal.assertion_failed
        and signal.response_received
        and signal.http_status is not None
        and signal.http_status >= 500
    ):
        return "PRODUCT_DEFECT", "SERVER_RESPONSE_ASSERTION_MISMATCH"
    response_result = _response_classification(signal)
    if response_result is not None:
        return response_result
    code_result = _code_classification(signal.error_code or "")
    if code_result is not None:
        return code_result
    if signal.assertion_failed and signal.response_received:
        return "PRODUCT_DEFECT", "DETERMINISTIC_ASSERTION_MISMATCH"
    return "UNKNOWN", "NO_RULE_MATCH"


def _status_classification(
    signal: FailureSignal,
) -> tuple[FailureClassification, str] | None:
    if signal.item_status == "cancelled":
        return "CANCELLED", "ITEM_CANCELLED"
    if signal.item_status == "passed" and signal.attempts > 1:
        return "FLAKY", "RETRY_EVENTUALLY_PASSED"
    return None


def _response_classification(
    signal: FailureSignal,
) -> tuple[FailureClassification, str] | None:
    if signal.http_status in {401, 403}:
        return "AUTH_FAILURE", "HTTP_AUTH_STATUS"
    if signal.http_status is not None and signal.http_status >= 500:
        return "UPSTREAM_SERVICE_FAILURE", "UPSTREAM_RESPONSE_5XX"
    return None


def _code_classification(code: str) -> tuple[FailureClassification, str] | None:
    if code in _TIMEOUT_CODES:
        return "TIMEOUT", "STRUCTURED_TIMEOUT_CODE"
    if code in _NETWORK_CODES:
        return "NETWORK_FAILURE", "STRUCTURED_NETWORK_CODE"
    if code in _ENDPOINT_CODES:
        return "SERVICE_ENDPOINT_FAILURE", "ENDPOINT_OR_SERVER_FAILURE"
    if code in _CONTRACT_CODES:
        return "CONTRACT_DRIFT", "CONTRACT_ASSERTION_FAILED"
    if code in _AUTH_CODES:
        return "AUTH_FAILURE", "STRUCTURED_AUTH_CODE"
    if code in _DATA_CODES:
        return "BAD_TEST_DATA", "STRUCTURED_TEST_DATA_CODE"
    if code in _ENVIRONMENT_CODES:
        return "ENVIRONMENT_FAILURE", "STRUCTURED_ENVIRONMENT_CODE"
    if code in _BAD_TEST_CODES:
        return "BAD_TEST", "STRUCTURED_TEST_DEFINITION_CODE"
    return None


def _primary(
    candidates: list[tuple[FailureClassification, str]], signals: list[FailureSignal]
) -> FailureClassification:
    classes = [classification for classification, _ in candidates]
    if "NETWORK_FAILURE" in classes and _multi_node_service(signals):
        return "SERVICE_ENDPOINT_FAILURE"
    counts = Counter(classes)
    return max(counts, key=lambda item: (counts[item], _PRIORITY[item]))


def _secondary(
    primary: FailureClassification,
    candidates: list[tuple[FailureClassification, str]],
    signals: list[FailureSignal],
) -> list[FailureClassification]:
    values = {classification for classification, _ in candidates if classification != primary}
    if primary == "PRODUCT_DEFECT":
        values.add("BAD_TEST")
    if any(signal.attempts > 1 for signal in signals) and primary != "FLAKY":
        values.add("FLAKY")
    return sorted(values, key=lambda item: (-_PRIORITY[item], item))[:4]


def _multi_node_service(signals: list[FailureSignal]) -> bool:
    services = Counter(
        signal.affected_service
        for signal in signals
        if signal.affected_service and signal.item_status == "failed"
    )
    return any(count >= 2 for count in services.values())


def _result(
    primary: FailureClassification,
    signals: list[FailureSignal],
    reasons: list[str],
    secondary: list[FailureClassification] | None = None,
) -> FailureTriageResult:
    representative = next(
        (signal for signal in signals if signal.item_status == "failed"),
        signals[0] if signals else None,
    )
    confidence = 0.4 if primary == "UNKNOWN" else 0.95 if len(reasons) > 1 else 0.85
    action, regression = _recommendation(primary)
    return FailureTriageResult(
        primary_classification=primary,
        secondary_candidates=secondary or [],
        confidence=confidence,
        reason_codes=reasons,
        affected_service=(representative.affected_service if representative else None),
        endpoint_variant=(representative.endpoint_variant if representative else None),
        affected_operation=(representative.affected_operation if representative else None),
        evidence_refs=sorted({signal.evidence_ref for signal in signals})[:200],
        retry_signal=any(signal.retryable or signal.attempts > 1 for signal in signals),
        recommended_action=action,
        recommended_regression=regression,
    )


def _recommendation(primary: FailureClassification) -> tuple[str, list[str]]:
    return _RECOMMENDATIONS[primary]


_TIMEOUT_CODES = frozenset(
    {"NETWORK_TIMEOUT", "NODE_TIMEOUT", "REQUEST_TIMEOUT", "DATA_NODE_TIMEOUT", "GRAPHQL_TIMEOUT"}
)
_NETWORK_CODES = frozenset({"NETWORK_ERROR", "DNS_ERROR", "CONNECTION_REFUSED"})
_ENDPOINT_CODES = frozenset(
    {
        "SERVICE_ENDPOINT_NOT_FOUND",
        "SERVICE_ENDPOINT_DISABLED",
    }
)
_CONTRACT_CODES = frozenset(
    {"RESPONSE_SCHEMA_MISMATCH", "CONTRACT_ASSERTION_FAILED", "SCHEMA_VALIDATION_FAILED"}
)
_AUTH_CODES = frozenset({"AUTHENTICATION_FAILED", "AUTHORIZATION_FAILED", "HTTP_401", "HTTP_403"})
_DATA_CODES = frozenset(
    {"DATASET_ROW_INVALID", "TEST_DATA_MISSING", "DATA_CONSTRAINT_VIOLATION", "UNRESOLVED_VARIABLE"}
)
_ENVIRONMENT_CODES = frozenset(
    {"CAPABILITY_RUNTIME_UNAVAILABLE", "RUNNER_LEASE_EXHAUSTED", "ENVIRONMENT_PROVISION_TIMEOUT"}
)
_BAD_TEST_CODES = frozenset(
    {"INVALID_NODE_CONFIG", "WORKFLOW_VALIDATION_FAILED", "INVALID_EXPRESSION", "MAPPING_INVALID"}
)
_PRIORITY: dict[FailureClassification, int] = {
    "CANCELLED": 12,
    "AUTH_FAILURE": 11,
    "CONTRACT_DRIFT": 10,
    "SERVICE_ENDPOINT_FAILURE": 9,
    "UPSTREAM_SERVICE_FAILURE": 9,
    "NETWORK_FAILURE": 8,
    "TIMEOUT": 7,
    "ENVIRONMENT_FAILURE": 6,
    "BAD_TEST_DATA": 5,
    "PRODUCT_DEFECT": 4,
    "BAD_TEST": 3,
    "FLAKY": 2,
    "UNKNOWN": 1,
}
_RECOMMENDATIONS: dict[FailureClassification, tuple[str, list[str]]] = {
    "PRODUCT_DEFECT": ("检查产品逻辑与预期断言的差异", ["重跑同一输入", "扩展相邻边界回归"]),
    "BAD_TEST": ("审核测试定义、映射和 Oracle", ["校验测试草案"]),
    "BAD_TEST_DATA": ("修复数据集前置条件或数据映射", ["重跑相同数据分片"]),
    "ENVIRONMENT_FAILURE": ("恢复 Runner 或环境容量后重试", ["环境健康检查"]),
    "SERVICE_ENDPOINT_FAILURE": (
        "检查 Service Endpoint 健康、变体与服务状态",
        ["目标服务健康回归"],
    ),
    "UPSTREAM_SERVICE_FAILURE": (
        "检查上游服务日志、依赖健康与 5xx 响应证据",
        ["固定请求重放", "上游 5xx 回归"],
    ),
    "CONTRACT_DRIFT": ("对比运行响应与当前 Contract", ["重跑 Contract Oracle", "生成差异边界用例"]),
    "AUTH_FAILURE": ("检查认证引用、权限与环境配置", ["认证成功/缺失场景"]),
    "NETWORK_FAILURE": ("检查 DNS、网络路由与代理", ["网络连通性回归"]),
    "TIMEOUT": ("检查超时预算和下游延迟", ["延迟与重试回归"]),
    "FLAKY": ("隔离不稳定用例并收集重试证据", ["多次固定输入重跑"]),
    "CANCELLED": ("确认取消发起人与原因后决定是否重跑", ["人工确认后重跑"]),
    "UNKNOWN": ("收集 NodeResult、HTTP Observation 和 Checkpoint 后人工分析", ["扩充结构化证据"]),
}
