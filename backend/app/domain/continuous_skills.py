"""Frozen tool contracts for the four continuous-quality skill packages."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.v6_skill import SkillEvaluationReference, SkillHumanApproval

ContinuousSkillName = Literal[
    "flowtest-project-onboarding",
    "flowtest-complete-coverage",
    "flowtest-change-aware-regression",
    "flowtest-triage-and-repair",
]


@dataclass(frozen=True, slots=True)
class ContinuousSkillProfile:
    name: ContinuousSkillName
    required_tools: tuple[str, ...]
    optional_tools: tuple[str, ...]
    required_scopes: tuple[str, ...]
    optional_scopes: tuple[str, ...]
    stages: tuple[str, ...]


CONTINUOUS_SKILL_PROFILES = (
    ContinuousSkillProfile(
        "flowtest-project-onboarding",
        (
            "flowtest.list_projects",
            "flowtest.inspect_project",
            "flowtest.discover_services",
            "flowtest.inspect_contract",
            "flowtest.begin_test_context",
            "flowtest.inspect_context_requirements",
            "flowtest.ingest_external_evidence",
            "flowtest.inspect_test_context",
            "flowtest.find_assets",
            "flowtest.inspect_project_readiness",
        ),
        (
            "flowtest.inspect_connection",
            "flowtest.ensure_project",
            "flowtest.ensure_service_target",
            "flowtest.ensure_test_environment",
            "flowtest.check_service_target",
            "flowtest.ingest_java_source_snapshot",
            "flowtest.ingest_database_evidence",
            "flowtest.inspect_entity_mapping",
            "flowtest.preview_contract_import",
            "flowtest.commit_contract_import",
        ),
        ("mcp:read", "mcp:evidence:write"),
        ("mcp:project:bootstrap", "mcp:contract:import"),
        (
            "bootstrap_assets",
            "select_project",
            "inspect_contracts",
            "create_context",
            "ingest_authorized_evidence",
            "report_missing_evidence",
        ),
    ),
    ContinuousSkillProfile(
        "flowtest-complete-coverage",
        (
            "flowtest.list_projects",
            "flowtest.inspect_project",
            "flowtest.find_assets",
            "flowtest.inspect_contract",
            "flowtest.inspect_test_evidence",
            "flowtest.analyze_test_coverage",
            "flowtest.generate_test_design",
            "flowtest.propose_test_design",
        ),
        (
            "flowtest.inspect_source_evidence",
            "flowtest.inspect_project_readiness",
            "flowtest.propose_test_plan_update",
        ),
        ("mcp:read", "mcp:write"),
        (),
        (
            "select_project",
            "inspect_evidence",
            "analyze_gaps",
            "generate_design",
            "dry_run",
            "propose_design",
            "human_review",
        ),
    ),
    ContinuousSkillProfile(
        "flowtest-change-aware-regression",
        (
            "flowtest.list_projects",
            "flowtest.inspect_project",
            "flowtest.find_assets",
            "flowtest.inspect_change_regression",
            "flowtest.inspect_change_impact",
            "flowtest.inspect_context_diff",
            "flowtest.inspect_affected_flows",
            "flowtest.export_flowspec",
            "flowtest.validate_flowspec",
            "flowtest.propose_maintenance",
            "flowtest.inspect_flow_proposal",
        ),
        (
            "flowtest.preview_flow_proposal",
            "flowtest.inspect_project_readiness",
            "flowtest.propose_test_plan_update",
        ),
        ("mcp:read", "mcp:flow:propose", "mcp:regression:prepare"),
        ("mcp:preview:execute", "mcp:test-plan:propose"),
        (
            "select_project",
            "discover_assets",
            "inspect_existing_regression",
            "prepare_analysis",
            "compare_context",
            "inspect_affected_flows",
            "dry_run",
            "propose_and_link",
            "human_review",
            "optional_sandbox_preview",
        ),
    ),
    ContinuousSkillProfile(
        "flowtest-triage-and-repair",
        (
            "flowtest.list_projects",
            "flowtest.inspect_project",
            "flowtest.find_assets",
            "flowtest.inspect_run_evidence",
            "flowtest.diagnose_failure",
            "flowtest.export_flowspec",
            "flowtest.validate_flowspec",
            "flowtest.propose_repair",
            "flowtest.inspect_flow_proposal",
        ),
        (
            "flowtest.preview_flow_proposal",
            "flowtest.inspect_test_context",
            "flowtest.inspect_project_readiness",
            "flowtest.cancel_preview",
        ),
        ("mcp:read", "mcp:flow:propose"),
        ("mcp:preview:execute",),
        (
            "select_project",
            "inspect_failed_execution",
            "diagnose",
            "validate_patch",
            "dry_run",
            "propose_repair",
            "human_review",
            "optional_sandbox_preview",
        ),
    ),
)


class ContinuousQASkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["flowtest-skill-manifest-v1"]
    name: ContinuousSkillName
    version: Literal["1.2.0-rc.1"]
    minimum_mcp_version: Literal["s61-mcp-connection-v1"]
    required_tools: list[str] = Field(min_length=1)
    optional_tools: list[str]
    required_scopes: list[str] = Field(min_length=1)
    optional_scopes: list[str]
    stages: list[str] = Field(min_length=1)
    human_approval: SkillHumanApproval
    stop_conditions: list[str] = Field(min_length=1)
    security_rules: list[str] = Field(min_length=1)
    evaluation: SkillEvaluationReference
    automatic_accept: Literal[False]
    automatic_apply: Literal[False]
    automatic_publish: Literal[False]
    automatic_execute: Literal[False]

    @model_validator(mode="after")
    def frozen_profile(self) -> "ContinuousQASkillManifest":
        profile = next(item for item in CONTINUOUS_SKILL_PROFILES if item.name == self.name)
        for field in (
            "required_tools",
            "optional_tools",
            "required_scopes",
            "optional_scopes",
            "stages",
        ):
            if tuple(getattr(self, field)) != getattr(profile, field):
                raise ValueError(f"skill profile mismatch: {field}")
        if self.evaluation.runtime is None:
            raise ValueError("continuous QA skills require a self-contained evaluator")
        return self
