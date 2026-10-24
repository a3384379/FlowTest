"""Deployment-authorized host contracts; no credential or approval comes from model output."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from scripts.selftest.contracts import Contract, Sha256
from scripts.selftest.host_diagnosis_contracts import DiagnosisConclusion

from app.domain.test_design import TestDesignDocument
from app.domain.test_design_compilation import FrozenGenerationOrigin


class HostBudget(Contract):
    maximum_tool_calls: int = Field(ge=1, le=100, strict=True)
    wall_seconds: int = Field(ge=1, le=600, strict=True)
    attempts: int = Field(default=1, ge=1, le=1, strict=True)
    maximum_prompt_bytes: int = Field(ge=1, le=131072, strict=True)
    maximum_result_bytes: int = Field(ge=1024, le=1048576, strict=True)
    maximum_total_result_bytes: int = Field(ge=1024, le=8388608, strict=True)
    # CLI token usage is post-hoc telemetry. A separate provider cap is required for hard caps.
    provider_cap_reference: str | None = Field(default=None, min_length=1, max_length=200)
    require_hard_provider_cap: bool = False


class HostGeneratedDesign(Contract):
    fingerprint: Sha256
    design: TestDesignDocument
    origin: FrozenGenerationOrigin
    persisted: Literal[False]


class ReadOnlyRepairPolicy(Contract):
    tool_name: str = Field(
        pattern=r"^flowtest\.(inspect_contract|generate_test_design|analyze_test_coverage|validate_flowspec|compile_test_design|validate_integration_plan|compile_integration_flowspec)$"
    )
    error_codes: tuple[str, ...] = Field(min_length=1, max_length=5)
    allowed_argument_fields: tuple[str, ...] = Field(min_length=1, max_length=5)


class HostAuthorization(Contract):
    authorization_id: UUID
    approved_by: str = Field(min_length=1, max_length=200)
    host_id: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=200)
    provider: str = Field(min_length=1, max_length=100)
    cli_version: str = Field(min_length=1, max_length=200)
    project_id: UUID
    batch_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
    environment_ids: tuple[UUID, ...] = Field(min_length=1, max_length=2)
    task_digest: Sha256
    skill_digest: Sha256
    authorized_data_digest: Sha256
    policy_digest: Sha256
    allowed_tools: tuple[str, ...] = Field(min_length=1, max_length=30)
    review_mode: Literal["human", "ci_fixture"] = "human"
    reviewer_ids: tuple[UUID, ...] = Field(min_length=1, max_length=5)
    read_only_repairs: tuple[ReadOnlyRepairPolicy, ...] = Field(default=(), max_length=5)
    budget: HostBudget
    approved_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def aware_authorization(self) -> HostAuthorization:
        if self.approved_at.utcoffset() is None or self.expires_at.utcoffset() is None:
            raise ValueError("authorization timestamps require timezone")
        if self.expires_at <= self.approved_at:
            raise ValueError("authorization must have a positive lifetime")
        return self


class HostToolReceipt(Contract):
    sequence: int = Field(ge=1, le=100)
    attempt_id: UUID
    phase: Literal["workflow", "case", "diagnosis"]
    tool_name: str = Field(min_length=1, max_length=160)
    request_digest: Sha256
    result_digest: Sha256 | None
    catalog_digest: Sha256
    started_at: datetime
    completed_at: datetime | None
    business_success: bool | None = None
    result_bytes: int = Field(default=0, ge=0, strict=True)
    outcome: Literal["pending", "completed", "rejected", "unknown"]
    reason_code: str | None = Field(default=None, max_length=100)
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,99}$")
    resolved_by: int | None = Field(default=None, ge=1, le=100, strict=True)


class HostStopReceipt(Contract):
    attempt_id: UUID
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,99}$")
    first_rejected_at: datetime
    last_rejected_at: datetime
    admitted_calls: int = Field(ge=0, le=100, strict=True)
    rejected_calls: int = Field(ge=1, le=100, strict=True)
    rejected_count_truncated: bool = False
    first_tool_name: str = Field(max_length=160)
    first_request_digest: Sha256


class HostAttemptResult(Contract):
    attempt_id: UUID
    phase: Literal["workflow", "case"]
    status: Literal["NOT_RUN", "blocked", "error", "waiting_for_review"]
    reason_codes: tuple[str, ...] = Field(max_length=20)
    host: str
    model: str
    cli_version: str
    skill_digest: Sha256
    prompt_digest: Sha256
    authorized_budget_digest: Sha256 | None
    actual_tool_calls: int = Field(ge=0, le=100)
    catalog_digest: Sha256 | None
    started_at: datetime | None
    completed_at: datetime
    exit_code: int | None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    billed_cost: Literal["unknown"] = "unknown"
    proposal_ids: tuple[UUID, ...] = Field(default=(), max_length=10)


class ReviewedWorkflowBinding(Contract):
    workflow_id: UUID
    version: int = Field(ge=1, strict=True)
    fingerprint: Sha256


class HostModelSummary(Contract):
    phase: Literal["workflow", "case", "diagnosis"]
    status: Literal["waiting_for_review", "blocked", "diagnosed"]
    proposal_ids: tuple[UUID, ...] = Field(default=(), max_length=3)
    reason_codes: tuple[str, ...] = Field(default=(), max_length=10)
    diagnosis: DiagnosisConclusion | None = None

    @model_validator(mode="after")
    def separate_diagnosis(self) -> HostModelSummary:
        if self.phase == "diagnosis":
            if self.proposal_ids or (self.status == "diagnosed") != (self.diagnosis is not None):
                raise ValueError("diagnosis cannot become a proposal or invent a completed result")
        elif self.diagnosis is not None or self.status == "diagnosed":
            raise ValueError("generation summaries cannot carry post-run diagnosis")
        return self
