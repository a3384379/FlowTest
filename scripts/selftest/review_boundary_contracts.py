"""Frozen review/recovery and Preview observations; no formal Run is implied."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, StrictInt
from scripts.selftest.contracts import Contract, FixtureJournal, Identity, McpCallReceipt, Sha256
from scripts.selftest.io import JsonObject
from scripts.selftest.mcp_governance_contracts import Result
from scripts.selftest.mcp_probe_contracts import ProbeSnapshot
from scripts.selftest.mcp_probe_evidence import DisposalReceipt, StackSnapshot

ReviewAction = Literal[
    "preview_cancel",
    "unknown_publish",
    "stale_proposal",
    "stale_approval",
    "concurrent_accept",
    "partial_resume",
]
ReviewTransport = Literal["stdio", "streamable-http"]


class ReviewScope(Contract):
    project_id: UUID
    fixture_environment_id: UUID
    fixture_service_id: UUID
    production_environment_id: UUID


class ReviewScenario(Contract):
    scenario_id: Identity
    action: ReviewAction
    transport: ReviewTransport


class ReviewManifest(Contract):
    batch_key: Identity
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    pack_digest: Sha256
    source_digest: Sha256
    scope: ReviewScope
    writer_machine_id: UUID
    reviewer_id: UUID
    created_at: AwareDatetime
    expires_at: AwareDatetime
    scenarios: tuple[ReviewScenario, ...] = Field(min_length=12, max_length=12)
    claim: Literal["review_recovery_and_preview_only"] = "review_recovery_and_preview_only"
    trust: Literal["local_untrusted"] = "local_untrusted"


class ReviewHTTPReceipt(Contract):
    id: UUID
    step: Identity
    method: Literal["GET", "POST", "PUT", "PATCH"]
    path: str = Field(max_length=500)
    request_digest: Sha256
    status: StrictInt = Field(ge=100, le=599)
    code: Identity | None
    trace_present: StrictBool
    outcome: Literal["received", "lost_response_body"]
    response_digest: Sha256 | None
    started_at: AwareDatetime
    completed_at: AwareDatetime


class ReviewSource(Contract):
    transport: ReviewTransport
    api_id: UUID
    api_version: StrictInt = Field(ge=1)
    contract_fingerprint: Sha256
    context: JsonObject
    spec: JsonObject
    spec_digest: Sha256
    fixture_epoch: Identity
    calls: tuple[McpCallReceipt, ...] = Field(min_length=4, max_length=4)
    frozen_at: AwareDatetime


class PreviewNode(Contract):
    node_id: Identity
    node_type: Identity
    phase: Literal["main", "cleanup"]
    status: Identity
    attempts: StrictInt = Field(ge=0)
    assertions_complete: StrictBool


class PreviewExecution(Contract):
    execution_id: UUID
    project_id: UUID
    environment_id: UUID
    workflow_id: UUID | None
    workflow_version_id: UUID | None
    run_purpose: Literal["standard", "preview"]
    source_case_id: UUID | None
    source_plan_run_item_id: UUID | None
    status: Identity
    main_status: Identity | None
    cleanup_status: Identity | None
    bindings_complete: StrictBool
    nodes: tuple[PreviewNode, ...] = Field(max_length=100)
    node_total: StrictInt = Field(ge=0)
    truncated: StrictBool
    children_total: StrictInt = Field(ge=0)
    children_complete: StrictBool
    nested_node_total: StrictInt = Field(ge=0)
    nested_nodes_complete: StrictBool
    completed_at: AwareDatetime | None
    workflow_fingerprint: Sha256 | None


class PreviewBudgetProjection(Contract):
    max_nodes: StrictInt
    max_requests: StrictInt
    max_dataset_rows: StrictInt
    max_parallelism: StrictInt
    max_runtime_seconds: StrictInt


class PreviewApprovalProjection(Contract):
    id: UUID
    project_id: UUID
    change_set_id: UUID
    environment_id: UUID
    executor_id: UUID
    executor_kind: Identity
    proposal_fingerprint: Sha256
    context_fingerprint: Sha256
    context_revision_id: UUID
    budget: PreviewBudgetProjection


class ReviewObservation(Contract):
    scenario_id: Identity
    started_at: AwareDatetime
    completed_at: AwareDatetime
    before: ProbeSnapshot
    checkpoint: ProbeSnapshot | None = None
    after: ProbeSnapshot
    proposal_id: UUID
    proposal_arguments: JsonObject
    proposal_result: JsonObject
    proposal_envelope: JsonObject
    workflow_read_envelope: JsonObject | None = None
    workflow_id: UUID | None = None
    approval_id: UUID | None = None
    preview: PreviewExecution | None = None
    preview_approval: PreviewApprovalProjection | None = None
    preview_execution_ids: tuple[UUID, ...] = Field(default=(), max_length=2)
    tool_results: tuple[Result, ...] = Field(default=(), max_length=2)
    journal: FixtureJournal | None = None
    http: tuple[ReviewHTTPReceipt, ...] = Field(max_length=30)
    calls: tuple[McpCallReceipt, ...] = Field(max_length=10)


class ReviewEvidence(Contract):
    manifest_digest: Sha256
    authority_digest: Sha256
    stack: StackSnapshot
    sources: tuple[ReviewSource, ...] = Field(max_length=2)
    observations: tuple[ReviewObservation, ...] = Field(max_length=12)
    http_admitted: StrictInt = Field(ge=0, le=500)
    http_rejected: StrictInt = Field(ge=0)
    tools_admitted: StrictInt = Field(ge=0, le=100)
    tools_rejected: StrictInt = Field(ge=0)
    protocol_cleanup_complete: StrictBool
    collected_at: AwareDatetime
    disposal: DisposalReceipt | None = None
