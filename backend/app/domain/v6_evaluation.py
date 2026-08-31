"""Model-independent V6 evaluation annotation and aggregation contract."""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EVALUATION_SCHEMA_VERSION = "flowtest-v6-evaluation-v1"
EVALUATION_BASELINE_SCHEMA_VERSION = "flowtest-v6-evaluation-baseline-v1"


class EvaluationMetric(StrEnum):
    OPERATION_CANDIDATE_PRECISION = "operation_candidate_precision"
    BINDING_CANDIDATE_PRECISION = "binding_candidate_precision"
    COMPILER_SUCCESS = "compiler_success"
    MANUAL_EDIT_RATE = "manual_edit_rate"
    PREVIEW_FIRST_PASS = "preview_first_pass"  # noqa: S105
    EVIDENCE_CONFLICT_RATE = "evidence_conflict_rate"
    EVIDENCE_CONFLICT_DETECTION = "evidence_conflict_detection"
    STATIC_VALIDATION = "static_validation"
    SECRET_LEAK = "secret_leak"  # noqa: S105
    CROSS_TENANT = "cross_tenant"
    STALE_OVERWRITE = "stale_overwrite"
    UNREVIEWED_APPLY = "unreviewed_apply"
    PRODUCTION_MCP_PREVIEW = "production_mcp_preview"
    ARBITRARY_CODE = "arbitrary_code"
    WRITE_SQL = "write_sql"
    CLEANUP_SILENT_FAILURE = "cleanup_silent_failure"
    PRODUCT_DEFECT_AUTO_WEAKENING = "product_defect_auto_weakening"


class EvaluationGatePolicy(StrEnum):
    INFORMATIONAL = "informational"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"


class EvaluationGateStatus(StrEnum):
    INFORMATIONAL = "informational"
    PASSED = "passed"
    FAILED = "failed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


EvaluationLabel = Literal[
    "true_positive",
    "false_positive",
    "false_negative",
    "true_negative",
    "pass",
    "fail",
    "yes",
    "no",
    "not_applicable",
]

_PRECISION_LABELS = frozenset(
    {"true_positive", "false_positive", "false_negative", "true_negative"}
)
_PASS_LABELS = frozenset({"pass", "fail", "not_applicable"})
_BOOLEAN_LABELS = frozenset({"yes", "no", "not_applicable"})


class EvaluationAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-v6-evaluation-v1"] = "flowtest-v6-evaluation-v1"
    case_id: str = Field(min_length=1, max_length=160)
    fixture_id: str = Field(min_length=1, max_length=160)
    metric: EvaluationMetric
    label: EvaluationLabel
    expected_ref: str = Field(min_length=1, max_length=512)
    observed_ref: str = Field(min_length=1, max_length=512)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    source_revision: str = Field(min_length=7, max_length=160)
    annotator_ref: str = Field(min_length=1, max_length=160)
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_metric_label(self) -> EvaluationAnnotation:
        if self.metric in {
            EvaluationMetric.OPERATION_CANDIDATE_PRECISION,
            EvaluationMetric.BINDING_CANDIDATE_PRECISION,
        }:
            allowed = _PRECISION_LABELS
        elif self.metric in {
            EvaluationMetric.COMPILER_SUCCESS,
            EvaluationMetric.PREVIEW_FIRST_PASS,
            EvaluationMetric.EVIDENCE_CONFLICT_DETECTION,
            EvaluationMetric.STATIC_VALIDATION,
        }:
            allowed = _PASS_LABELS
        else:
            allowed = _BOOLEAN_LABELS
        if self.label not in allowed:
            raise ValueError(f"label {self.label!r} is invalid for metric {self.metric.value}")
        return self


class EvaluationMetricSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: EvaluationMetric
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = Field(default=None, ge=0, le=1)
    label_counts: dict[str, int]
    gate_policy: EvaluationGatePolicy
    gate_threshold: float | None = Field(default=None, ge=0, le=1)
    gate_status: EvaluationGateStatus


class EvaluationBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-v6-evaluation-baseline-v1"] = (
        "flowtest-v6-evaluation-baseline-v1"
    )
    annotation_schema_version: Literal["flowtest-v6-evaluation-v1"] = "flowtest-v6-evaluation-v1"
    annotation_count: int = Field(ge=1)
    metrics: list[EvaluationMetricSummary] = Field(min_length=1)
    release_gates_passed: bool


