"""Frozen transport-fault contracts; independent of candidate application models."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator
from scripts.selftest.contracts import Contract, Identity, Sha256
from scripts.selftest.mcp_negative_contracts import RpcId, RpcRequest, RpcResponse, Transport
from scripts.selftest.mcp_probe_contracts import ProbeSnapshot
from scripts.selftest.mcp_probe_evidence import DisposalReceipt, StackSnapshot

Fault = Literal[
    "bad_json",
    "bad_version",
    "oversized_field",
    "timeout",
    "pipe_break",
    "socket_break",
    "server_crash",
    "unknown_mutation",
    "inactive_account_creator",
]


class FaultGolden(Contract):
    rpc_error_code: StrictInt | None = None
    transport_error: Literal["remote_protocol_error"] | None = None
    server_http_status: StrictInt | None = Field(default=None, ge=100, le=599)
    server_rpc_error: StrictInt | None = None
    tool_error: StrictBool | None = None
    business_code: Identity | None = None
    text_marker: Literal["invalid_arguments"] | None = None
    trace_required: StrictBool = False
    sdk_complete: StrictBool = False
    mutation_count: Literal[0, 1] = 0
    server_killed: StrictBool = False


class FaultScenario(Contract):
    scenario_id: Identity
    acceptance_id: Literal["ST-MCP-004", "ST-MCP-007", "ST-MCP-008"]
    variant_key: Identity
    transport: Transport
    fault: Fault
    expected: FaultGolden


class FaultPack(Contract):
    schema_version: Literal["flowtest-mcp-transport-fault-v1"]
    pack_id: Literal["mcp-transport-fault-v1"]
    pack_version: Literal["1.0.1"]
    sdk_version: Literal["2.2.0"]
    max_requests: Literal[500]
    max_tool_calls: Literal[100]
    max_runtime_seconds: Literal[600]
    normalized_design_digest: Sha256
    proposed_source_fingerprint: Sha256
    catalog_fingerprint: Sha256
    tool_names: tuple[Identity, ...] = Field(min_length=1, max_length=300)
    scenarios: tuple[FaultScenario, ...] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def exact_scope(self) -> "FaultPack":
        ids = [r.scenario_id for r in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("传输故障场景集合不能重复")
        return self


class FrozenCall(Contract):
    scenario_id: Identity
    tool_name: Identity
    arguments_digest: Sha256


class FaultManifest(Contract):
    batch_key: Identity
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    pack_digest: Sha256
    source_digest: Sha256
    created_at: AwareDatetime
    expires_at: AwareDatetime
    project_id: UUID
    owner_user_id: UUID
    writer_machine_id: UUID
    inactive_creator_id: UUID
    inactive_machine_id: UUID
    scenarios: tuple[FaultScenario, ...] = Field(min_length=1, max_length=30)
    calls: tuple[FrozenCall, ...] = Field(min_length=1, max_length=30)
    claim: Literal["transport_fault_negative_only"] = "transport_fault_negative_only"
    trust: Literal["local_untrusted"] = "local_untrusted"

    @model_validator(mode="after")
    def exact_denominator(self) -> "FaultManifest":
        ids = [r.scenario_id for r in self.scenarios]
        calls = [r.scenario_id for r in self.calls]
        if not ids or len(ids) != len(set(ids)) or calls != ids:
            raise ValueError("故障分母与预先冻结请求必须精确对应")
        if not 0 < (self.expires_at - self.created_at).total_seconds() <= 600:
            raise ValueError("故障批次期限不能超过600秒")
        if (
            self.inactive_creator_id == self.owner_user_id
            or self.inactive_machine_id == self.writer_machine_id
        ):
            raise ValueError("停用fixture不能复用正常写入身份")
        return self


class ProcessIdentity(Contract):
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    pid: StrictInt = Field(ge=1)
    start_ticks: str = Field(pattern=r"^[0-9]+$")


class ProcessRemovalProof(Contract):
    process: ProcessIdentity
    removed: Literal[True]
    observed_at: AwareDatetime


class DispatchReceipt(Contract):
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    observed_at: AwareDatetime
    request_id: RpcId
    tool_name: Identity
    arguments_digest: Sha256
    sdk_frame_digest: Sha256
    forwarded_digest: Sha256
    forwarded_bytes: StrictInt = Field(ge=1, le=262144)
    forwarded_count: Literal[1]
    response_digest: Sha256 | None = None
    response_result_digest: Sha256 | None = None
    response_id: RpcId | None = None
    server_http_status: StrictInt | None = Field(default=None, ge=100, le=599)
    server_rpc_error: StrictInt | None = None
    proposal_id: UUID | None = None
    fault_applied: StrictBool
    process: ProcessIdentity | None = None
    server_killed: StrictBool = False
    process_cleanup_complete: StrictBool
    removal: ProcessRemovalProof | None = None


class FaultResult(Contract):
    trace_present: StrictBool = False
    complete: StrictBool
    rpc_error_code: StrictInt | None = None
    transport_error: Literal["remote_protocol_error"] | None = None
    tool_error: StrictBool | None = None
    business_code: Identity | None = None
    text_marker: Literal["invalid_arguments"] | None = None
    result_digest: Sha256 | None = None


class FrameReceipt(Contract):
    request_id: RpcId
    frame_digest: Sha256


class FaultObservation(Contract):
    scenario_id: Identity
    transport: Transport
    sdk_version: Literal["2.2.0"]
    started_at: AwareDatetime
    completed_at: AwareDatetime
    catalog_fingerprint: Sha256
    tool_names: tuple[Identity, ...] = Field(min_length=1, max_length=300)
    requests: tuple[RpcRequest, ...] = Field(min_length=1, max_length=10)
    responses: tuple[RpcResponse, ...] = Field(max_length=10)
    frames: tuple[FrameReceipt, ...] = Field(min_length=1, max_length=10)
    dispatch: DispatchReceipt
    result: FaultResult
    before: ProbeSnapshot
    after: ProbeSnapshot

    @model_validator(mode="after")
    def aware_wire_times(self) -> "FaultObservation":
        times = [r.observed_at for r in self.requests] + [r.observed_at for r in self.responses]
        if any(value.tzinfo is None or value.utcoffset() is None for value in times):
            raise ValueError("线缆回执时间必须有时区")
        return self


class InactiveFixture(Contract):
    creator_id: UUID
    machine_id: UUID
    creator_is_active: Literal[False]
    machine_enabled: Literal[True]
    machine_revoked: Literal[False]
    user_response_digest: Sha256
    account_response_digest: Sha256
    mechanism: Literal["public_user_patch_and_service_account_list"]


class FaultEvidence(Contract):
    batch_key: Identity
    nonce: Identity
    pack_digest: Sha256
    source_digest: Sha256
    manifest_digest: Sha256
    authority_digest: Sha256
    stack: StackSnapshot
    inactive_fixture: InactiveFixture
    scenarios: tuple[FaultObservation, ...] = Field(max_length=30)
    http_admitted: StrictInt = Field(ge=0, le=500)
    http_rejected: StrictInt = Field(ge=0)
    tools_admitted: StrictInt = Field(ge=0, le=100)
    tools_rejected: StrictInt = Field(ge=0)
    process_cleanup_complete: StrictBool
    disposal_receipt: DisposalReceipt | None
    collected_at: AwareDatetime
    claim: Literal["transport_fault_negative_only"] = "transport_fault_negative_only"
    trust: Literal["local_untrusted"] = "local_untrusted"
