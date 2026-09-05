from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.failure_repair import RepairKind
from app.domain.flow_spec import FlowSpec
from app.domain.flow_spec_v2 import FlowSpecV2
from app.domain.maintenance_proposals import FlowSpecMaintenanceProvenance
from app.schemas.flow_spec import FlowSpecChangeSetDetailResponse


class MaintenanceProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    context_id: UUID
    before_revision: int = Field(ge=1)
    after_revision: int = Field(ge=1)
    impact_run_id: UUID | None = None
    expected_target_revision: int = Field(ge=1)
    kind: RepairKind
    proposed_spec: FlowSpec | FlowSpecV2
    rationale: str = Field(min_length=1, max_length=2000)
    acknowledge_oracle_weakening: bool = False


class MaintenanceProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-maintenance-proposal-v1"] = "flowtest-maintenance-proposal-v1"
    provenance: FlowSpecMaintenanceProvenance
    proposal: FlowSpecChangeSetDetailResponse
