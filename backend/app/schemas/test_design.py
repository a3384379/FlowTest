"""API contracts for S42 test design proposals and controlled writes."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.domain.test_design import TestDesignDocument
from app.schemas.test_assets import AssetName, TagName, TestCaseDefinitionInput


class MCPTestCaseDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AssetName
    description: str = Field(default="", max_length=4000)
    tags: list[TagName] = Field(default_factory=list, max_length=20)
    definition: TestCaseDefinitionInput


class MCPControlledWriteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[\x21-\x7e]+$")
    dry_run: bool = True
    title: AssetName
    source_ref: str | None = Field(default=None, max_length=512)
    confidence: float = Field(ge=0, le=1)
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"
    design: TestDesignDocument
    test_cases: list[MCPTestCaseDraft] = Field(default_factory=list, max_length=50)


class MCPManualApprovalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(default="", max_length=2000)


class MCPControlledWriteReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, JsonValue] | None = None
    note: str = Field(default="", max_length=2000)
    approval_id: UUID | None = None


class MCPControlledWriteEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: JsonValue
    evidence_refs: list[dict[str, str]] = Field(default_factory=list, max_length=200)
    confidence: float = Field(ge=0, le=1)
    redactions: list[str] = Field(default_factory=list, max_length=100)
    trace_id: str = Field(min_length=1, max_length=128)
    warnings: list[str] = Field(default_factory=list, max_length=100)
