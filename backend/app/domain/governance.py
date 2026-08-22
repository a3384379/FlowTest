"""Pure organization governance and quota contracts."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class QuotaMode(StrEnum):
    OBSERVE = "observe"
    WARN = "warn"
    SOFT_LIMIT = "soft_limit"
    HARD_LIMIT = "hard_limit"


class QuotaDimension(StrEnum):
    PROJECT_COUNT = "project_count"
    USER_COUNT = "user_count"
    RUNNER_CONCURRENCY = "runner_concurrency"
    EXECUTION_CONCURRENCY = "execution_concurrency"
    AI_REQUEST_COUNT = "ai_request_count"
    ARTIFACT_STORAGE = "artifact_storage"


@dataclass(frozen=True, slots=True)
class QuotaRule:
    mode: QuotaMode = QuotaMode.OBSERVE
    limit: int | None = None
    warn_at: int | None = None

    def __post_init__(self) -> None:
        if self.limit is not None and self.limit < 1:
            raise ValueError("Quota limit must be positive")
        if self.warn_at is not None and self.warn_at < 1:
            raise ValueError("Quota warning threshold must be positive")
        if self.limit is not None and self.warn_at is not None and self.warn_at > self.limit:
            raise ValueError("Quota warning threshold cannot exceed the limit")
        if self.mode is not QuotaMode.OBSERVE and self.limit is None:
            raise ValueError("A quota limit is required when enforcement is enabled")

    def evaluate(self, usage: int) -> "QuotaDecision":
        if usage < 0:
            raise ValueError("Quota usage cannot be negative")
        threshold_reached = self.warn_at is not None and usage >= self.warn_at
        limit_reached = self.limit is not None and usage > self.limit
        return QuotaDecision(
            dimension="",
            mode=self.mode,
            usage=usage,
            limit=self.limit,
            warning=self.mode is not QuotaMode.OBSERVE and (threshold_reached or limit_reached),
            blocked=self.mode is QuotaMode.HARD_LIMIT and bool(limit_reached),
        )


@dataclass(frozen=True, slots=True)
class QuotaDecision:
    dimension: str
    mode: QuotaMode
    usage: int
    limit: int | None
    warning: bool
    blocked: bool


DEFAULT_QUOTA_POLICIES: Final[dict[str, dict[str, int | str | None]]] = {
    dimension.value: {"mode": QuotaMode.OBSERVE.value, "limit": None, "warn_at": None}
    for dimension in QuotaDimension
}


def parse_quota_policies(value: object) -> dict[str, QuotaRule]:
    """Parse persisted JSON while keeping unknown dimensions out of the contract."""

    raw = value if isinstance(value, dict) else {}
    policies: dict[str, QuotaRule] = {}
    for dimension in QuotaDimension:
        candidate = raw.get(dimension.value)
        if not isinstance(candidate, dict):
            policies[dimension.value] = QuotaRule()
            continue
        try:
            mode = QuotaMode(str(candidate.get("mode", QuotaMode.OBSERVE.value)))
            limit = _optional_int(candidate.get("limit"))
            warn_at = _optional_int(candidate.get("warn_at"))
            policies[dimension.value] = QuotaRule(mode=mode, limit=limit, warn_at=warn_at)
        except (TypeError, ValueError):
            policies[dimension.value] = QuotaRule()
    return policies


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Quota values must be integers")
    return value
