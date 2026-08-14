from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

SearchResourceType = Literal[
    "project",
    "api",
    "workflow",
    "test_case",
    "test_suite",
    "test_plan",
    "environment",
    "mock_service",
    "performance_scenario",
    "contract_service",
    "impact_run",
    "quality_gate",
    "release_risk",
    "release_policy",
]


class SearchResultResponse(BaseModel):
    resource_type: SearchResourceType
    resource_id: UUID
    project_id: UUID
    project_name: str
    title: str
    description: str
    section: str
    path: str
    updated_at: datetime
