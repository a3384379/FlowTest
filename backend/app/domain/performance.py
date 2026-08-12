import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

_SENSITIVE_NAME = re.compile(
    r"(^|[_\-.])(password|passwd|authorization|cookie|token|secret|api[_-]?key|"
    r"access[_-]?key|private[_-]?key|client[_-]?secret)($|[_\-.])",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"
)


class LoadExecutor(StrEnum):
    CONSTANT_VUS = "constant_vus"
    RAMPING_VUS = "ramping_vus"


class ThresholdOperator(StrEnum):
    LESS_THAN = "<"
    LESS_THAN_OR_EQUAL = "<="
    GREATER_THAN = ">"
    GREATER_THAN_OR_EQUAL = ">="


class PerformanceStage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    duration_seconds: int = Field(ge=1, le=3600)
    target_vus: int = Field(ge=0, le=1000)


class PerformanceHttpStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=120)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET"
    url: str = Field(min_length=1, max_length=2048)
    headers: dict[str, str] = Field(default_factory=dict)
    body: JsonValue | None = None
    expected_statuses: tuple[int, ...] = Field(default=(200,), min_length=1, max_length=20)
    pause_seconds: float = Field(default=0, ge=0, le=60)

    @model_validator(mode="after")
    def validate_step(self) -> "PerformanceHttpStep":
        normalized_headers: dict[str, str] = {}
        for name, value in self.headers.items():
            header_name = name.strip()
            if (
                not header_name
                or len(header_name) > 128
                or "\n" in header_name
                or "\r" in header_name
            ):
                raise ValueError("HTTP header name is invalid")
            if len(value) > 8192 or "\n" in value or "\r" in value:
                raise ValueError("HTTP header value is invalid")
            if _is_sensitive_name(header_name) or _SECRET_VALUE.search(value):
                raise ValueError(
                    "Sensitive HTTP headers are not supported by performance scenarios"
                )
            normalized_headers[header_name] = value
        statuses = tuple(sorted(set(self.expected_statuses)))
        if any(status < 100 or status > 599 for status in statuses):
            raise ValueError("Expected HTTP status must be between 100 and 599")
        if any(_is_sensitive_name(name) for name, _ in parse_qsl(urlsplit(self.url).query)):
            raise ValueError("Sensitive URL query parameters are not supported")
        if _contains_sensitive_body(self.body):
            raise ValueError("Sensitive request body fields are not supported")
        object.__setattr__(self, "headers", normalized_headers)
        object.__setattr__(self, "expected_statuses", statuses)
        return self


MetricName = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9_]*(?:\{[a-zA-Z0-9_=,:.-]+\})?$", max_length=160),
]
Aggregation = Annotated[
    str,
    Field(pattern=r"^(?:avg|med|min|max|rate|count|p\((?:[1-9]\d?|100)(?:\.\d+)?\))$"),
]


