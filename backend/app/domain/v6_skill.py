"""Contract for the installable V6 integration-flow skill package."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SKILL_NAME = "flowtest-generate-integration-flow"
SKILL_MANIFEST_SCHEMA_VERSION = "flowtest-skill-manifest-v1"
SKILL_VERSION = "1.0.0-rc.1"
SKILL_MINIMUM_MCP_VERSION = "s55-sandbox-preview-v1"

SKILL_REQUIRED_TOOLS = (
    "flowtest.list_projects",
    "flowtest.inspect_project",
    "flowtest.discover_services",
    "flowtest.inspect_contract",
    "flowtest.begin_test_context",
    "flowtest.inspect_context_requirements",
    "flowtest.ingest_external_evidence",
    "flowtest.ingest_java_evidence",
    "flowtest.ingest_database_evidence",
    "flowtest.inspect_test_context",
    "flowtest.plan_integration_test",
    "flowtest.validate_integration_plan",
    "flowtest.compile_integration_flowspec",
    "flowtest.explain_compiler_diagnostics",
    "flowtest.validate_flowspec",
    "flowtest.propose_flow_draft",
    "flowtest.inspect_flow_proposal",
)
SKILL_OPTIONAL_TOOLS = (
    "flowtest.inspect_entity_mapping",
    "flowtest.inspect_data_profile",
    "flowtest.preview_flow_proposal",
)
SKILL_REQUIRED_SCOPES = (
    "mcp:read",
    "mcp:evidence:write",
    "mcp:flow:propose",
)
SKILL_OPTIONAL_SCOPES = ("mcp:preview:execute",)
SKILL_STAGES = (
    "select_project",
    "create_context",
    "inspect_missing_evidence",
    "collect_external_evidence",
    "ingest_evidence",
    "plan",
    "compile",
    "dry_run",
    "propose_draft",
    "visual_review",
    "optional_sandbox_preview",
)


class SkillExternalDependency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["code_mcp", "database_mcp"]
    access: Literal["read_only", "schema_and_profile_only"]
    optional: bool


class SkillHumanApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_before: list[str] = Field(min_length=1)
    never_implied_by: list[str] = Field(min_length=1)


class SkillEvaluationReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["flowtest-v6-evaluation-v1"]
    annotations: str = Field(min_length=1)
    baseline: str = Field(min_length=1)
    guide: str = Field(min_length=1)


class IntegrationFlowSkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["flowtest-skill-manifest-v1"]
    name: Literal["flowtest-generate-integration-flow"]
    version: Literal["1.0.0-rc.1"]
    minimum_mcp_version: Literal["s55-sandbox-preview-v1"]
    required_tools: list[str] = Field(min_length=1)
    optional_tools: list[str]
    required_scopes: list[str] = Field(min_length=1)
    optional_scopes: list[str]
    external_dependencies: list[SkillExternalDependency]
    stages: list[str] = Field(min_length=1)
    human_approval: SkillHumanApproval
    stop_conditions: list[str] = Field(min_length=1)
    security_rules: list[str] = Field(min_length=1)
    evaluation: SkillEvaluationReference

    @model_validator(mode="after")
    def validate_frozen_contract(self) -> IntegrationFlowSkillManifest:
        expected = {
            "required_tools": SKILL_REQUIRED_TOOLS,
            "optional_tools": SKILL_OPTIONAL_TOOLS,
            "required_scopes": SKILL_REQUIRED_SCOPES,
            "optional_scopes": SKILL_OPTIONAL_SCOPES,
            "stages": SKILL_STAGES,
        }
        actual = {
            "required_tools": tuple(self.required_tools),
            "optional_tools": tuple(self.optional_tools),
            "required_scopes": tuple(self.required_scopes),
            "optional_scopes": tuple(self.optional_scopes),
            "stages": tuple(self.stages),
        }
        mismatches = [name for name, value in expected.items() if actual[name] != value]
        if mismatches:
            raise ValueError("skill manifest contract mismatch: " + ", ".join(mismatches))
        if set(self.required_tools) & set(self.optional_tools):
            raise ValueError("required and optional tools must be disjoint")
        if set(self.required_scopes) & set(self.optional_scopes):
            raise ValueError("required and optional scopes must be disjoint")
        return self
