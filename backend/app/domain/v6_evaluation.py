"""Model-independent V6 evaluation annotation and aggregation contract."""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EVALUATION_SCHEMA_VERSION = "flowtest-v6-evaluation-v1"


class EvaluationMetric(StrEnum):
    OPERATION_CANDIDATE_PRECISION = "operation_candidate_precision"
    BINDING_CANDIDATE_PRECISION = "binding_candidate_precision"
    COMPILER_SUCCESS = "compiler_success"
    MANUAL_EDIT_RATE = "manual_edit_rate"
    PREVIEW_FIRST_PASS = "preview_first_pass"  # noqa: S105
    EVIDENCE_CONFLICT_RATE = "evidence_conflict_rate"


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


def summarize_evaluations(
    annotations: list[EvaluationAnnotation],
) -> tuple[EvaluationMetricSummary, ...]:
    summaries: list[EvaluationMetricSummary] = []
    for metric in EvaluationMetric:
        counts = Counter(item.label for item in annotations if item.metric is metric)
        numerator, denominator = _score(metric, counts)
        summaries.append(
            EvaluationMetricSummary(
                metric=metric,
                numerator=numerator,
                denominator=denominator,
                value=round(numerator / denominator, 6) if denominator else None,
                label_counts=dict(sorted(counts.items())),
            )
        )
    return tuple(summaries)


def _score(metric: EvaluationMetric, counts: Counter[EvaluationLabel]) -> tuple[int, int]:
    if metric in {
        EvaluationMetric.OPERATION_CANDIDATE_PRECISION,
        EvaluationMetric.BINDING_CANDIDATE_PRECISION,
    }:
        return counts["true_positive"], counts["true_positive"] + counts["false_positive"]
    if metric in {EvaluationMetric.COMPILER_SUCCESS, EvaluationMetric.PREVIEW_FIRST_PASS}:
        return counts["pass"], counts["pass"] + counts["fail"]
    return counts["yes"], counts["yes"] + counts["no"]