_MINIMUM_GATES = frozenset(
    {
        EvaluationMetric.COMPILER_SUCCESS,
        EvaluationMetric.PREVIEW_FIRST_PASS,
        EvaluationMetric.EVIDENCE_CONFLICT_DETECTION,
        EvaluationMetric.STATIC_VALIDATION,
    }
)
_MAXIMUM_GATES = frozenset(
    {
        EvaluationMetric.SECRET_LEAK,
        EvaluationMetric.CROSS_TENANT,
        EvaluationMetric.STALE_OVERWRITE,
        EvaluationMetric.UNREVIEWED_APPLY,
        EvaluationMetric.PRODUCTION_MCP_PREVIEW,
        EvaluationMetric.ARBITRARY_CODE,
        EvaluationMetric.WRITE_SQL,
        EvaluationMetric.CLEANUP_SILENT_FAILURE,
        EvaluationMetric.PRODUCT_DEFECT_AUTO_WEAKENING,
    }
)


def summarize_evaluations(
    annotations: list[EvaluationAnnotation],
) -> tuple[EvaluationMetricSummary, ...]:
    identities = [(item.metric, item.case_id) for item in annotations]
    if len(identities) != len(set(identities)):
        raise ValueError("evaluation metric and case_id pairs must be unique")
    summaries: list[EvaluationMetricSummary] = []
    for metric in EvaluationMetric:
        counts = Counter(item.label for item in annotations if item.metric is metric)
        numerator, denominator = _score(metric, counts)
        value = round(numerator / denominator, 6) if denominator else None
        gate_policy, gate_threshold = _gate_policy(metric)
        summaries.append(
            EvaluationMetricSummary(
                metric=metric,
                numerator=numerator,
                denominator=denominator,
                value=value,
                label_counts=dict(sorted(counts.items())),
                gate_policy=gate_policy,
                gate_threshold=gate_threshold,
                gate_status=_gate_status(
                    policy=gate_policy,
                    threshold=gate_threshold,
                    numerator=numerator,
                    denominator=denominator,
                ),
            )
        )
    return tuple(summaries)


def build_evaluation_baseline(annotations: list[EvaluationAnnotation]) -> EvaluationBaseline:
    summaries = summarize_evaluations(annotations)
    release_metrics = [
        item for item in summaries if item.gate_policy is not EvaluationGatePolicy.INFORMATIONAL
    ]
    release_gates_passed = bool(release_metrics) and all(
        item.gate_status is EvaluationGateStatus.PASSED for item in release_metrics
    )
    return EvaluationBaseline(
        annotation_count=len(annotations),
        metrics=list(summaries),
        release_gates_passed=release_gates_passed,
    )


def _score(metric: EvaluationMetric, counts: Counter[EvaluationLabel]) -> tuple[int, int]:
    if metric in {
        EvaluationMetric.OPERATION_CANDIDATE_PRECISION,
        EvaluationMetric.BINDING_CANDIDATE_PRECISION,
    }:
        return counts["true_positive"], counts["true_positive"] + counts["false_positive"]
    if metric in _MINIMUM_GATES:
        return counts["pass"], counts["pass"] + counts["fail"]
    return counts["yes"], counts["yes"] + counts["no"]


def _gate_policy(metric: EvaluationMetric) -> tuple[EvaluationGatePolicy, float | None]:
    if metric in _MINIMUM_GATES:
        return EvaluationGatePolicy.MINIMUM, 1.0
    if metric in _MAXIMUM_GATES:
        return EvaluationGatePolicy.MAXIMUM, 0.0
    return EvaluationGatePolicy.INFORMATIONAL, None


def _gate_status(
    *,
    policy: EvaluationGatePolicy,
    threshold: float | None,
    numerator: int,
    denominator: int,
) -> EvaluationGateStatus:
    if denominator == 0:
        return EvaluationGateStatus.INSUFFICIENT_EVIDENCE
    if policy is EvaluationGatePolicy.INFORMATIONAL:
        return EvaluationGateStatus.INFORMATIONAL
    if threshold is None:
        raise ValueError("release-gated evaluation metric must define a threshold")
    raw_value = Fraction(numerator, denominator)
    gate_threshold = Fraction(str(threshold))
    passed = (
        raw_value >= gate_threshold
        if policy is EvaluationGatePolicy.MINIMUM
        else raw_value <= gate_threshold
    )
    return EvaluationGateStatus.PASSED if passed else EvaluationGateStatus.FAILED
