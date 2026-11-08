"""Eight independent quality ratios over a frozen task set; no model self-scoring input."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from scripts.selftest.contracts import Contract, Identity, Sha256, canonical_digest
from scripts.selftest.io import HarnessError

MetricName = Literal[
    "protocol_availability",
    "design_validity",
    "executable_asset_generation",
    "required_oracle_landing",
    "first_generation_execution_match",
    "assisted_execution_match",
    "fixed_defect_detection",
    "source_completeness",
]


class QualityTask(Contract):
    task_id: Identity
    variant_key: Identity = "default"
    required_oracle_ids: tuple[Identity, ...] = Field(default=(), max_length=500)
    known_defect: bool = False
    exclusion_reason: Identity | None = None


class QualityTaskSet(Contract):
    version: Identity
    tasks: tuple[QualityTask, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_tasks(self) -> QualityTaskSet:
        keys = [(item.task_id, item.variant_key) for item in self.tasks]
        if len(keys) != len(set(keys)):
            raise ValueError("frozen quality task set cannot contain duplicates")
        return self


class AssistedRevision(Contract):
    before_proposal_id: UUID
    after_proposal_id: UUID
    before_fingerprint: Sha256
    after_fingerprint: Sha256
    reviewer_id: UUID
    reason_digest: Sha256
    independent_execution_match: bool | None
    review_mode: Literal["human", "ci_fixture"]


class QualityAttempt(Contract):
    task_id: Identity
    variant_key: Identity = "default"
    attempt_id: UUID
    ordinal: int = Field(ge=1, le=100, strict=True)
    evidence_digest: Sha256
    review_mode: Literal["human", "ci_fixture"]
    generation_kind: Literal["model", "assisted"] = "model"
    # None means no independent observation, never success inferred from a generated summary.
    protocol_available: bool | None = None
    design_valid: bool | None = None
    executable_asset_generated: bool | None = None
    landed_oracle_ids: tuple[Identity, ...] | None = Field(default=None, max_length=500)
    independent_execution_match: bool | None = None
    fixed_defect_detected: bool | None = None
    source_complete: bool | None = None
    assisted: AssistedRevision | None = None


class QualityRatio(Contract):
    name: MetricName
    numerator: int = Field(ge=0, strict=True)
    denominator: int = Field(ge=0, strict=True)
    status: Literal["EVALUATED", "NOT_EVALUATED", "INCOMPLETE"]
    unobserved_count: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode="after")
    def consistent_ratio(self) -> QualityRatio:
        if self.numerator > self.denominator or self.unobserved_count > self.denominator:
            raise ValueError("ratio must preserve its actual denominator")
        expected = (
            "NOT_EVALUATED"
            if self.denominator == 0
            else ("INCOMPLETE" if self.unobserved_count else "EVALUATED")
        )
        if self.status != expected:
            raise ValueError("ratio cannot hide missing observations")
        return self


class HostQualityReport(Contract):
    schema_version: Literal["flowtest-host-quality-v1"] = "flowtest-host-quality-v1"
    taskset_version: Identity
    taskset_digest: Sha256
    selected_task_count: int = Field(ge=1)
    coverage: Literal["NOT_RUN", "PARTIAL", "COMPLETE"]
    evaluation_status: Literal["EVALUATED", "NOT_EVALUATED", "INCOMPLETE"]
    excluded: tuple[QualityTask, ...]
    not_run_task_ids: tuple[Identity, ...]
    attempts: tuple[QualityAttempt, ...]
    metrics: tuple[QualityRatio, ...] = Field(min_length=8, max_length=8)

    @model_validator(mode="after")
    def complete_metric_status(self) -> HostQualityReport:
        if len({item.name for item in self.metrics}) != 8:
            raise ValueError("quality report must preserve all eight independent metrics")
        if self.evaluation_status != _evaluation_status(self.coverage, list(self.metrics)):
            raise ValueError("whole quality status cannot hide incomplete task coverage")
        return self


def _ratio(name: MetricName, values: list[bool | None]) -> QualityRatio:
    missing = sum(item is None for item in values)
    return QualityRatio(
        name=name,
        numerator=sum(item is True for item in values),
        denominator=len(values),
        unobserved_count=missing,
        status="NOT_EVALUATED" if not values else ("INCOMPLETE" if missing else "EVALUATED"),
    )


def quality_report(
    taskset: QualityTaskSet, attempts: tuple[QualityAttempt, ...]
) -> HostQualityReport:
    selected = {
        (item.task_id, item.variant_key): item
        for item in taskset.tasks
        if item.exclusion_reason is None
    }
    keys = [(item.task_id, item.variant_key, item.ordinal) for item in attempts]
    if len(keys) != len(set(keys)) or len(
        {(item.task_id, item.variant_key, item.attempt_id) for item in attempts}
    ) != len(attempts):
        raise HarnessError("HOST_QUALITY_ATTEMPT_DUPLICATE")
    if any((item.task_id, item.variant_key) not in selected for item in attempts):
        raise HarnessError("HOST_QUALITY_UNSELECTED_ATTEMPT")
    for task, variant in selected:
        ordinals = sorted(
            item.ordinal for item in attempts if (item.task_id, item.variant_key) == (task, variant)
        )
        if ordinals != list(range(1, len(ordinals) + 1)):
            raise HarnessError("HOST_QUALITY_ATTEMPT_SEQUENCE_INCOMPLETE")
    metrics: list[QualityRatio] = []
    boolean_fields: tuple[tuple[MetricName, str], ...] = (
        ("protocol_availability", "protocol_available"),
        ("design_validity", "design_valid"),
        ("executable_asset_generation", "executable_asset_generated"),
        ("source_completeness", "source_complete"),
    )
    for name, field in boolean_fields:
        values = [
            getattr(item, field)
            for item in attempts
            if name == "source_completeness"
            or (item.generation_kind == "model" and item.assisted is None)
        ]
        metrics.append(_ratio(name, values))
    oracle_values: list[bool | None] = []
    for item in attempts:
        required = selected[(item.task_id, item.variant_key)].required_oracle_ids
        oracle_values.extend(
            None if item.landed_oracle_ids is None else identifier in item.landed_oracle_ids
            for identifier in required
        )
    metrics.extend(
        (
            _ratio("required_oracle_landing", oracle_values),
            _ratio(
                "first_generation_execution_match",
                [
                    item.independent_execution_match
                    for item in attempts
                    if item.ordinal == 1
                    and item.generation_kind == "model"
                    and item.assisted is None
                ],
            ),
            _ratio(
                "assisted_execution_match",
                [
                    item.assisted.independent_execution_match
                    for item in attempts
                    if item.assisted is not None
                ],
            ),
            _ratio(
                "fixed_defect_detection",
                [
                    item.fixed_defect_detected
                    for item in attempts
                    if selected[(item.task_id, item.variant_key)].known_defect
                ],
            ),
        )
    )
    observed = {(item.task_id, item.variant_key) for item in attempts}
    coverage = _coverage(set(selected), observed)
    return HostQualityReport(
        taskset_version=taskset.version,
        taskset_digest=canonical_digest(taskset.model_dump(mode="json")),
        selected_task_count=len(taskset.tasks),
        coverage=coverage,
        evaluation_status=_evaluation_status(coverage, metrics),
        excluded=tuple(item for item in taskset.tasks if item.exclusion_reason is not None),
        not_run_task_ids=tuple(
            task + ":" + variant for task, variant in selected if (task, variant) not in observed
        ),
        attempts=attempts,
        metrics=tuple(metrics),
    )


def _coverage(
    selected: set[tuple[str, str]], observed: set[tuple[str, str]]
) -> Literal["NOT_RUN", "PARTIAL", "COMPLETE"]:
    if not observed:
        return "NOT_RUN"
    return "COMPLETE" if selected == observed else "PARTIAL"


def _evaluation_status(
    coverage: Literal["NOT_RUN", "PARTIAL", "COMPLETE"], metrics: list[QualityRatio]
) -> Literal["EVALUATED", "NOT_EVALUATED", "INCOMPLETE"]:
    if coverage == "NOT_RUN":
        return "NOT_EVALUATED"
    if coverage != "COMPLETE" or any(item.status == "INCOMPLETE" for item in metrics):
        return "INCOMPLETE"
    return "EVALUATED"
