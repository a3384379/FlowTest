"""Missing observations and assisted revisions never inflate first-generation metrics."""

import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.host_quality import (  # noqa: E402
    AssistedRevision,
    QualityAttempt,
    QualityTask,
    QualityTaskSet,
    quality_report,
)
from scripts.selftest.io import HarnessError  # noqa: E402


def tasks():
    return QualityTaskSet(
        version="host-quality-v1",
        tasks=(
            QualityTask(task_id="one", required_oracle_ids=("a", "b"), known_defect=True),
            QualityTask(task_id="two"),
        ),
    )


def test_not_run_has_eight_zero_denominator_not_evaluated_metrics():
    report = quality_report(tasks(), ())
    assert len(report.metrics) == 8 and report.not_run_task_ids == ("one:default", "two:default")
    assert all(
        item.numerator == item.denominator == 0 and item.status == "NOT_EVALUATED"
        for item in report.metrics
    )


def test_all_attempts_remain_and_assisted_success_does_not_replace_first_failure():
    first = QualityAttempt(
        review_mode="ci_fixture",
        task_id="one",
        attempt_id=uuid4(),
        ordinal=1,
        evidence_digest="a" * 64,
        protocol_available=True,
        independent_execution_match=False,
        landed_oracle_ids=("a",),
        fixed_defect_detected=False,
    )
    assisted = first.model_copy(
        update={
            "attempt_id": uuid4(),
            "ordinal": 2,
            "independent_execution_match": True,
            "assisted": AssistedRevision(
                review_mode="ci_fixture",
                before_proposal_id=uuid4(),
                after_proposal_id=uuid4(),
                before_fingerprint="b" * 64,
                after_fingerprint="c" * 64,
                reviewer_id=uuid4(),
                reason_digest="d" * 64,
                independent_execution_match=True,
            ),
        }
    )
    report = quality_report(tasks(), (first, assisted))
    metrics = {item.name: item for item in report.metrics}
    assert (
        metrics["first_generation_execution_match"].numerator,
        metrics["first_generation_execution_match"].denominator,
    ) == (0, 1)
    assert (
        metrics["assisted_execution_match"].numerator,
        metrics["assisted_execution_match"].denominator,
    ) == (1, 1)
    assert (
        metrics["required_oracle_landing"].numerator,
        metrics["required_oracle_landing"].denominator,
    ) == (2, 4)
    assert (
        metrics["design_validity"].status == "INCOMPLETE"
        and metrics["design_validity"].unobserved_count == 1
    )
    assert metrics["design_validity"].denominator == 1
    assert len(report.attempts) == 2 and report.not_run_task_ids == ("two:default",)


def test_missing_first_attempt_or_unselected_task_cannot_reduce_denominator():
    record = QualityAttempt(
        task_id="one",
        attempt_id=uuid4(),
        ordinal=2,
        evidence_digest="a" * 64,
        review_mode="ci_fixture",
    )
    with pytest.raises(HarnessError, match="SEQUENCE_INCOMPLETE"):
        quality_report(tasks(), (record,))
    with pytest.raises(HarnessError, match="UNSELECTED_ATTEMPT"):
        quality_report(tasks(), (record.model_copy(update={"task_id": "outside", "ordinal": 1}),))
