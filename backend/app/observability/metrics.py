import re
from collections import Counter, defaultdict
from threading import Lock

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.executions import APICallExecution
from app.models.tasking import TestPlanRun
from app.models.workflows import WorkflowExecution

HISTOGRAM_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
UUID_PATH_SEGMENT = re.compile(
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)"
)


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._request_counts: Counter[tuple[str, str, int]] = Counter()
        self._duration_counts: Counter[tuple[str, str]] = Counter()
        self._duration_sums: defaultdict[tuple[str, str], float] = defaultdict(float)
        self._duration_buckets: Counter[tuple[str, str, float]] = Counter()

    def observe_request(self, *, method: str, path: str, status: int, duration: float) -> None:
        route = normalize_path(path)
        key = (method.upper(), route)
        with self._lock:
            self._request_counts[(*key, status)] += 1
            self._duration_counts[key] += 1
            self._duration_sums[key] += duration
            for bucket in HISTOGRAM_BUCKETS:
                if duration <= bucket:
                    self._duration_buckets[(*key, bucket)] += 1

    def render_http(self) -> list[str]:
        with self._lock:
            request_counts = dict(self._request_counts)
            duration_counts = dict(self._duration_counts)
            duration_sums = dict(self._duration_sums)
            duration_buckets = dict(self._duration_buckets)
        lines = [
            "# HELP flowtest_info FlowTest build information.",
            "# TYPE flowtest_info gauge",
            f'flowtest_info{{version="{_escape(settings.app_version)}"}} 1',
            "# HELP flowtest_http_requests_total HTTP requests handled by the API.",
            "# TYPE flowtest_http_requests_total counter",
        ]
        for (method, path, status), count in sorted(request_counts.items()):
            labels = _labels(method=method, path=path, status=str(status))
            lines.append(f"flowtest_http_requests_total{{{labels}}} {count}")
        lines.extend(
            [
                "# HELP flowtest_http_request_duration_seconds HTTP request latency.",
                "# TYPE flowtest_http_request_duration_seconds histogram",
            ]
        )
        for method, path in sorted(duration_counts):
            count = duration_counts[(method, path)]
            for bucket in HISTOGRAM_BUCKETS:
                labels = _labels(method=method, path=path, le=_number(bucket))
                bucket_count = duration_buckets.get((method, path, bucket), 0)
                lines.append(
                    f"flowtest_http_request_duration_seconds_bucket{{{labels}}} {bucket_count}"
                )
            labels = _labels(method=method, path=path, le="+Inf")
            lines.append(f"flowtest_http_request_duration_seconds_bucket{{{labels}}} {count}")
            base_labels = _labels(method=method, path=path)
            lines.append(
                "flowtest_http_request_duration_seconds_sum"
                f"{{{base_labels}}} {duration_sums[(method, path)]:.9f}"
            )
            lines.append(f"flowtest_http_request_duration_seconds_count{{{base_labels}}} {count}")
        return lines


async def render_metrics(registry: MetricsRegistry, session: AsyncSession) -> str:
    lines = registry.render_http()
    lines.extend(
        [
            "# HELP flowtest_execution_records "
            "Current persisted execution records by kind and status.",
            "# TYPE flowtest_execution_records gauge",
        ]
    )
    try:
        for kind, status_column in (
            ("api", APICallExecution.status),
            ("workflow", WorkflowExecution.status),
            ("test_plan", TestPlanRun.status),
        ):
            rows = (
                await session.execute(select(status_column, func.count()).group_by(status_column))
            ).all()
            for status, count in sorted(rows):
                labels = _labels(kind=kind, status=str(status))
                lines.append(f"flowtest_execution_records{{{labels}}} {int(count)}")
    except (OSError, SQLAlchemyError):
        lines.extend(
            [
                "# HELP flowtest_execution_metrics_available Execution store metrics availability.",
                "# TYPE flowtest_execution_metrics_available gauge",
                "flowtest_execution_metrics_available 0",
            ]
        )
    else:
        lines.extend(
            [
                "# HELP flowtest_execution_metrics_available Execution store metrics availability.",
                "# TYPE flowtest_execution_metrics_available gauge",
                "flowtest_execution_metrics_available 1",
            ]
        )
    return "\n".join(lines) + "\n"


def normalize_path(path: str) -> str:
    normalized = UUID_PATH_SEGMENT.sub("/{id}", path)
    return normalized if len(normalized) <= 240 else normalized[:240]


def _labels(**values: str) -> str:
    return ",".join(f'{key}="{_escape(value)}"' for key, value in sorted(values.items()))


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)
