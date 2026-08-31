from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.failure_repair import FailureDiagnosis, RepairKind
from app.domain.flow_spec import FlowSpec
from app.domain.flow_spec_v2 import FlowSpecV2
from app.schemas.flow_spec import FlowSpecChangeSetDetailResponse


class RepairProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RepairKind
    proposed_spec: FlowSpec | FlowSpecV2
    expected_target_revision: int = Field(ge=1)
    context_revision_id: UUID | None = None
    rationale: str = Field(min_length=1, max_length=2000)
    acknowledge_oracle_weakening: bool = False


class FailureDiagnosisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: UUID
    workflow_id: UUID | None
    diagnosis: FailureDiagnosis


class RepairProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-repair-proposal-v1"] = "flowtest-repair-proposal-v1"
    execution_id: UUID
    diagnosis: FailureDiagnosis
    proposal: FlowSpecChangeSetDetailResponse
