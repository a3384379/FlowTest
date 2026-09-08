"""Typed MCP contracts for S62 analysis preparation and plan suggestions."""

# Chinese product copy intentionally uses full-width punctuation.

from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.impact import OpenApiDiffReference, SchemaDiffReference

MCP_PLANNING_SCHEMA_VERSION: Literal["flowtest-mcp-planning-v1"] = "flowtest-mcp-planning-v1"
MCP_TEST_PLAN_TARGET_LIMIT: Final[int] = 100


class MCPTestPlanUpdateTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_type: Literal["workflow", "case", "suite"]
    target_id: UUID
    target_version: int | None = Field(default=None, ge=1)
    workflow_version: int | None = Field(default=None, ge=1)
    environment_id: UUID | None = None
    max_retries: int = Field(default=0, ge=0, le=3)
    runtime_variables: dict[str, str] = Field(default_factory=dict)
    runtime_headers: dict[str, str] = Field(default_factory=dict)


class MCPTestPlanUpdateContent(BaseModel):
    """Reviewable content stored in an AIChangeItem, never a second proposal table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["s62-test-plan-update-v1"] = "s62-test-plan-update-v1"
    test_plan_id: UUID
    targets: list[MCPTestPlanUpdateTarget] = Field(
        min_length=1, max_length=MCP_TEST_PLAN_TARGET_LIMIT
    )
    unpublished_dependencies: list[str] = Field(default_factory=list, max_length=100)
    rationale: str = Field(default="", max_length=2000)


class MCPPrepareChangeRegressionRequest(BaseModel):
    """Create or preview one analysis run bound to two fixed Context revisions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    title: str = Field(min_length=1, max_length=200)
    source_ref: str = Field(default="", max_length=200)
    candidate_ref: str = Field(min_length=1, max_length=200)
    git_diff: str | None = Field(default=None, max_length=2 * 1024 * 1024)
    openapi_diffs: list[OpenApiDiffReference] = Field(default_factory=list, max_length=20)
    schema_diffs: list[SchemaDiffReference] = Field(default_factory=list, max_length=20)
    test_plan_id: UUID
    release_policy_id: UUID
    release_risk_id: UUID | None = None
    deployment_check_id: UUID | None = None
    context_id: UUID
    before_revision: int = Field(ge=1)
    after_revision: int = Field(ge=1)
    generate_missing_tests: bool = True
    dry_run: bool = True

    @model_validator(mode="after")
    def validate_sources_and_revisions(self) -> "MCPPrepareChangeRegressionRequest":
        if not self.git_diff and not self.openapi_diffs and not self.schema_diffs:
            raise ValueError("至少提供一种 Git 或 Schema 变更来源")
        if self.before_revision >= self.after_revision:
            raise ValueError("必须选择向前推进的两个上下文版本")
        return self


class MCPPrepareChangeRegressionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["flowtest-mcp-planning-v1"] = MCP_PLANNING_SCHEMA_VERSION
    project_id: UUID
    run_id: UUID | None = None
    impact_run_id: UUID | None = None
    context_diff_ref: str | None = None
    knowledge_diff_ref: str | None = None
    analysis_complete: bool | None = None
    dry_run: bool
    requires_human_review: Literal[True] = True
    automatic_execute: Literal[False] = False
    automatic_release: Literal[False] = False
    idempotency_replayed: bool = False
    next_action: str = Field(min_length=1, max_length=400)
    trace_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def require_run_for_persisted_result(self) -> "MCPPrepareChangeRegressionResponse":
        if self.dry_run and self.run_id is not None:
            raise ValueError("dry-run 不能返回已创建的分析 Run")
        if not self.dry_run and self.run_id is None:
            raise ValueError("已持久化的分析结果必须包含 run_id")
        return self


class MCPTestPlanUpdateRequest(BaseModel):
    """Suggest existing, versioned assets for a Plan without mutating the Plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    test_plan_id: UUID
    run_id: UUID | None = None
    workflow_ids: list[UUID] = Field(default_factory=list, max_length=MCP_TEST_PLAN_TARGET_LIMIT)
    test_case_ids: list[UUID] = Field(default_factory=list, max_length=MCP_TEST_PLAN_TARGET_LIMIT)
    test_suite_ids: list[UUID] = Field(default_factory=list, max_length=MCP_TEST_PLAN_TARGET_LIMIT)
    title: str = Field(default="Test Plan 更新建议", min_length=1, max_length=200)
    rationale: str = Field(default="", max_length=2000)
    dry_run: bool = True

    @model_validator(mode="after")
    def require_targets_and_unique_ids(self) -> "MCPTestPlanUpdateRequest":
        targets = [*self.workflow_ids, *self.test_case_ids, *self.test_suite_ids]
        if not targets:
            raise ValueError("至少指定一个已有 Workflow、Test Case 或 Test Suite")
        if len(targets) > MCP_TEST_PLAN_TARGET_LIMIT:
            raise ValueError("测试计划建议的资产总数不能超过 100")
        if len(set(targets)) != len(targets):
            raise ValueError("测试计划建议中的资产不能重复")
        return self


class MCPTestPlanUpdateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["flowtest-mcp-planning-v1"] = MCP_PLANNING_SCHEMA_VERSION
    project_id: UUID
    test_plan_id: UUID
    change_set_id: UUID | None = None
    proposed_item_count: int = Field(ge=1, le=MCP_TEST_PLAN_TARGET_LIMIT)
    unpublished_dependencies: list[str] = Field(default_factory=list, max_length=100)
    dry_run: bool
    requires_human_review: Literal[True] = True
    automatic_publish: Literal[False] = False
    automatic_execute: Literal[False] = False
    idempotency_replayed: bool = False
    next_action: str = Field(min_length=1, max_length=400)
    trace_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def require_change_set_for_persisted_result(self) -> "MCPTestPlanUpdateResponse":
        if self.dry_run and self.change_set_id is not None:
            raise ValueError("dry-run 不能返回已创建的 ChangeSet")
        if not self.dry_run and self.change_set_id is None:
            raise ValueError("已持久化的计划建议必须包含 change_set_id")
        return self


class MCPCancelPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    execution_id: UUID


class MCPCancelPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["flowtest-mcp-planning-v1"] = MCP_PLANNING_SCHEMA_VERSION
    project_id: UUID
    execution_id: UUID
    status: Literal["queued", "running", "passed", "failed", "cancelled"]
    cancellation_requested: bool
    cleanup_pending: bool
    idempotent: bool
    next_action: str = Field(min_length=1, max_length=400)
    trace_id: str = Field(min_length=1, max_length=128)
