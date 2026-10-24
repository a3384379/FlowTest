"""Frozen, synthetic bad-target inputs and paired-run evidence; no product Oracle imports."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue
from scripts.selftest.contracts import (
    ApiSource,
    BatchEvidence,
    BatchManifest,
    Builds,
    Contract,
    DesignSource,
    FixtureBudgetScope,
    Identity,
    McpCallReceipt,
    OracleBinding,
    Sha256,
    VerificationReport,
    canonical_digest,
)
from scripts.selftest.io import HarnessError, JsonObject, read_json
from scripts.selftest.review_fixture_driver import ReviewedCase, ReviewedWorkflow

PACK_DIRECTORY = Path(__file__).resolve().parents[2] / "selftest/packs/mcp-badtargets-v1"
SCENARIOS = ("ST-BAD-business", "ST-BAD-dependency", "ST-BAD-auth")
type FaultKind = Literal["business_fault", "dependency_fault", "auth_fault"]


class BadTargetGolden(Contract):
    scenario_id: Identity
    fault_kind: FaultKind
    status: int = Field(ge=100, le=599)
    actual: int
    good_code: int
    bad_code: int
    good_value: JsonValue
    bad_value: JsonValue
    requests: int = Field(ge=1, le=2)
    schema_: JsonObject = Field(alias="schema")


class BadTargetsPack(Contract):
    pack_id: Literal["mcp-badtargets-v1"]
    version: Literal["1.0.0"]
    runtime_seconds: Literal[600]
    request_budget: Literal[500]
    tool_budget: Literal[100]
    scope: Literal["synthetic_target_fault_detection"]
    failure_code: Literal["WORKFLOW_ASSERTION_FAILED"]
    failure_phase: Literal["main"]
    failure_binding: Literal["consumer.schema"]
    positive_first: Literal[True]
    same_published_assets: Literal[True]
    auth_boundary: Literal["403_synthetic_response_leak_not_cross_tenant_authorization"]
    scenarios: tuple[BadTargetGolden, ...] = Field(min_length=3, max_length=3)

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json", by_alias=True))


def load_bad_targets_pack(directory: Path = PACK_DIRECTORY) -> BadTargetsPack:
    pack = BadTargetsPack.model_validate(read_json(directory / "pack.json"))
    if tuple(item.scenario_id for item in pack.scenarios) != SCENARIOS:
        raise HarnessError("SELFTEST_BADTARGET_DENOMINATOR_MISMATCH")
    if (
        tuple(item.fault_kind for item in pack.scenarios)
        != ("business_fault", "dependency_fault", "auth_fault")
        or sum(item.requests for item in pack.scenarios) != 4
    ):
        raise HarnessError("SELFTEST_BADTARGET_GOLDEN_MISMATCH")
    return pack


class BadOperation(Contract):
    purpose: Identity
    api_source: ApiSource
    operation_ref: Identity
    design: JsonObject
    origin: JsonObject
    design_fingerprint: Sha256
    scenario_id: Identity

    @property
    def source(self) -> DesignSource:
        return DesignSource(
            api_source=self.api_source,
            operation_ref=self.operation_ref,
            scenario_id=self.scenario_id,
            design_fingerprint=self.design_fingerprint,
        )


class BadAssertion(Contract):
    binding: OracleBinding
    kind: Literal["status", "schema"]
    purpose: Identity
    expected: JsonValue


class BadTargetAsset(Contract):
    scenario_id: Identity
    variant_key: FaultKind
    operations: tuple[BadOperation, ...] = Field(min_length=1, max_length=2)
    combined_design_fingerprint: Sha256 | None = None
    oracle_source: JsonObject
    oracle_source_kind: Literal["design", "integration_plan"]
    assertions: tuple[BadAssertion, ...] = Field(min_length=2, max_length=4)
    workflow: ReviewedWorkflow
    case: ReviewedCase
    calls: tuple[McpCallReceipt, ...] = Field(min_length=1, max_length=100)
    compilation_fingerprint: Sha256
    generated_at: datetime
    frozen_at: datetime

    @property
    def oracle_bindings(self) -> tuple[OracleBinding, ...]:
        return tuple(item.binding for item in self.assertions)


class NamespaceRegistration(Contract):
    scenario_id: Identity
    fixture_epoch: Identity
    registration_epoch: Identity


class BadTargetPhase(Contract):
    phase: Literal["positive", "fault"]
    registrations: tuple[NamespaceRegistration, ...] = Field(min_length=3, max_length=3)
    manifest: BatchManifest
    evidence: BatchEvidence
    report: VerificationReport


class BadTargetsAdmission(Contract):
    direct_http_attempts: int = Field(ge=0, le=392)
    tool_attempts: int = Field(ge=0, le=100)
    target_requests: int = Field(ge=0, le=8)
    max_requests: Literal[500] = 500
    max_seconds: Literal[600] = 600
    deadline: datetime


class BadTargetsResult(Contract):
    schema_version: Literal["flowtest-badtargets-v1"] = "flowtest-badtargets-v1"
    pack_digest: Sha256
    batch_key: Identity
    nonce: Identity
    builds: Builds
    frozen_at: datetime
    fixture_budget: FixtureBudgetScope
    expectations_frozen_at: datetime
    expectation_digests: tuple[Sha256, Sha256]
    phases: tuple[BadTargetPhase, ...] = Field(min_length=1, max_length=2)
    admission: BadTargetsAdmission
    provenance: Literal["local_untrusted"] = "local_untrusted"
    batch_verdict: Literal["passed", "failed", "blocked"]
    exit_code: Literal[0, 1, 2]
    reason_codes: tuple[Identity, ...] = ()
