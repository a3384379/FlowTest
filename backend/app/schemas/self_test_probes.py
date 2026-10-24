"""Safe metadata only; no proposal, request, credential or oracle values."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.core.self_test_probes import ProbeFixture
from app.schemas.self_tests import BuildIdentity, Digest, Identity, Reason, SelfTestDTO

ProbeKind = Literal[
    "workflow",
    "workflow_version",
    "test_case",
    "test_case_version",
    "test_plan",
    "test_plan_run",
    "workflow_execution",
    "ai_change_set",
    "test_design",
    "change_set_approval",
]
ProbeCursor = Annotated[str, Field(pattern=r"^[0-9a-f]{64}\.[0-9]{1,3}$")]


class ProbeOracle(SelfTestDTO):
    id: Identity
    kind: Identity
    expression_digest: Digest
    operator: Identity
    expected_digest: Digest


class ProbeDesignSummary(SelfTestDTO):
    document_digest: Digest
    intent_key_digest: Digest
    objective_digest: Digest
    oracles: tuple[ProbeOracle, ...] = Field(max_length=200)


class ProbeChangeItem(SelfTestDTO):
    id: UUID
    item_type: Identity
    action: Identity
    review_status: Identity
    reviewed_by_id: UUID | None
    materialized_resource_type: Identity | None
    materialized_resource_id: UUID | None
    proposed_document_digest: Digest | None = None
    design: ProbeDesignSummary | None = None


class ProbeResource(SelfTestDTO):
    kind: ProbeKind
    id: UUID
    project_id: UUID
    parent_id: UUID | None = None
    source_change_set_id: UUID | None = None
    version: int | None = Field(default=None, ge=1)
    status: Identity
    fingerprint: Digest | None = None
    created_by_id: UUID | None = None
    reviewed_by_id: UUID | None = None
    actor_type: Identity | None = None
    items: tuple[ProbeChangeItem, ...] = Field(default=(), max_length=500)
    design: ProbeDesignSummary | None = None


class ProbeInventory(SelfTestDTO):
    probe_id: UUID
    purpose: Literal["mcp_governance_negative"] = "mcp_governance_negative"
    execution_scope: Literal["governance_negative_only"] = "governance_negative_only"
    provenance: Literal["local_untrusted"] = "local_untrusted"
    binding_id: UUID
    binding_fingerprint: Digest
    manifest_digest: Digest
    source_digest: Digest
    runtime_profile: Literal["full", "compact", "compose", "standalone"]
    builds: BuildIdentity
    covered_projects: tuple[ProbeFixture, ...] = Field(min_length=2, max_length=2)
    covered_kinds: tuple[ProbeKind, ...] = Field(min_length=10, max_length=10)
    items: tuple[ProbeResource, ...] = Field(max_length=100)
    total: int = Field(ge=0)
    next_cursor: ProbeCursor | None = None
    has_more: bool = False
    complete: bool
    reason_codes: tuple[Reason, ...] = Field(default=(), max_length=10)
    snapshot_digest: Digest
    observed_at: datetime
    expires_at: datetime
