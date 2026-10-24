"""Independent protocol negative fixtures and bounded observations."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator
from scripts.selftest.contracts import Contract, Identity, Sha256

Transport = Literal["stdio", "streamable-http"]
Actor = Literal["reader_a", "reader_b", "none", "limited", "revoked", "expired", "human", "ci"]
Operation = Literal[
    "unknown_tool",
    "bad_params",
    "list_projects",
    "cross_org",
    "propose_denied",
    "modern",
    "legacy",
    "unsupported",
    "resources",
    "prompts",
    "inspect",
    "interleaved",
    "concurrent",
]
RpcId = StrictInt | Annotated[StrictStr, Field(min_length=1, max_length=160)]


class EmptyAssets(Contract):
    workflows: StrictInt = Field(default=0, ge=0)
    workflow_versions: StrictInt = Field(default=0, ge=0)
    cases: StrictInt = Field(default=0, ge=0)
    case_versions: StrictInt = Field(default=0, ge=0)
    plans: StrictInt = Field(default=0, ge=0)
    runs: StrictInt = Field(default=0, ge=0)
    executions: StrictInt = Field(default=0, ge=0)
    proposals: StrictInt = Field(default=0, ge=0)


class ActorGolden(Contract):
    actor: Actor
    project_ids: tuple[UUID, ...] = Field(max_length=2)
    business_code: Identity | None = None
    diagnostic_code: Identity | None = None


class ProtocolGolden(Contract):
    layer: Literal["tool_error", "business_error", "success", "protocol_error"]
    tool_name: Identity | None = None
    arguments_digest: Sha256 | None = None
    group: tuple[ActorGolden, ...] = Field(default=(), max_length=3)
    is_error: StrictBool | None = None
    business_code: Identity | None = None
    diagnostic_code: Identity | None = None
    rpc_error_code: StrictInt | None = None
    text_marker: Literal["unknown_tool", "invalid_arguments"] | None = None
    protocol_version: Identity | None = "2026-07-28"
    project_ids: tuple[UUID, ...] = Field(default=(), max_length=2)
    minimum_items: int = Field(default=0, ge=0, le=1000)
    organization_id: UUID | None = None
    effective_scopes: tuple[Identity, ...] = Field(default=(), max_length=30)
    runtime_profile: Literal["full", "compact", "standalone"] | None = None
    trace_required: StrictBool = False
    assets: EmptyAssets = Field(default_factory=EmptyAssets)


class ProtocolScenario(Contract):
    scenario_id: Identity
    acceptance_id: Identity
    variant_key: Identity
    title: Identity
    transport: Transport
    actor: Actor
    operation: Operation
    expected: ProtocolGolden


class ProtocolPack(Contract):
    catalog_fingerprint: Sha256
    tool_names: tuple[Identity, ...] = Field(min_length=1, max_length=300)
    schema_version: Literal["flowtest-mcp-negative-v1"]
    pack_id: Literal["mcp-negative-v1"]
    pack_version: Literal["1.0.0"]
    sdk_version: Literal["2.2.0"]
    max_tool_calls: int = Field(default=100, ge=1, le=100)
    max_requests: int = Field(default=500, ge=1, le=500)
    max_runtime_seconds: int = Field(default=600, ge=1, le=600)
    scenarios: tuple[ProtocolScenario, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def exact_ids(self) -> "ProtocolPack":
        values = [item.scenario_id for item in self.scenarios]
        if len(values) != len(set(values)):
            raise ValueError("协议故障分母的ID不能重复")
        return self


class FixtureIdentity(Contract):
    project_a: UUID
    project_b: UUID
    organization_a: UUID
    organization_b: UUID


class ProtocolManifest(Contract):
    batch_key: Identity
    nonce: Identity
    fixture: FixtureIdentity
    pack_digest: Sha256
    source_digest: Sha256
    catalog_fingerprint: Sha256
    tool_names: tuple[Identity, ...] = Field(min_length=1, max_length=300)
    created_at: datetime
    expires_at: datetime
    scenarios: tuple[ProtocolScenario, ...] = Field(min_length=1, max_length=50)
    sdk_version: Literal["2.2.0"] = "2.2.0"
    trust: Literal["local_untrusted"] = "local_untrusted"

    @model_validator(mode="after")
    def frozen_nonempty_scope(self) -> "ProtocolManifest":
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("必须冻结带时区的期限")
        if not 0 < (self.expires_at - self.created_at).total_seconds() <= 600:
            raise ValueError("批次期限必须在600秒内")
        identifiers = [item.scenario_id for item in self.scenarios]
        if len(set(identifiers)) != len(identifiers) or len(set(self.tool_names)) != len(
            self.tool_names
        ):
            raise ValueError("冻结分母与工具目录不能重复")
        if (
            self.fixture.project_a == self.fixture.project_b
            or self.fixture.organization_a == self.fixture.organization_b
        ):
            raise ValueError("独立身份必须绑定不同组织和项目")
        return self


class RpcRequest(Contract):
    session_id: UUID
    id: RpcId
    method: Identity
    tool_name: Identity | None = None
    arguments_digest: Sha256 | None = None
    observed_at: datetime


class RpcResponse(Contract):
    session_id: UUID
    id: RpcId
    result_digest: Sha256 | None = None
    error_code: StrictInt | None = None
    observed_at: datetime


class ResultProjection(Contract):
    actor: Actor | None = None
    session_id: UUID | None = None
    rpc_id: RpcId | None = None
    is_error: StrictBool | None = None
    business_code: Identity | None = None
    diagnostic_code: Identity | None = None
    rpc_error_code: StrictInt | None = None
    text_marker: Literal["unknown_tool", "invalid_arguments"] | None = None
    project_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    total: StrictInt | None = Field(default=None, ge=0)
    item_count: StrictInt = Field(default=0, ge=0, le=1000)
    organization_id: UUID | None = None
    effective_scopes: tuple[Identity, ...] = Field(default=(), max_length=30)
    runtime_profile: Literal["full", "compact", "standalone"] | None = None
    trace_present: StrictBool = False
    result_digest: Sha256 | None = None
    sdk_result_digest: Sha256 | None = None


class ProtocolObservation(Contract):
    scenario_id: Identity
    transport: Transport
    actor: Actor
    sdk_version: Identity
    protocol_version: Identity | None
    catalog_fingerprint: Sha256 | None
    tool_names: tuple[Identity, ...] = Field(max_length=300)
    requests: tuple[RpcRequest, ...] = Field(max_length=100)
    responses: tuple[RpcResponse, ...] = Field(max_length=100)
    results: tuple[ResultProjection, ...] = Field(max_length=10)
    assets: EmptyAssets
    before_assets: EmptyAssets
    started_at: datetime
    completed_at: datetime
    complete: StrictBool
    error_code: Identity | None = None


class ProtocolEvidence(Contract):
    batch_key: Identity
    nonce: Identity
    pack_digest: Sha256
    source_digest: Sha256
    scenarios: tuple[ProtocolObservation, ...] = Field(max_length=50)
    collected_at: datetime
    cleanup_complete: StrictBool
    protocol_attempts: StrictInt = Field(ge=0, le=100)
    http_requests: StrictInt = Field(ge=0, le=500)
    rejected_http_requests: StrictInt = Field(default=0, ge=0)
    rejected_tool_calls: StrictInt = Field(default=0, ge=0)
    trust: Literal["local_untrusted"] = "local_untrusted"
