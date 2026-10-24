"""An explicitly authorized, read-only post-run task; never a generation retry."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator
from scripts.selftest.contracts import Contract, Identity, OracleBinding, Sha256

from app.domain.failure_triage import FailureClassification


class DiagnosisConclusion(Contract):
    execution_id: UUID
    classification: FailureClassification
    error_code: Identity
    node_id: Identity
    phase: Literal["main", "cleanup"]
    explanation: str = Field(min_length=1, max_length=2000)
    supporting_sequences: tuple[Annotated[int, Field(ge=1, le=100, strict=True)], ...] = Field(
        min_length=2, max_length=100
    )
    raw_failure_preserved: Literal[True] = True
    required_oracles_preserved: Literal[True] = True
    changes_applied: Literal[False] = False


class DiagnosisTask(Contract):
    schema_version: Literal["flowtest-host-diagnosis-task-v1"] = "flowtest-host-diagnosis-task-v1"
    project_id: UUID
    batch_key: Identity
    origin_batch_id: UUID
    origin_batch_key: Identity
    scenario_id: Identity
    variant_key: Identity
    execution_id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    workflow_version: int = Field(ge=1, strict=True)
    workflow_fingerprint: Sha256
    environment_id: UUID
    error_code: Identity
    node_id: Identity
    phase: Literal["main", "cleanup"]
    expected_classification: FailureClassification = "PRODUCT_DEFECT"
    required_oracles: tuple[OracleBinding, ...] = Field(min_length=1, max_length=500)
    manifest_sha256: Sha256
    evidence_sha256: Sha256
    verification_sha256: Sha256
    expected_digest: Sha256
    authorized_data_digest: Sha256


class DiagnosisReceipt(Contract):
    schema_version: Literal["flowtest-host-diagnosis-v1"] = "flowtest-host-diagnosis-v1"
    status: Literal["NOT_RUN", "pending", "diagnosed", "blocked", "error"]
    task_digest: Sha256
    authorization_digest: Sha256 | None
    attempt_id: UUID | None
    origin_batch_id: UUID
    execution_id: UUID
    actual_tool_calls: int = Field(ge=0, le=100)
    host: Identity
    model: Identity
    cli_version: Identity
    skill_digest: Sha256
    prompt_digest: Sha256
    reason_codes: tuple[Identity, ...] = Field(default=(), max_length=20)
    conclusion: DiagnosisConclusion | None = None
    # Hashes bind separately retained full process/tool receipts, not model self-report.
    process_digest: Sha256 | None = None
    tool_receipts_digest: Sha256 | None = None
    billed_cost: Literal["unknown"] = "unknown"
    raw_failure_preserved: Literal[True] = True
    changes_applied: Literal[False] = False

    @model_validator(mode="after")
    def completed_diagnosis_is_bound(self) -> DiagnosisReceipt:
        if self.status == "diagnosed" and (
            self.conclusion is None
            or self.attempt_id is None
            or self.authorization_digest is None
            or self.process_digest is None
            or self.tool_receipts_digest is None
            or self.actual_tool_calls < 2
            or self.reason_codes
        ):
            raise ValueError("completed diagnosis requires the independent frozen call chain")
        if self.status != "diagnosed" and self.conclusion is not None:
            raise ValueError("incomplete diagnosis cannot carry a completed conclusion")
        return self
