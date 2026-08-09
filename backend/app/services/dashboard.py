from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.access import User
from app.repositories.dashboard import DashboardExecutionRecord, DashboardRepository

DISPLAY_TIME_ZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class DashboardTrendPoint:
    date: date
    total: int
    passed: int
    failed: int
    running: int


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    project_count: int
    api_count: int
    workflow_count: int
    today_total: int
    today_passed: int
    today_failed: int
    pass_rate: float
    trend: list[DashboardTrendPoint]


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self._dashboard = DashboardRepository(session)

    async def summary(self, *, actor: User, project_id: UUID | None) -> DashboardSummary:
        project_ids = await self._scope(actor=actor, project_id=project_id)
        today = datetime.now(DISPLAY_TIME_ZONE).date()
        first_day = today - timedelta(days=6)
        since = datetime.combine(first_day, time.min, tzinfo=DISPLAY_TIME_ZONE).astimezone(UTC)
        counts = await self._dashboard.counts(project_ids)
        activity = await self._dashboard.activity(project_ids=project_ids, since=since)
        grouped: dict[date, list[DashboardExecutionRecord]] = defaultdict(list)
        for execution in activity:
            grouped[_local_date(execution.started_at)].append(execution)
        trend = [_trend_point(first_day + timedelta(days=offset), grouped) for offset in range(7)]
        today_point = trend[-1]
        terminal = today_point.passed + today_point.failed
        pass_rate = round(today_point.passed / terminal * 100, 2) if terminal else 0.0
        return DashboardSummary(
            project_count=counts.projects,
            api_count=counts.apis,
            workflow_count=counts.workflows,
            today_total=today_point.total,
            today_passed=today_point.passed,
            today_failed=today_point.failed,
            pass_rate=pass_rate,
            trend=trend,
        )

    async def recent_executions(
        self,
        *,
        actor: User,
        project_id: UUID | None,
        page: int,
        page_size: int,
    ) -> tuple[list[DashboardExecutionRecord], int]:
        project_ids = await self._scope(actor=actor, project_id=project_id)
        offset = (page - 1) * page_size
        records = await self._dashboard.activity(
            project_ids=project_ids,
            limit=offset + page_size,
        )
        total = await self._dashboard.execution_count(project_ids)
        return records[offset : offset + page_size], total

    async def _scope(self, *, actor: User, project_id: UUID | None) -> list[UUID]:
        accessible = await self._dashboard.accessible_project_ids(
            user_id=actor.id,
            system_admin=actor.is_system_admin,
        )
        if project_id is None:
            return accessible
        if project_id not in accessible:
            raise AppError(code="PROJECT_NOT_FOUND", message="项目不存在", status_code=404)
        return [project_id]


def _local_date(value: datetime) -> date:
    source = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return source.astimezone(DISPLAY_TIME_ZONE).date()


def _trend_point(
    day: date, grouped: dict[date, list[DashboardExecutionRecord]]
) -> DashboardTrendPoint:
    executions = grouped.get(day, [])
    passed = sum(item.status == "passed" for item in executions)
    running = sum(item.status == "running" for item in executions)
    failed = len(executions) - passed - running
    return DashboardTrendPoint(
        date=day,
        total=len(executions),
        passed=passed,
        failed=failed,
        running=running,
    )
