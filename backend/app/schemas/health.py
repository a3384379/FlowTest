from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, Literal["ok", "error"]]


class FeatureFlagsResponse(BaseModel):
    teams: bool
    test_assets: bool
    advanced_workflows: bool
    data_nodes: bool
    contract_testing: bool
    quality_center: bool
    oidc: bool
    ai: bool
