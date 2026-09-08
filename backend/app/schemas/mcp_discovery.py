"""Typed, bounded contracts for MCP resource discovery and readiness checks."""

from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MCPAssetType = Literal[
    "api",
    "workflow",
    "context",
    "proposal",
    "test_asset",
    "test_case",
    "test_suite",
    "test_plan",
    "import_run",
    "execution",
    "change_regression_run",
]


class MCPFindAssetsRequest(BaseModel):
    """A deliberately small query surface; SQL/repository details never cross MCP."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    asset_types: list[MCPAssetType] = Field(
        default_factory=lambda: cast(
            list[MCPAssetType], ["api", "workflow", "context", "proposal"]
        ),
        min_length=1,
        max_length=5,
    )
    query: str = Field(default="", max_length=160)
    method: str | None = Field(default=None, min_length=3, max_length=16)
    path: str | None = Field(default=None, min_length=1, max_length=2048)
    source: str | None = Field(default=None, min_length=1, max_length=512)
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=20, ge=1, le=50)

    @field_validator("query", "method", "path", "source")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("asset_types")
    @classmethod
    def reject_duplicate_types(cls, value: list[MCPAssetType]) -> list[MCPAssetType]:
        if len(set(value)) != len(value):
            raise ValueError("资源类型不能重复")
        return value


class MCPAssetSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_type: MCPAssetType
    id: UUID
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=400)
    version: int | None = Field(default=None, ge=1)
    status: str = Field(min_length=1, max_length=32)
    source_ref: str | None = Field(default=None, max_length=512)
    updated_at: datetime
    deep_link: str = Field(min_length=1, max_length=1024)


class MCPFindAssetsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["flowtest-mcp-asset-discovery-v1"] = "flowtest-mcp-asset-discovery-v1"
    project_id: UUID
    items: list[MCPAssetSummary] = Field(max_length=50)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=50)
    has_more: bool
    next_page: int | None = Field(default=None, ge=1)


ReadinessState = Literal[
    "ready",
    "missing",
    "degraded",
    "not_configured",
    "not_authorized",
    "not_verified",
]


class MCPReadinessCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=80)
    state: ReadinessState
    detail: str = Field(default="", max_length=400)
    action: str | None = Field(default=None, max_length=400)


class MCPProjectReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["flowtest-mcp-project-readiness-v1"] = (
        "flowtest-mcp-project-readiness-v1"
    )
    project_id: UUID
    can_generate_proposal: bool
    can_request_preview: bool
    checks: list[MCPReadinessCheck] = Field(max_length=30)
    human_actions_required: list[str] = Field(default_factory=list, max_length=30)
    review_url: str | None = Field(default=None, max_length=1024)
    credential_setup_url: str | None = Field(default=None, max_length=1024)
    next_action: str = Field(min_length=1, max_length=400)


class MCPServiceTargetCheckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["flowtest-mcp-service-target-check-v1"] = (
        "flowtest-mcp-service-target-check-v1"
    )
    project_id: UUID
    endpoint_id: UUID
    variant: str = Field(min_length=1, max_length=80)
    base_origin: str = Field(min_length=1, max_length=512)
    execution_origin: Literal["flowtest_api_host", "worker", "runner_unknown"]
    worker_network_verified: bool = False
    status: str = Field(min_length=1, max_length=32)
    dns: str = Field(default="", max_length=1024)
    http_status: int | None = Field(default=None, ge=100, le=599)
    latency_ms: float | None = Field(default=None, ge=0)
    redirect: bool = False
    error_code: str | None = Field(default=None, max_length=100)
    human_actions_required: list[str] = Field(default_factory=list, max_length=10)
    next_action: str = Field(min_length=1, max_length=400)
