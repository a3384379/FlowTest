from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class DashboardTrendPointResponse(BaseModel):
    date: date
    total: int
    passed: int
    failed: int
    running: int


class DashboardSummaryResponse(BaseModel):
    project_count: int
    api_count: int
    workflow_count: int
    today_total: int
    today_passed: int
    today_failed: int
    pass_rate: float
    trend: list[DashboardTrendPointResponse]


class RecentExecutionResponse(BaseModel):
    id: UUID
    project_id: UUID
    project_name: str
    kind: Literal["api", "workflow"]
    target_id: UUID
    target_name: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    duration_ms: float | None
