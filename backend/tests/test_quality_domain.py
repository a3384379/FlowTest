from datetime import UTC, datetime
from xml.etree import ElementTree

import pytest

from app.domain.junit import JUnitCase, build_junit_xml
from app.domain.quality import (
    QualityMetrics,
    QualityPolicy,
    ScheduleValidationError,
    duration_regression,
    evaluate_gate,
    flaky_score,
    next_scheduled_at,
)


def test_cron_timezone_interval_and_schedule_validation() -> None:
    now = datetime(2026, 8, 11, 0, 0, 30, tzinfo=UTC)
    assert next_scheduled_at(
        now,
        enabled=True,
        interval_seconds=60,
        cron_expression=None,
        timezone_name="Asia/Shanghai",
    ) == datetime(2026, 8, 11, 0, 1, 30, tzinfo=UTC)
    assert next_scheduled_at(
        now,
        enabled=True,
        interval_seconds=None,
        cron_expression="0 9 * * 1-5",
        timezone_name="Asia/Shanghai",
    ) == datetime(2026, 8, 11, 1, 0, tzinfo=UTC)
    assert (
        next_scheduled_at(
            now,
            enabled=False,
            interval_seconds=60,
            cron_expression=None,
            timezone_name="Asia/Shanghai",
        )
        is None
    )
    for interval, cron, timezone in (
        (60, "* * * * *", "UTC"),
        (30, None, "UTC"),
        (None, "* * * *", "UTC"),
        (None, "invalid * * * *", "UTC"),
        (None, "* * * * *", "Mars/Base"),
    ):
        with pytest.raises(ScheduleValidationError):
            next_scheduled_at(
                now,
                enabled=True,
                interval_seconds=interval,
                cron_expression=cron,
                timezone_name=timezone,
            )


def test_flaky_scoring_duration_and_quality_gate_are_deterministic() -> None:
    assert flaky_score(total_runs=1, passed_runs=1, failed_runs=0, transitions=0) == 0
    assert flaky_score(total_runs=2, passed_runs=1, failed_runs=1, transitions=1) == 100
    assert flaky_score(total_runs=4, passed_runs=2, failed_runs=2, transitions=1) == 53.33
    assert duration_regression(12, None) is None
    assert duration_regression(12, 0) is None
    assert duration_regression(12, 10) == 20

    result = evaluate_gate(
        QualityPolicy(
            min_pass_rate=95,
            max_failed=0,
            max_flaky=0,
            max_duration_regression_percent=10,
            require_no_breaking_changes=True,
        ),
        QualityMetrics(
            total=10,
            passed=8,
            failed=2,
            quarantined=1,
            flaky=1,
            pass_rate=80,
            duration_seconds=12,
            baseline_duration_seconds=10,
            duration_regression_percent=20,
            breaking_changes=1,
        ),
    )
    assert not result.passed
    assert len(result.violations) == 5


def test_junit_builder_escapes_untrusted_names_and_marks_results() -> None:
    document = build_junit_xml(
        suite_name='suite <&"',
        cases=(
            JUnitCase("passed", "FlowTest", 0.1, "passed"),
            JUnitCase("failed <case>", "FlowTest", 0.2, "failed", "safe <message>"),
            JUnitCase("quarantined", "FlowTest", 0, "quarantined"),
        ),
    )
    root = ElementTree.fromstring(document)
    assert root.attrib == {
        "name": 'suite <&"',
        "tests": "3",
        "failures": "1",
        "errors": "0",
        "skipped": "1",
        "time": "0.300",
    }
    testcases = root.findall("testcase")
    assert testcases[0].find("failure") is None
    failure = testcases[1].find("failure")
    assert failure is not None and failure.text == "safe <message>"
    assert testcases[2].find("skipped") is not None
