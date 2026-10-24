"""Independent synthetic governance contracts; no product model imports."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator
from scripts.selftest.contracts import Contract, Identity, Sha256
from scripts.selftest.mcp_negative_contracts import RpcRequest, RpcResponse, Transport

Action = Literal[
    "empty_design",
    "dry_run",
    "persist_low",
    "replay",
    "conflict",
    "machine_approve",
    "machine_accept",
    "low_extra_approve",
    "low_reject",
    "low_reaccept",
    "persist_high",
    "high_unapproved",
    "high_approve",
    "high_accept",
    "high_reaccept",
    "persist_other",
    "wrong_approval",
    "injection_dry",
    "unknown_approve",
    "unknown_publish",
    "unknown_run",
]
Reference = Literal["low", "high", "other"]
Role = Literal["generation_machine", "fixture_reviewer"]


class Inventory(Contract):
    workflows: StrictInt = Field(ge=0)
    workflow_versions: StrictInt = Field(ge=0)
    cases: StrictInt = Field(ge=0)
    case_versions: StrictInt = Field(ge=0)
    plans: StrictInt = Field(ge=0)
    runs: StrictInt = Field(ge=0)
    executions: StrictInt = Field(ge=0)
    proposals: StrictInt = Field(ge=0)
    designs: StrictInt = Field(ge=0)
    approvals: StrictInt = Field(ge=0)


class Oracle(Contract):
    id: Identity
    kind: Literal["status"]
    expression: Literal["$.status"]
    operator: Literal["equals"] = "equals"
    expected_digest: Sha256


class MaterializedView(Contract):
    id: UUID
    project_id: UUID
    source_change_set_id: UUID
    fingerprint: Sha256
    document_digest: Sha256
    reviewed_by_id: UUID
    status: Literal["approved"]


class ProposalView(Contract):
    id: UUID
    project_id: UUID
    source_fingerprint: Sha256
    proposed_document_digest: Sha256
    actor_type: Literal["service_account"]
    created_by_id: UUID
    status: Literal["draft", "rejected", "accepted", "partially_reviewed"]
    item_id: UUID
    item_type: Literal["test_design"]
    item_review: Literal["pending", "accepted", "rejected"]
    materialized_type: Literal["test_design"] | None
    materialized_id: UUID | None
    approval_id: UUID | None
    approved_by_id: UUID | None
    materialized: MaterializedView | None
    reviewed_by_id: UUID | None
    intent_key: Identity
    objective: Identity
    oracles: tuple[Oracle, ...] = Field(min_length=1, max_length=3)


class Expected(Contract):
    channel: Literal["mcp", "rest"]
    actor: Role
    http_status: int | None = Field(default=None, ge=100, le=599)
    tool_name: Identity | None = None
    is_error: StrictBool | None = None
    business_code: Identity | None = None
    text_marker: Literal["unknown_tool"] | None = None
    trace_required: StrictBool = False
    preview: StrictBool | None = None
    persisted: StrictBool | None = None
    result_status: Literal["draft", "accepted", "rejected"] | None = None
    target: Reference | None = None
    state_status: Literal["draft", "accepted", "rejected"] | None = None
    item_review: Literal["pending", "accepted", "rejected"] | None = None
    before: Inventory
    after: Inventory


class Scenario(Contract):
    scenario_id: Identity
    acceptance_id: Identity
    variant_key: Identity
    transport: Transport
    action: Action
    expected: Expected


class Pack(Contract):
    schema_version: Literal["flowtest-mcp-governance-negative-v1"]
    pack_id: Literal["mcp-governance-negative-v1"]
    pack_version: Literal["1.0.0"]
    sdk_version: Literal["2.2.0"]
    max_requests: Literal[500]
    max_tool_calls: Literal[100]
    max_runtime_seconds: Literal[600]
    claim: Literal["governance_negative_only"]
    scenarios: tuple[Scenario, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def nonempty_unique(self) -> "Pack":
        ids = [row.scenario_id for row in self.scenarios]
        if len(set(ids)) != len(ids):
            raise ValueError("冻结治理场景不能重复")
        return self


class Fixture(Contract):
    project_id: UUID
    organization_id: UUID
    machine_id: UUID
    owner_user_id: UUID
    reviewer_user_id: UUID


class Manifest(Contract):
    batch_key: Identity
    nonce: Identity
    pack_digest: Sha256
    source_digest: Sha256
    sdk_version: Literal["2.2.0"]
    created_at: AwareDatetime
    expires_at: AwareDatetime
    fixture: Fixture
    scenarios: tuple[Scenario, ...] = Field(min_length=1, max_length=50)
    claim: Literal["governance_negative_only"] = "governance_negative_only"
    trust: Literal["local_untrusted"] = "local_untrusted"

    @model_validator(mode="after")
    def bounded_frozen_scope(self) -> "Manifest":
        if not 0 < (self.expires_at - self.created_at).total_seconds() <= 600:
            raise ValueError("批次期限必须在600秒内")
        if self.fixture.owner_user_id == self.fixture.reviewer_user_id:
            raise ValueError("独立评审身份不能与机器所属用户相同")
        ids = [item.scenario_id for item in self.scenarios]
        if len(set(ids)) != len(ids):
            raise ValueError("冻结分母不能重复")
        return self


class Result(Contract):
    is_error: StrictBool | None = None
    business_code: Identity | None = None
    text_marker: Literal["unknown_tool"] | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    trace_present: StrictBool = False
    preview: StrictBool | None = None
    persisted: StrictBool | None = None
    status: Identity | None = None
    proposal_id: UUID | None = None
    result_digest: Sha256


class Observation(Contract):
    scenario_id: Identity
    actor: Role
    transport: Transport
    started_at: AwareDatetime
    completed_at: AwareDatetime
    request_method: Literal["POST"]
    request_path: str = Field(min_length=1, max_length=400)
    request_digest: Sha256
    wire_request: RpcRequest | None
    wire_response: RpcResponse | None
    result: Result
    before: Inventory
    after: Inventory
    state: ProposalView | None
    complete: StrictBool


class Evidence(Contract):
    batch_key: Identity
    nonce: Identity
    pack_digest: Sha256
    source_digest: Sha256
    sdk_version: Literal["2.2.0"]
    scenarios: tuple[Observation, ...] = Field(max_length=50)
    collected_at: AwareDatetime
    process_cleanup_complete: StrictBool
    http_admitted: StrictInt = Field(ge=0, le=500)
    http_rejected: StrictInt = Field(ge=0)
    tools_admitted: StrictInt = Field(ge=0, le=100)
    tools_rejected: StrictInt = Field(ge=0)
    claim: Literal["governance_negative_only"] = "governance_negative_only"
    trust: Literal["local_untrusted"] = "local_untrusted"
