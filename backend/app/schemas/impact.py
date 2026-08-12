from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

SourceKindValue = Literal["git", "openapi", "graphql", "grpc"]
TargetTypeValue = Literal[
    "test_case",
    "workflow",
    "openapi_contract",
    "pact_contract",
    "performance",
]


class ImpactMappingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: SourceKindValue
    source_selector: str = Field(min_length=1, max_length=512)
    target_type: TargetTypeValue
    target_id: UUID


class ImpactMappingResponse(BaseModel):
    id: UUID
    project_id: UUID
    source_kind: SourceKindValue
    source_selector: str
    target_type: TargetTypeValue
    target_id: UUID
    target_name: str
    target_version: str | int | None
    created_by_id: UUID
    created_at: datetime


class OpenApiDiffReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_run_id: UUID
    current_run_id: UUID


class SchemaDiffReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_artifact_id: UUID
    current_artifact_id: UUID


class ImpactRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    source_ref: str = Field(default="", max_length=200)
    git_diff: str | None = Field(default=None, max_length=2 * 1024 * 1024)
    openapi_diffs: list[OpenApiDiffReference] = Field(default_factory=list, max_length=20)
    schema_diffs: list[SchemaDiffReference] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def require_change_source(self) -> "ImpactRunCreate":
        if not self.git_diff and not self.openapi_diffs and not self.schema_diffs:
            raise ValueError("至少提供一种 Git 或 Schema 变更来源")
        return self


class ImpactRunSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    source_ref: str
    status: Literal["completed", "failed"]
    source_fingerprint: str
    source_summary: dict[str, JsonValue]
    change_count: int
    summary: dict[str, JsonValue]
    created_by_id: UUID
    created_at: datetime


class TestSelectionResponse(BaseModel):
    id: UUID
    strategy: str
    selected_assets: list[dict[str, JsonValue]]
    explanations: list[dict[str, JsonValue]]
    created_at: datetime


class CoverageSnapshotResponse(BaseModel):
    id: UUID
    total_changes: int
    covered_changes: int
    coverage_percent: float
    matrix: list[dict[str, JsonValue]]
    gaps: list[dict[str, JsonValue]]
    created_at: datetime


class ImpactRunDetailResponse(ImpactRunSummaryResponse):
    changes: list[dict[str, JsonValue]]
    graph: dict[str, JsonValue]
    selection: TestSelectionResponse
    coverage: CoverageSnapshotResponse


class ImpactCatalogItem(BaseModel):
    id: UUID
    target_type: TargetTypeValue
    name: str
    version: str | int | None


class ImpactSchemaCatalogItem(BaseModel):
    id: UUID
    protocol: Literal["graphql", "grpc"]
    name: str
    version: int


class ImpactCatalogResponse(BaseModel):
    targets: list[ImpactCatalogItem]
    schemas: list[ImpactSchemaCatalogItem]