class PerformanceThreshold(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: MetricName
    aggregation: Aggregation
    operator: ThresholdOperator
    value: float = Field(ge=0, le=1_000_000_000)
    abort_on_fail: bool = False
    delay_abort_seconds: int = Field(default=0, ge=0, le=3600)

    @model_validator(mode="after")
    def validate_abort_delay(self) -> "PerformanceThreshold":
        if not self.abort_on_fail and self.delay_abort_seconds:
            raise ValueError("Threshold abort delay requires abort_on_fail")
        return self

    @property
    def expression(self) -> str:
        value = format(self.value, ".15g")
        return f"{self.aggregation}{self.operator.value}{value}"


class PerformanceScenarioDefinition(BaseModel):
    """Declarative load definition. It deliberately contains no executable source text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    executor: LoadExecutor
    steps: tuple[PerformanceHttpStep, ...] = Field(min_length=1, max_length=20)
    thresholds: tuple[PerformanceThreshold, ...] = Field(min_length=1, max_length=30)
    vus: int | None = Field(default=None, ge=1, le=1000)
    duration_seconds: int | None = Field(default=None, ge=1, le=3600)
    start_vus: int | None = Field(default=None, ge=0, le=1000)
    stages: tuple[PerformanceStage, ...] = Field(default=(), max_length=20)
    graceful_stop_seconds: int = Field(default=30, ge=0, le=300)

    @model_validator(mode="after")
    def validate_executor_configuration(self) -> "PerformanceScenarioDefinition":
        if self.executor is LoadExecutor.CONSTANT_VUS:
            if self.vus is None or self.duration_seconds is None:
                raise ValueError("constant_vus requires vus and duration_seconds")
            if self.start_vus is not None or self.stages:
                raise ValueError("constant_vus cannot declare start_vus or stages")
        else:
            if self.start_vus is None or not self.stages:
                raise ValueError("ramping_vus requires start_vus and stages")
            if self.vus is not None or self.duration_seconds is not None:
                raise ValueError("ramping_vus cannot declare vus or duration_seconds")
        if self.total_duration_seconds > 3600:
            raise ValueError("Performance scenario duration cannot exceed 3600 seconds")
        threshold_keys = [(item.metric, item.expression) for item in self.thresholds]
        if len(threshold_keys) != len(set(threshold_keys)):
            raise ValueError("Performance thresholds must be unique")
        step_names = [step.name for step in self.steps]
        if len(step_names) != len(set(step_names)):
            raise ValueError("Performance step names must be unique")
        return self

    @property
    def total_duration_seconds(self) -> int:
        if self.executor is LoadExecutor.CONSTANT_VUS:
            return self.duration_seconds or 0
        return sum(stage.duration_seconds for stage in self.stages)

    @property
    def maximum_vus(self) -> int:
        if self.executor is LoadExecutor.CONSTANT_VUS:
            return self.vus or 0
        return max((self.start_vus or 0), *(stage.target_vus for stage in self.stages))

    @property
    def target_type(self) -> str:
        return "rest" if len(self.steps) == 1 else "http_workflow"


class ThresholdOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: str
    expression: str
    passed: bool


@dataclass(frozen=True, slots=True)
class PerformanceExecutionResult:
    exit_code: int
    summary: dict[str, object]
    raw_metrics: bytes
    stderr: str


def threshold_outcomes(summary: dict[str, object]) -> tuple[ThresholdOutcome, ...]:
    metrics = summary.get("metrics")
    if not isinstance(metrics, dict):
        return ()
    outcomes: list[ThresholdOutcome] = []
    for metric_name, metric_payload in metrics.items():
        if not isinstance(metric_name, str) or not isinstance(metric_payload, dict):
            continue
        thresholds = metric_payload.get("thresholds")
        if not isinstance(thresholds, dict):
            continue
        outcomes.extend(_metric_thresholds(metric_name, thresholds))
    return tuple(outcomes)


def _metric_thresholds(
    metric_name: str, thresholds: dict[object, object]
) -> list[ThresholdOutcome]:
    outcomes: list[ThresholdOutcome] = []
    for expression, result in thresholds.items():
        if not isinstance(expression, str) or not isinstance(result, dict):
            continue
        passed = result.get("ok")
        if isinstance(passed, bool):
            outcomes.append(
                ThresholdOutcome(metric=metric_name, expression=expression, passed=passed)
            )
    return outcomes


def metric_value(summary: dict[str, object], metric: str, aggregation: str) -> float | None:
    metrics = summary.get("metrics")
    if not isinstance(metrics, dict):
        return None
    payload = metrics.get(metric)
    if not isinstance(payload, dict):
        return None
    values = payload.get("values")
    if not isinstance(values, dict):
        return None
    value = values.get(aggregation)
    return float(value) if isinstance(value, int | float) else None


def validate_metric_name(value: str) -> bool:
    return re.fullmatch(r"[a-z][a-z0-9_]*(?:\{[a-zA-Z0-9_=,:.-]+\})?", value) is not None


def _contains_sensitive_body(value: JsonValue | None) -> bool:
    if isinstance(value, dict):
        return any(
            _is_sensitive_name(str(name)) or _contains_sensitive_body(item)
            for name, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_body(item) for item in value)
    return isinstance(value, str) and _SECRET_VALUE.search(value) is not None


def _is_sensitive_name(value: str) -> bool:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value).lower()
    return _SENSITIVE_NAME.search(f"_{normalized}_") is not None
