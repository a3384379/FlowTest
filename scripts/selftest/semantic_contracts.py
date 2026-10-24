"""Frozen synthetic assertion-review rubric and its native execution receipts."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool
from scripts.selftest.contracts import (
    ApiSource,
    Builds,
    Contract,
    ExecutionEvidence,
    FixtureJournal,
    McpCallReceipt,
    OracleBinding,
    PlanRunSnapshot,
    ProposalEvidence,
    Sha256,
)
from scripts.selftest.io import JsonObject
from scripts.selftest.mcp_probe_evidence import DisposalReceipt, StackSnapshot
from scripts.selftest.start_plan import PlanSelection

SemanticVariant = Literal[
    "positive_control", "missing_assertion", "wrong_field", "wrong_operator", "expected_from_actual"
]


class SemanticRubric(Contract):
    status: Literal[200] = 200
    response_schema: JsonObject
    oracle_ids: tuple[str, str] = ("oracle_success_status", "oracle_response_schema_200")
    source_node_id: Literal["request"] = "request"
    expression: Literal["body"] = "body"
    operator: Literal["equals"] = "equals"
    assertion_type: Literal["json_schema"] = "json_schema"
    dynamic_expected_allowed: Literal[False] = False


class SemanticArtifact(Contract):
    variant: SemanticVariant
    api_source: ApiSource
    design: JsonObject
    design_fingerprint: Sha256
    compilation_fingerprint: Sha256
    oracle_bindings: tuple[OracleBinding, ...]
    definition: JsonObject
    definition_digest: Sha256
    workflow_id: UUID
    workflow_version_id: UUID
    workflow_version: int
    workflow_fingerprint: Sha256
    case_id: UUID
    case_version: int
    environment_id: UUID
    workflow_proposal: ProposalEvidence
    case_proposal: ProposalEvidence
    calls: tuple[McpCallReceipt, ...]
    frozen_at: AwareDatetime


class SemanticManifest(Contract):
    schema_version: Literal["flowtest-semantic-review-v1"] = "flowtest-semantic-review-v1"
    batch_key: str
    pack_id: Literal["mcp-semantic-review-v1"] = "mcp-semantic-review-v1"
    pack_digest: Sha256
    transport: Literal["stdio", "streamable-http"]
    nonce: str
    builds: Builds
    stack: StackSnapshot
    rubric: SemanticRubric
    artifacts: tuple[SemanticArtifact, ...] = Field(min_length=5, max_length=5)
    selection: PlanSelection
    fixture_epoch: str
    created_at: AwareDatetime
    expires_at: AwareDatetime
    claim: Literal["semantic_review_negative_only"] = "semantic_review_negative_only"
    trust: Literal["local_untrusted"] = "local_untrusted"


class SemanticObservation(Contract):
    variant: SemanticVariant
    execution: ExecutionEvidence
    run: PlanRunSnapshot
    source_plan_run_item_id: UUID
    source_case_id: UUID
    complete: StrictBool


class SemanticEvidence(Contract):
    manifest_digest: Sha256
    observations: tuple[SemanticObservation, ...] = Field(max_length=5)
    journal: FixtureJournal
    cleanup_completed: StrictBool
    tool_attempts: int = Field(ge=0, le=100)
    direct_http_attempts: int = Field(ge=0, le=392)
    tool_receipts: tuple[McpCallReceipt, ...] = Field(max_length=100)
    collected_at: AwareDatetime
    disposal: DisposalReceipt | None = None


class SemanticVerdict(Contract):
    variant: SemanticVariant
    raw_status: str | None
    source_rejected: bool
    reason_codes: tuple[str, ...]


class SemanticReport(Contract):
    batch_key: str
    exit_code: Literal[0, 1, 2]
    reason_codes: tuple[str, ...]
    scenarios: tuple[SemanticVerdict, ...]
    claim: Literal["semantic_review_negative_only"] = "semantic_review_negative_only"
    trust: Literal["local_untrusted"] = "local_untrusted"
