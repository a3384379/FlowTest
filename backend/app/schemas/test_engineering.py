from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.test_design import TestDesignDocument
from app.domain.test_engineering import GenerationPolicy, OperationContract


class TestEngineeringGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_definition_id: UUID | None = None
    contract: OperationContract | None = None
    generation_policy: GenerationPolicy = Field(default_factory=GenerationPolicy)

    @model_validator(mode="after")
    def require_one_source(self) -> TestEngineeringGenerateRequest:
        if (self.api_definition_id is None) == (self.contract is None):
            raise ValueError("exactly one of api_definition_id or contract is required")
        return self


class TestEngineeringGenerateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fingerprint: str
    design: TestDesignDocument
    persisted: bool = False


class TestEngineeringProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    api_definition_id: UUID
    environment_id: UUID
    endpoint_variant: str | None = Field(default=None, min_length=1, max_length=80)
    contract: OperationContract | None = None
    generation_policy: GenerationPolicy = Field(default_factory=GenerationPolicy)
    scenario_ids: list[str] = Field(default_factory=list, max_length=50)


class TestEngineeringProposalReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accept: bool
    note: str = Field(default="", max_length=2000)


class TestEngineeringProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_set_id: UUID
    status: str
    review_status: str
    fingerprint: str
    design: TestDesignDocument
    scenario_ids: list[str]
    applied: bool


class TestEngineeringApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_set_id: UUID
    test_design_id: UUID
    workflow_ids: list[UUID]
    test_case_ids: list[UUID]
