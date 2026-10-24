"""Independent host-trail checks. Structured tool failures never become successes."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from pydantic import Field
from scripts.selftest.contracts import (
    BatchManifest,
    Contract,
    Finding,
    HostEvidence,
    McpCallReceipt,
    ScenarioExpectation,
    ScenarioObservation,
    Sha256,
    canonical_digest,
)
from scripts.selftest.host_contracts import HostStopReceipt, HostToolReceipt
from scripts.selftest.host_launch import VerifiedGrant
from scripts.selftest.host_repairs import RepairProof
from scripts.selftest.host_runner import ProcessReceipt
from scripts.selftest.verify_generation_provenance import verify_generation_provenance


class HostFrozenTrail(Contract):
    authorization_digest: Sha256
    task_digest: Sha256
    host: HostEvidence
    catalog_digest: Sha256
    receipts: tuple[HostToolReceipt, ...] = Field(min_length=1, max_length=100)
    repairs: tuple[RepairProof, ...] = Field(default=(), max_length=20)
    phases: tuple[ProcessReceipt, ProcessReceipt]
    stop: HostStopReceipt | None = None


def verify_host_trail(
    trail: HostFrozenTrail, grant: VerifiedGrant, calls: tuple[McpCallReceipt, ...]
) -> tuple[str, ...]:
    auth, host = grant.authorization, trail.host
    if trail.stop is not None:
        return ("HOST_STOPPED_ATTEMPT",)
    identity = (
        trail.authorization_digest == grant.digest,
        trail.task_digest == auth.task_digest,
        host.authorized_budget_digest == grant.digest,
        host.host == auth.host_id,
        host.model == auth.model,
        host.skill_digest == auth.skill_digest,
        host.actual_tool_calls == len(trail.receipts) == len(calls),
        len(calls) <= auth.budget.maximum_tool_calls,
        len({item.attempt_id for item in trail.receipts}) == 1,
        all(
            item.started_at.tzinfo is not None
            and item.completed_at is not None
            and item.completed_at.tzinfo is not None
            and auth.approved_at <= item.started_at <= item.completed_at <= auth.expires_at
            for item in trail.receipts
        ),
        all(
            process.started_at.tzinfo is not None
            and process.completed_at.tzinfo is not None
            and auth.approved_at <= process.started_at <= process.completed_at <= auth.expires_at
            for process in trail.phases
        ),
        trail.phases[1].completed_at
        <= trail.phases[0].started_at + timedelta(seconds=auth.budget.wall_seconds),
    )
    if not all(identity):
        return ("HOST_AUTHORIZATION_OR_CALL_SET_MISMATCH",)
    findings = []
    for index, (receipt, call) in enumerate(zip(trail.receipts, calls, strict=True), start=1):
        if (receipt.tool_name == "flowtest.propose_test_design" and receipt.phase != "case") or (
            receipt.tool_name in {"flowtest.propose_flow_draft", "flowtest.propose_simple_flow"}
            and receipt.phase != "workflow"
        ):
            findings.append("HOST_TOOL_PHASE_MISMATCH")
        if not _same_call(trail, receipt, call, index):
            findings.append("HOST_CALL_RECEIPT_MISMATCH")
        if (
            receipt.outcome != "completed" or receipt.business_success is not True
        ) and not _repair_allowed(trail, grant, receipt):
            findings.append("HOST_UNKNOWN_OR_UNRESOLVED_TOOL_FAILURE")
    findings.extend(_phase_findings(trail))
    return tuple(dict.fromkeys(findings))


def _same_call(
    trail: HostFrozenTrail, receipt: HostToolReceipt, call: McpCallReceipt, index: int
) -> bool:
    return (
        receipt.sequence == index
        and call.call_id == f"host-{receipt.attempt_id}-{index}"
        and receipt.phase == call.phase
        and receipt.tool_name == call.tool_name
        and receipt.request_digest == call.request_digest
        and receipt.result_digest == call.result_digest
        and receipt.catalog_digest == call.catalog_digest == trail.catalog_digest
        and call.completed_at == receipt.completed_at
        and call.success == (receipt.business_success is True)
    )


def _repair_allowed(trail: HostFrozenTrail, grant: VerifiedGrant, receipt: HostToolReceipt) -> bool:
    if receipt.outcome != "completed" or receipt.resolved_by is None:
        return False
    policies = [
        item
        for item in grant.authorization.read_only_repairs
        if item.tool_name == receipt.tool_name and receipt.error_code in item.error_codes
    ]
    proofs = [item for item in trail.repairs if item.failed_sequence == receipt.sequence]
    if len(policies) != 1 or len(proofs) != 1:
        return False
    policy, proof = policies[0], proofs[0]
    resolved = [item for item in trail.receipts if item.sequence == proof.resolved_sequence]
    return (
        len(resolved) == 1
        and resolved[0].tool_name == receipt.tool_name
        and resolved[0].outcome == "completed"
        and resolved[0].business_success is True
        and proof.resolved_sequence == receipt.resolved_by > receipt.sequence
        and proof.error_code == receipt.error_code
        and proof.tool_name == receipt.tool_name
        and bool(proof.changed_fields)
        and set(proof.changed_fields) <= set(policy.allowed_argument_fields)
        and proof.policy_digest == canonical_digest(policy.model_dump(mode="json"))
    )


def _phase_findings(trail: HostFrozenTrail) -> tuple[str, ...]:
    findings = []
    prompt = canonical_digest(
        {"workflow": trail.phases[0].prompt_digest, "case": trail.phases[1].prompt_digest}
    )
    if prompt != trail.host.prompt_digest or any(
        process.authorization_digest != trail.authorization_digest for process in trail.phases
    ):
        findings.append("HOST_PROCESS_PROMPT_OR_AUTHORIZATION_CHANGED")
    for phase, process in zip(("workflow", "case"), trail.phases, strict=True):
        if (
            process.exit_code != 0
            or process.reason_code
            or process.summary is None
            or process.summary.phase != phase
            or process.summary.status != "waiting_for_review"
        ):
            findings.append("HOST_PROCESS_NOT_COMPLETED_FOR_REVIEW")
        started = [
            (event.tool_name, event.request_digest)
            for event in process.events
            if event.event_type == "item.started" and event.item_type == "mcp_tool_call"
        ]
        expected = [
            (receipt.tool_name, receipt.request_digest)
            for receipt in trail.receipts
            if receipt.phase == phase
        ]
        if Counter(started) != Counter(expected):
            findings.append("HOST_EVENT_CALL_SET_MISMATCH")
    return tuple(findings)


def verify_host_generation_provenance(
    manifest: BatchManifest,
    expected: ScenarioExpectation,
    observed: ScenarioObservation,
    *,
    trail: HostFrozenTrail,
    grant: VerifiedGrant,
) -> tuple[Finding, ...]:
    """Retain all general source checks; only explicit, proven read repairs are distinct."""
    source = observed.provenance
    if source is None:
        return (Finding(code="HOST_SOURCE_MISSING", status="incomplete", message="缺少宿主来源"),)
    reasons = list(verify_host_trail(trail, grant, source.calls))
    if (
        manifest.generation_mode != "host_llm_mcp"
        or source.generation_mode != "host_llm_mcp"
        or source.host != trail.host
        or manifest.project_id != grant.authorization.project_id
        or manifest.batch_key != grant.authorization.batch_key
    ):
        reasons.append("HOST_FROZEN_SOURCE_IDENTITY_CHANGED")
    general = verify_generation_provenance(manifest, expected, observed)
    if reasons:
        return (
            *general,
            *(
                Finding(
                    code=code,
                    status="mismatched",
                    message="宿主授权、完整调用轨迹或独立修复证明不符",
                )
                for code in dict.fromkeys(reasons)
            ),
        )
    # An allowed read error remains success=False. No raw status, source or Oracle is rewritten.
    return tuple(finding for finding in general if finding.code != "MCP_RECEIPT_RESULT_INVALID")
