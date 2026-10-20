from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal
from uuid import UUID

ReportStatus = Literal["queued", "running", "passed", "failed", "cancelled"]
ReportSource = Literal["workflow", "case", "plan", "preview"]
ReportFilterKind = Literal["workflow", "environment", "case", "plan"]


@dataclass(frozen=True, slots=True)
class ReportFilterOption:
    id: UUID
    name: str


class InvalidReportScope(ValueError):
    """A reporting window or source violates the query policy."""


@dataclass(frozen=True, slots=True)
class ReportScope:
    status: ReportStatus | None = None
    started_from: datetime | None = None
    started_until: datetime | None = None
    workflow_id: UUID | None = None
    environment_id: UUID | None = None
    source_case_id: UUID | None = None
    source_plan_id: UUID | None = None
    source: ReportSource | None = None

    def normalized(self) -> "ReportScope":
        if self.status is not None and self.status not in {
            "queued",
            "running",
            "passed",
            "failed",
            "cancelled",
        }:
            raise InvalidReportScope("报告状态不存在")
        if self.source is not None and self.source not in {"workflow", "case", "plan", "preview"}:
            raise InvalidReportScope("报告来源不存在")
        self._validate_period()
        return replace(
            self,
            started_from=self.started_from.astimezone(UTC)
            if self.started_from is not None
            else None,
            started_until=self.started_until.astimezone(UTC)
            if self.started_until is not None
            else None,
        )

    def _validate_period(self) -> None:
        if (self.started_from is None) != (self.started_until is None):
            raise InvalidReportScope("开始与结束时间必须同时提供")
        if self.started_from is None or self.started_until is None:
            return
        if self.started_from.utcoffset() is None or self.started_until.utcoffset() is None:
            raise InvalidReportScope("报告时间必须携带时区")
        delta = self.started_until - self.started_from
        if delta <= timedelta(0) or delta > timedelta(days=90):
            raise InvalidReportScope("报告时间范围必须大于零且不超过 90 天")

    def trend_window(self, days: int, now: datetime) -> tuple[datetime, datetime]:
        if not 1 <= days <= 90:
            raise InvalidReportScope("趋势窗口必须为 1 至 90 天")
        if self.started_from is not None and self.started_until is not None:
            return self.started_from, self.started_until
        until = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            days=1
        )
        return until - timedelta(days=days), until


@dataclass(frozen=True, slots=True)
class ReportTrendRecord:
    status: str
    error_code: str | None
    started_at: datetime
    completed_at: datetime | None


class FailureCategory(StrEnum):
    ASSERTION = "assertion"
    TIMEOUT = "timeout"
    NETWORK = "network"
    HTTP_CLIENT = "http_client"
    HTTP_SERVER = "http_server"
    CONFIGURATION = "configuration"
    CANCELLED = "cancelled"
    RUNTIME = "runtime"
    NONE = "none"


class NotificationEvent(StrEnum):
    WORKFLOW_COMPLETED = "workflow.completed"
    TEST_PLAN_COMPLETED = "test_plan.completed"


def classify_failure(*, status: str, error_code: str | None) -> FailureCategory:
    if status in {"passed", "queued", "running"}:
        return FailureCategory.NONE
    if status == "cancelled":
        return FailureCategory.CANCELLED
    normalized = (error_code or "").upper()
    if "ASSERT" in normalized:
        return FailureCategory.ASSERTION
    if "TIMEOUT" in normalized:
        return FailureCategory.TIMEOUT
    if "NETWORK" in normalized or "DNS" in normalized:
        return FailureCategory.NETWORK
    if "4XX" in normalized:
        return FailureCategory.HTTP_CLIENT
    if "5XX" in normalized:
        return FailureCategory.HTTP_SERVER
    if any(
        marker in normalized
        for marker in ("INVALID", "UNSUPPORTED", "MAPPING", "EXTRACT", "NOT_FOUND")
    ):
        return FailureCategory.CONFIGURATION
    return FailureCategory.RUNTIME
