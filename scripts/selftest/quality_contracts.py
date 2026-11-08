"""Frozen generation-quality and opaque-material boundary evidence."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, StrictInt
from scripts.selftest.contracts import Contract, McpCallReceipt, Sha256
from scripts.selftest.mcp_governance_contracts import Result
from scripts.selftest.mcp_probe_contracts import ProbeSnapshot
from scripts.selftest.mcp_probe_evidence import DisposalReceipt, StackSnapshot
from scripts.selftest.quality_case_contracts import QualityCaseResult

QualityAction = Literal[
    "positive_control",
    "empty_cases",
    "needs_review",
    "truncated",
    "coverage_missing",
    "prompt_injection",
    "scope",
    "target",
    "credential_ref",
]


class QualityScope(Contract):
    project_id: UUID
    fixture_environment_id: UUID
    fixture_service_id: UUID
    production_environment_id: UUID
    credential_ref: str


class QualityScenario(Contract):
    scenario_id: str
    acceptance_id: Literal["ST-MCP-013", "ST-MCP-016", "ST-MCP-027"]
    action: QualityAction
    transport: Literal["stdio", "streamable-http"]
    expected_readiness: Literal["ready", "incomplete", "needs_review"] | None = None
    expected_business_code: str | None = None


class QualityPack(Contract):
    pack_id: Literal["mcp-quality-boundaries-v1"]
    version: Literal["1.0.0"]
    sdk_version: Literal["2.2.0"]
    max_requests: Literal[500]
    max_tool_calls: Literal[100]
    max_runtime_seconds: Literal[600]
    scenarios: tuple[QualityScenario, ...] = Field(min_length=18, max_length=18)


class QualityManifest(Contract):
    batch_key: str
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    pack_digest: Sha256
    source_digest: Sha256
    scope: QualityScope
    writer_machine_id: UUID
    reader_machine_id: UUID
    created_at: AwareDatetime
    expires_at: AwareDatetime
    scenarios: tuple[QualityScenario, ...] = Field(min_length=18, max_length=18)
    calls: tuple["QualityCall", ...] = Field(min_length=8, max_length=8)
    claim: Literal["generation_quality_negative_only"] = "generation_quality_negative_only"
    trust: Literal["local_untrusted"] = "local_untrusted"


class QualityCall(Contract):
    scenario_id: str
    tool_name: str
    arguments_digest: Sha256


class CredentialEndpoint(Contract):
    id: UUID
    project_id: UUID
    environment_id: UUID
    service_id: UUID
    secret_ref_count: StrictInt = Field(ge=0)


class CredentialProjection(Contract):
    reference_count: StrictInt = Field(ge=0)
    verified: StrictBool
    sentinel_leaked: StrictBool
    result_digest: Sha256
    metadata_digest: Sha256
    endpoint: CredentialEndpoint


class QualityObservation(Contract):
    scenario_id: str
    started_at: AwareDatetime
    completed_at: AwareDatetime
    before: ProbeSnapshot
    after: ProbeSnapshot
    generated: QualityCaseResult | None = None
    result: Result | None = None
    credential: CredentialProjection | None = None
    attack_id: str | None = None
    calls: tuple[McpCallReceipt, ...] = Field(min_length=1, max_length=15)


class QualityEvidence(Contract):
    manifest_digest: Sha256
    authority_digest: Sha256
    stack: StackSnapshot
    observations: tuple[QualityObservation, ...] = Field(max_length=18)
    http_admitted: StrictInt = Field(ge=0, le=500)
    http_rejected: StrictInt = Field(ge=0)
    tool_attempts: StrictInt = Field(ge=0, le=100)
    tools_rejected: StrictInt = Field(ge=0)
    request_budget_mode: Literal["conservative_public_api_plus_sdk_and_candidate_rpc"] = (
        "conservative_public_api_plus_sdk_and_candidate_rpc"
    )
    protocol_cleanup_complete: StrictBool
    collected_at: AwareDatetime
    disposal: DisposalReceipt | None = None
