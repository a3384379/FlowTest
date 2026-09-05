"""Version-bound provenance for maintenance; deliberately not a failure diagnosis."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.failure_repair import RepairKind


class FlowSpecMaintenanceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["flowtest-maintenance-provenance-v1"] = (
        "flowtest-maintenance-provenance-v1"
    )
    context_id: UUID
    before_context_revision_id: UUID
    before_context_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    context_revision_id: UUID
    context_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    workflow_id: UUID
    expected_target_revision: int = Field(ge=1)
    impact_run_id: UUID | None = None
    patch_kind: RepairKind
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=100)
    analysis_complete: bool
    diagnostic_codes: tuple[str, ...] = ()
    oracle_weakening: bool = False
    requires_human_review: Literal[True] = True
    automatic_apply_allowed: Literal[False] = False
