from typing import Literal

from pydantic import BaseModel

from app.domain.runtime_profiles import RuntimeFeature, RuntimeProfile, WorkerTopology


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, Literal["ok", "error"]]


class RuntimeProfileResponse(BaseModel):
    profile: RuntimeProfile
    worker_topology: WorkerTopology
    unavailable_features: tuple[RuntimeFeature, ...]


class FeatureFlagsResponse(BaseModel):
    teams: bool
    test_assets: bool
    advanced_workflows: bool
    data_nodes: bool
    contract_testing: bool
    quality_center: bool
    oidc: bool
    ai: bool
    multi_protocol: bool
    event_protocols: bool
    performance_lab: bool
