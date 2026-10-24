"""Pure compiler wire observations; untrusted synthetic documents are bounded opaque input."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field
from scripts.selftest.contracts import (
    Contract,
    McpCallReceipt,
    RequiredDisposal,
    Sha256,
    TargetDisposalReceipt,
)
from scripts.selftest.draft_boundary_contracts import DraftBoundaryObservation
from scripts.selftest.initialization_contracts import InstallationInventory
from scripts.selftest.io import JsonObject
from scripts.selftest.mcp_governance_contracts import Result
from scripts.selftest.product_boundary_contracts import ProductBoundaryManifest

KEYS = (
    "positive",
    "reproducible",
    "negative",
    "null_field",
    "missing_context",
    "unsupported_route",
    "fixture_auth",
    "scope_none",
    "scope_read",
    "scope_flow",
    "organization",
    "version",
    "extra_fields",
    "boolean_budget",
    "source_changed",
    "context_changed",
    "catalog",
)


class CompileBoundaryManifest(Contract):
    product: ProductBoundaryManifest
    project_id: UUID
    foreign_project_id: UUID
    expected_keys: tuple[str, ...]
    verifier_digest: Sha256
    created_at: datetime
    deadline: datetime
    disposal: RequiredDisposal


class CompileBoundaryObservation(Contract):
    key: str
    transport: Literal["stdio", "streamable-http"]
    before: InstallationInventory
    after: InstallationInventory
    proposal_ids_before: tuple[UUID, ...]
    proposal_ids_after: tuple[UUID, ...]
    request: JsonObject
    response: JsonObject | None = None
    boundary: Result | None = None
    calls: tuple[McpCallReceipt, ...] = Field(max_length=2)
    catalog_names: tuple[str, ...] = ()
    sdk_version: str
    protocol_version: str
    completed_at: datetime


class CompileBoundaryEvidence(Contract):
    manifest_digest: Sha256
    observations: tuple[CompileBoundaryObservation, ...] = Field(max_length=34)
    drafts: tuple[DraftBoundaryObservation, ...] = Field(default=(), max_length=4)
    http_attempts: int = Field(ge=0, le=500)
    tool_attempts: int = Field(ge=0, le=100)
    rejected_attempts: int = Field(ge=0)
    collected_at: datetime
    disposal: TargetDisposalReceipt | None = None


class CompileBoundaryReport(Contract):
    expected_keys: tuple[str, ...]
    matched_keys: tuple[str, ...]
    reason_codes: tuple[str, ...]
    exit_code: Literal[0, 2]
    model_calls: Literal[0] = 0
    trust: Literal["local_untrusted"] = "local_untrusted"
