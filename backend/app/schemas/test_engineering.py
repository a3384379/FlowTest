from __future__ import annotations

import json
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.evidence import EvidenceBundle, EvidenceSourceType
from app.domain.test_design import TestDesignDocument
from app.domain.test_design_compilation import FrozenGenerationOrigin
from app.domain.test_engineering import GenerationPolicy, OperationContract

MAX_ADDITIONAL_EVIDENCE_BYTES = 2 * 1024 * 1024


class TestEngineeringGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_definition_id: UUID | None = None
    api_version: int | None = Field(default=None, ge=1, strict=True)
    contract: OperationContract | None = None
    generation_policy: GenerationPolicy = Field(default_factory=GenerationPolicy)
    additional_evidence: list[EvidenceBundle] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def require_one_source(self) -> TestEngineeringGenerateRequest:
        if (self.api_definition_id is None) == (self.contract is None):
            raise ValueError("exactly one of api_definition_id or contract is required")
        if self.api_version is not None and self.api_definition_id is None:
            raise ValueError("api_version requires api_definition_id")
        _validate_evidence_input_budget(self.additional_evidence)
        return self


class TestEngineeringEvidenceDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=160)
    source_type: EvidenceSourceType
    source_ref: str = Field(min_length=1, max_length=512)
    revision: str = Field(min_length=1, max_length=160)
    path: str = Field(min_length=1, max_length=1024)
    confidence: float = Field(ge=0, le=1)
    deterministic: bool


class TestEngineeringGenerateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fingerprint: str
    design: TestDesignDocument
    origin: FrozenGenerationOrigin | None = None
    persisted: bool = False
    contract_completeness: str
    contract_fingerprint: str
    contract: OperationContract
    evidence_details: list[TestEngineeringEvidenceDetail] = Field(default_factory=list)


class TestEngineeringProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    api_definition_id: UUID
    environment_id: UUID
    endpoint_variant: str | None = Field(default=None, min_length=1, max_length=80)
    contract: OperationContract | None = None
    generation_policy: GenerationPolicy = Field(default_factory=GenerationPolicy)
    additional_evidence: list[EvidenceBundle] = Field(default_factory=list, max_length=10)
    scenario_ids: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_evidence_budget(self) -> TestEngineeringProposalCreate:
        _validate_evidence_input_budget(self.additional_evidence)
        return self


class TestEngineeringProposalReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accept: bool
    note: str = Field(default="", max_length=2000)


class TestEngineeringMaterializedAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1, max_length=160)
    workflow_id: UUID
    test_case_id: UUID


class TestEngineeringApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_set_id: UUID
    test_design_id: UUID
    workflow_ids: list[UUID]
    test_case_ids: list[UUID]
    assets: list[TestEngineeringMaterializedAsset] = Field(default_factory=list, max_length=50)
    references_complete: bool = True


class TestEngineeringProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_set_id: UUID
    status: str
    review_status: str
    fingerprint: str
    design: TestDesignDocument
    scenario_ids: list[str]
    applied: bool
    contract_completeness: str
    contract_fingerprint: str
    contract: OperationContract
    materialization: TestEngineeringApplyResponse | None = None
    evidence_details: list[TestEngineeringEvidenceDetail] = Field(default_factory=list)


def _validate_evidence_input_budget(bundles: list[EvidenceBundle]) -> None:
    encoded = json.dumps(
        [bundle.model_dump(mode="json") for bundle in bundles],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if len(encoded) > MAX_ADDITIONAL_EVIDENCE_BYTES:
        raise ValueError("additional evidence byte budget exceeded")
