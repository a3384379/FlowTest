from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterBadCronError, CroniterBadDateError, croniter


class ScheduleValidationError(ValueError):
    """Raised when a scheduled plan cannot produce a safe next run time."""


@dataclass(frozen=True, slots=True)
class QualityMetrics:
    total: int
    passed: int
    failed: int
    quarantined: int
    flaky: int
    pass_rate: float
    duration_seconds: float
    baseline_duration_seconds: float | None
    duration_regression_percent: float | None
    breaking_changes: int


@dataclass(frozen=True, slots=True)
class QualityPolicy:
    min_pass_rate: float = 100.0
    max_failed: int = 0
    max_flaky: int = 0
    max_duration_regression_percent: float = 20.0
    require_no_breaking_changes: bool = True


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    violations: tuple[str, ...]


def next_scheduled_at(
    now: datetime,
    *,
    enabled: bool,
    interval_seconds: int | None,
    cron_expression: str | None,
    timezone_name: str,
) -> datetime | None:
    if not enabled:
        return None
    if interval_seconds is not None and cron_expression is not None:
        raise ScheduleValidationError("interval and cron schedule cannot be combined")
    if interval_seconds is not None:
        if interval_seconds < 60:
            raise ScheduleValidationError("schedule interval must be at least 60 seconds")
        return datetime.fromtimestamp(now.astimezone(UTC).timestamp() + interval_seconds, tz=UTC)
    if cron_expression is None:
        return None
    fields = cron_expression.strip().split()
    if len(fields) != 5:
        raise ScheduleValidationError("cron schedule must contain exactly five fields")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise ScheduleValidationError("unknown schedule timezone") from error
    localized_now = now.astimezone(timezone)
    try:
        following = croniter(cron_expression, localized_now).get_next(datetime)
    except (CroniterBadCronError, CroniterBadDateError, ValueError) as error:
        raise ScheduleValidationError("invalid cron schedule") from error
    following_utc = following.astimezone(UTC)
    if (following_utc - now.astimezone(UTC)).total_seconds() < 60:
        raise ScheduleValidationError("cron schedule must not run more than once per minute")
    return following_utc


def flaky_score(*, total_runs: int, passed_runs: int, failed_runs: int, transitions: int) -> float:
    if total_runs < 2 or passed_runs == 0 or failed_runs == 0:
        return 0.0
    transition_ratio = transitions / (total_runs - 1)
    balance_ratio = min(passed_runs, failed_runs) / max(passed_runs, failed_runs)
    return round((transition_ratio * 0.7 + balance_ratio * 0.3) * 100, 2)


def duration_regression(current_seconds: float, baseline_seconds: float | None) -> float | None:
    if baseline_seconds is None or baseline_seconds <= 0:
        return None
    return round(((current_seconds - baseline_seconds) / baseline_seconds) * 100, 2)


def evaluate_gate(policy: QualityPolicy, metrics: QualityMetrics) -> GateResult:
    violations: list[str] = []
    if metrics.pass_rate < policy.min_pass_rate:
        violations.append(f"通过率 {metrics.pass_rate:.2f}% 低于门槛 {policy.min_pass_rate:.2f}%")
    if metrics.failed > policy.max_failed:
        violations.append(f"失败数 {metrics.failed} 超过上限 {policy.max_failed}")
    if metrics.flaky > policy.max_flaky:
        violations.append(f"Flaky 数 {metrics.flaky} 超过上限 {policy.max_flaky}")
    if (
        metrics.duration_regression_percent is not None
        and metrics.duration_regression_percent > policy.max_duration_regression_percent
    ):
        violations.append(
            f"耗时回归 {metrics.duration_regression_percent:.2f}% 超过上限 "
            f"{policy.max_duration_regression_percent:.2f}%"
        )
    if policy.require_no_breaking_changes and metrics.breaking_changes > 0:
        violations.append(f"存在 {metrics.breaking_changes} 项破坏性契约变更")
    return GateResult(passed=not violations, violations=tuple(violations))
