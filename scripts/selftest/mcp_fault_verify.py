"""Independent fault oracle: raw SDK failure, exact dispatch and read-only state delta."""

from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import Element, SubElement, tostring

from pydantic import ValidationError
from scripts.selftest.contracts import Contract, Identity, canonical_digest
from scripts.selftest.io import HarnessError, JsonObject, read_json, write_json
from scripts.selftest.mcp_fault_contracts import (
    FaultEvidence,
    FaultManifest,
    FaultObservation,
    FaultPack,
    FaultScenario,
)
from scripts.selftest.mcp_governance_verify import Finding, Verdict, failure
from scripts.selftest.mcp_probe_contracts import ProbeAuthority, ProbeResource
from scripts.selftest.mcp_probe_reader import validate_snapshot

ROOT = Path(__file__).resolve().parents[2]
PACK_PATH = ROOT / "selftest/packs/mcp-transport-fault-v1/pack.json"


class FaultReport(Contract):
    batch_key: Identity
    exit_code: Literal[0, 1, 2]
    findings: tuple[Finding, ...]
    scenarios: tuple[Verdict, ...]
    claim: Literal["transport_fault_negative_only"] = "transport_fault_negative_only"
    trust: Literal["local_untrusted"] = "local_untrusted"


def _frozen_arguments(manifest: FaultManifest, scenario: FaultScenario) -> tuple[str, JsonObject]:
    if scenario.fault == "unknown_mutation":
        return "flowtest.propose_test_design", {
            "project_id": str(manifest.project_id),
            "idempotency_key": manifest.batch_key + ":" + scenario.scenario_id,
            "dry_run": False,
            "title": "一次未知结果故障提案",
            "confidence": 1.0,
            "risk_level": "low",
            "test_cases": [],
            "design": {
                "intent": {
                    "key": "synthetic.governance",
                    "objective": "合成治理验证, 不执行发布运行",
                    "acceptance_criteria": ["只允许已批准草稿"],
                },
                "oracles": [
                    {
                        "id": "status",
                        "kind": "status",
                        "expression": "$.status",
                        "operator": "equals",
                        "expected": 200,
                        "confidence": 1.0,
                    }
                ],
            },
        }
    return "flowtest.inspect_connection", {
        "request": {"expected_contract_version": "x" * 81}
        if scenario.fault == "oversized_field"
        else {}
    }


def _identity(
    manifest: FaultManifest, evidence: FaultEvidence, authority: ProbeAuthority
) -> list[Finding]:
    findings: list[Finding] = []
    identity_fields = ("batch_key", "nonce", "pack_digest", "source_digest", "claim", "trust")
    if any(getattr(manifest, key) != getattr(evidence, key) for key in identity_fields):
        findings.append(failure("FAULT_BATCH_IDENTITY_MISMATCH"))
    digest = canonical_digest(manifest.model_dump(mode="json"))
    if digest != evidence.manifest_digest or digest != authority.manifest_digest:
        findings.append(failure("FAULT_MANIFEST_BINDING_MISMATCH"))
    if evidence.authority_digest != canonical_digest(authority.model_dump(mode="json")):
        findings.append(failure("FAULT_AUTHORITY_BINDING_MISMATCH"))
    stack = evidence.stack
    if (
        canonical_digest(stack.model_dump(mode="json", exclude={"runner_container_id"}))
        != authority.binding_fingerprint
    ):
        findings.append(failure("FAULT_STACK_BINDING_MISMATCH"))
    if (
        stack.source_digest,
        stack.runtime_profile,
        stack.candidate_image_digest,
        stack.fixture_image_digest.removeprefix("sha256:"),
    ) != (
        manifest.source_digest,
        authority.runtime_profile,
        authority.builds.runner,
        authority.builds.fixture,
    ) or authority.builds.target != authority.builds.runner:
        findings.append(failure("FAULT_BUILD_SOURCE_MISMATCH"))
    if authority.source_digest != manifest.source_digest:
        findings.append(failure("FAULT_AUTHORITY_SOURCE_MISMATCH"))
    if (
        authority.probe_id.hex,
        authority.issued_at,
        authority.expires_at,
        authority.fixtures[0].project_id,
        authority.owner_user_id,
    ) != (
        manifest.nonce,
        manifest.created_at,
        manifest.expires_at,
        manifest.project_id,
        manifest.owner_user_id,
    ):
        findings.append(failure("FAULT_AUTHORITY_SCOPE_MISMATCH"))
    if not {manifest.writer_machine_id, manifest.inactive_machine_id} <= set(
        authority.machine_account_ids
    ):
        findings.append(failure("FAULT_MACHINE_SCOPE_MISMATCH"))
    if (evidence.inactive_fixture.creator_id, evidence.inactive_fixture.machine_id) != (
        manifest.inactive_creator_id,
        manifest.inactive_machine_id,
    ):
        findings.append(failure("FAULT_INACTIVE_FIXTURE_BINDING_MISMATCH"))
    return findings


def _batch(manifest: FaultManifest, evidence: FaultEvidence, now: datetime) -> list[Finding]:
    findings: list[Finding] = []
    if not manifest.created_at <= evidence.collected_at <= now < manifest.expires_at:
        findings.append(failure("FAULT_EVIDENCE_EXPIRED_OR_TIME_MISMATCH", True))
    if not evidence.process_cleanup_complete or evidence.http_rejected or evidence.tools_rejected:
        findings.append(failure("FAULT_BUDGET_OR_PROCESS_CLEANUP_INCOMPLETE", True))
    actual_tools = sum(
        request.method == "tools/call" for row in evidence.scenarios for request in row.requests
    )
    if (
        evidence.tools_admitted != len(manifest.scenarios)
        or actual_tools != evidence.tools_admitted
        or evidence.http_admitted < actual_tools
    ):
        findings.append(failure("FAULT_EXACT_ATTEMPT_COUNT_MISMATCH"))
    if evidence.disposal_receipt is None:
        findings.append(failure("OWNED_ASSET_DISPOSAL_PENDING", True))
    else:
        receipt, stack = evidence.disposal_receipt, evidence.stack
        if (
            receipt.project_name,
            receipt.binding_nonce,
            receipt.runner_volume,
            receipt.target_volume,
            receipt.candidate_image_digest,
        ) != (
            stack.project_name,
            stack.nonce,
            stack.runner_volume,
            stack.target_volume,
            stack.candidate_image_digest,
        ) or not evidence.collected_at <= receipt.removed_at <= min(manifest.expires_at, now):
            findings.append(failure("FAULT_DISPOSAL_BINDING_MISMATCH"))
    return findings


def _wire_shape(row: FaultObservation) -> list[Finding]:
    ids = [canonical_digest(r.id) for r in row.requests]
    replies = [canonical_digest(r.id) for r in row.responses]
    frames = [canonical_digest(r.request_id) for r in row.frames]
    if tuple(r.method for r in row.requests) != ("server/discover", "tools/list", "tools/call"):
        return [failure("FAULT_EXACT_RPC_SEQUENCE_MISMATCH")]
    if (
        len(ids) != len(set(ids))
        or len(replies) != len(set(replies))
        or frames != ids
        or set(replies) - set(ids)
    ):
        return [failure("FAULT_DUPLICATE_OR_MISSING_RPC_RECEIPT", True)]
    if len({r.session_id for r in row.requests}) != 1 or any(
        r.session_id != row.requests[0].session_id for r in row.responses
    ):
        return [failure("FAULT_RPC_SESSION_MISMATCH")]
    times = [r.observed_at for r in row.requests] + [r.observed_at for r in row.responses]
    if any(not row.started_at <= observed <= row.completed_at for observed in times):
        return [failure("FAULT_RPC_RECEIPT_TIME_MISMATCH")]
    first = {canonical_digest(r.id) for r in row.requests[:2]}
    if {canonical_digest(r.id) for r in row.responses if r.error_code is None} & first != first:
        return [failure("FAULT_DISCOVERY_OR_CATALOG_RESPONSE_MISSING", True)]
    return []


def _attempt_identities(evidence: FaultEvidence) -> list[Finding]:
    nonces = [row.dispatch.nonce for row in evidence.scenarios]
    processes = [
        (row.dispatch.process.nonce, row.dispatch.process.pid, row.dispatch.process.start_ticks)
        for row in evidence.scenarios
        if row.dispatch.process is not None
    ]
    findings: list[Finding] = []
    if len(nonces) != len(set(nonces)) or len(processes) != len(set(processes)):
        findings.append(failure("FAULT_REUSED_PROCESS_OR_ATTEMPT_IDENTITY"))
    if any(row.completed_at > evidence.collected_at for row in evidence.scenarios):
        findings.append(failure("FAULT_COLLECTION_BEFORE_ATTEMPT_COMPLETED"))
    return findings


def _golden(pack: FaultPack) -> list[Finding]:
    design = read_json(PACK_PATH.with_name("normalized-design.golden.json"))
    source: JsonObject = {
        "schema_version": "s42-test-design-v1",
        "source_ref": "mcp://controlled-writes/pending",
        "design": design,
        "test_cases": [],
        "governance": {
            "confidence": 1.0,
            "risk_level": "low",
            "requires_review": True,
            "manual_approval_required": False,
            "reason_codes": ["controlled_write_draft_only"],
        },
    }
    if (
        canonical_digest(design) != pack.normalized_design_digest
        or canonical_digest(source) != pack.proposed_source_fingerprint
    ):
        return [failure("FAULT_FROZEN_NORMALIZED_GOLDEN_MISMATCH")]
    return []


def _wire(manifest: FaultManifest, scenario: FaultScenario, row: FaultObservation) -> list[Finding]:
    calls = [r for r in row.requests if r.method == "tools/call"]
    if len(calls) != 1:
        return [failure("FAULT_SINGLE_DISPATCH_RECEIPT_REQUIRED", True)]
    request = calls[0]
    frames = [
        r for r in row.frames if canonical_digest(r.request_id) == canonical_digest(request.id)
    ]
    expected = next(r for r in manifest.calls if r.scenario_id == scenario.scenario_id)
    tool, args = _frozen_arguments(manifest, scenario)
    dispatch = row.dispatch
    if (
        not max(page.observed_at for page in row.before.pages)
        <= request.observed_at
        <= dispatch.observed_at
        <= min(page.observed_at for page in row.after.pages)
    ):
        return [failure("FAULT_DISPATCH_OBSERVATION_ORDER_MISMATCH")]
    if (expected.tool_name, expected.arguments_digest) != (tool, canonical_digest(args)):
        return [failure("FAULT_FROZEN_REQUEST_MUTATED")]
    if (
        request.tool_name,
        request.arguments_digest,
        dispatch.tool_name,
        dispatch.arguments_digest,
    ) != (tool, expected.arguments_digest, tool, expected.arguments_digest) or canonical_digest(
        request.id
    ) != canonical_digest(dispatch.request_id):
        return [failure("FAULT_WIRE_REQUEST_BINDING_MISMATCH")]
    if len(frames) != 1 or frames[0].frame_digest != dispatch.sdk_frame_digest:
        return [failure("FAULT_FRAME_RECEIPT_MISSING_OR_MISMATCH", True)]
    if scenario.fault == "bad_json":
        valid = (
            dispatch.forwarded_bytes == 1
            and dispatch.forwarded_digest == hashlib.sha256(b"{").hexdigest()
        )
    else:
        valid = (
            scenario.fault == "bad_version"
            or dispatch.forwarded_digest == dispatch.sdk_frame_digest
        )
    return [] if valid else [failure("FAULT_FORWARDED_FRAME_MISMATCH")]


def _result(scenario: FaultScenario, row: FaultObservation) -> list[Finding]:
    expected, actual, dispatch = scenario.expected, row.result, row.dispatch
    fields = ("rpc_error_code", "transport_error", "tool_error", "business_code", "text_marker")
    if actual.complete != expected.sdk_complete or any(
        getattr(actual, key) != getattr(expected, key) for key in fields
    ):
        return [failure("FAULT_RAW_SDK_RESULT_MISMATCH")]
    if expected.trace_required and not actual.trace_present:
        return [failure("FAULT_REQUIRED_ERROR_TRACE_MISSING")]
    if (
        expected.server_http_status is not None
        and dispatch.server_http_status != expected.server_http_status
    ):
        return [failure("FAULT_SERVER_HTTP_STATUS_MISMATCH")]
    if dispatch.server_rpc_error != expected.server_rpc_error:
        return [failure("FAULT_SERVER_RPC_LAYER_MISMATCH")]
    if (
        not dispatch.fault_applied
        or not dispatch.process_cleanup_complete
        or dispatch.server_killed != expected.server_killed
    ):
        return [failure("FAULT_NOT_APPLIED_OR_PROCESS_NOT_REMOVED", True)]
    if dispatch.process is None:
        return [failure("FAULT_ACTUAL_SERVER_KILL_RECEIPT_MISSING", True)]
    if (
        dispatch.removal is None
        or dispatch.removal.process != dispatch.process
        or not dispatch.observed_at <= dispatch.removal.observed_at <= row.completed_at
    ):
        return [failure("FAULT_EXACT_PROCESS_REMOVAL_RECEIPT_MISSING", True)]
    if scenario.transport == "stdio" and dispatch.process.nonce != dispatch.nonce:
        return [failure("FAULT_PROCESS_NONCE_MISMATCH")]
    return _reply(scenario, row)


def _reply(scenario: FaultScenario, row: FaultObservation) -> list[Finding]:
    expected, actual, dispatch = scenario.expected, row.result, row.dispatch
    calls = [r for r in row.requests if r.method == "tools/call"]
    replies = [
        r for r in row.responses if canonical_digest(r.id) == canonical_digest(dispatch.request_id)
    ]
    if actual.complete:
        valid = (
            len(replies) == 1
            and replies[0].result_digest == actual.result_digest == dispatch.response_result_digest
        )
    elif scenario.fault in {"bad_json", "bad_version"}:
        valid = (
            len(replies) == 1
            and replies[0].error_code == expected.rpc_error_code
            and dispatch.response_id is None
        )
    else:
        valid = not replies and len(calls) == 1 and dispatch.response_digest is not None
    return [] if valid else [failure("FAULT_RAW_WIRE_RESPONSE_MISMATCH")]


def _design(pack: FaultPack, resource: ProbeResource) -> bool:
    if len(resource.items) != 1:
        return False
    item = resource.items[0]
    design = item.design
    if design is None or len(design.oracles) != 1:
        return False
    oracle = design.oracles[0]
    return (
        (
            item.item_type,
            item.action,
            item.review_status,
            item.reviewed_by_id,
            item.materialized_resource_id,
            item.materialized_resource_type,
        )
        == ("test_design", "create", "pending", None, None, None)
        and item.proposed_document_digest == design.document_digest == pack.normalized_design_digest
        and (design.intent_key_digest, design.objective_digest)
        == (
            canonical_digest("synthetic.governance"),
            canonical_digest("合成治理验证, 不执行发布运行"),
        )
        and (
            oracle.id,
            oracle.kind,
            oracle.expression_digest,
            oracle.operator,
            oracle.expected_digest,
        )
        == ("status", "status", canonical_digest("$.status"), "equals", canonical_digest(200))
    )


def _delta(
    manifest: FaultManifest, pack: FaultPack, scenario: FaultScenario, row: FaultObservation
) -> list[Finding]:
    before = {(r.kind, r.id): r for r in row.before.resources}
    after = {(r.kind, r.id): r for r in row.after.resources}
    if any(after.get(key) != value for key, value in before.items()):
        return [failure("FAULT_EXISTING_RESOURCE_CHANGED")]
    added = [value for key, value in after.items() if key not in before]
    if not scenario.expected.mutation_count:
        return (
            []
            if not added and row.dispatch.proposal_id is None
            else [failure("FAULT_UNEXPECTED_SIDE_EFFECT")]
        )
    if len(added) != 1 or added[0].kind != "ai_change_set":
        return [failure("FAULT_UNKNOWN_MUTATION_EXACT_SET_MISMATCH")]
    proposal = added[0]
    if (
        proposal.id,
        proposal.project_id,
        proposal.status,
        proposal.created_by_id,
        proposal.actor_type,
        proposal.reviewed_by_id,
    ) != (
        row.dispatch.proposal_id,
        manifest.project_id,
        "draft",
        manifest.owner_user_id,
        "service_account",
        None,
    ) or proposal.fingerprint != pack.proposed_source_fingerprint:
        return [failure("FAULT_UNKNOWN_MUTATION_IDENTITY_MISMATCH")]
    return (
        []
        if _design(pack, proposal)
        else [failure("FAULT_UNKNOWN_MUTATION_FROZEN_DESIGN_MISMATCH")]
    )


def _row(
    manifest: FaultManifest,
    pack: FaultPack,
    authority: ProbeAuthority,
    scenario: FaultScenario,
    row: FaultObservation,
    now: datetime,
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    if (
        row.transport != scenario.transport
        or not manifest.created_at
        <= row.started_at
        <= row.completed_at
        <= evidence_time(manifest, now)
    ):
        findings.append(failure("FAULT_SCENARIO_IDENTITY_OR_TIME_MISMATCH"))
    if row.catalog_fingerprint != pack.catalog_fingerprint or row.tool_names != pack.tool_names:
        findings.append(failure("FAULT_CATALOG_MISMATCH"))
    for snapshot in (row.before, row.after):
        try:
            validate_snapshot(authority, snapshot, now=now)
        except HarnessError:
            findings.append(failure("FAULT_INDEPENDENT_SNAPSHOT_INCOMPLETE", True))
    findings.extend(_wire(manifest, scenario, row))
    findings.extend(_wire_shape(row))
    findings.extend(_result(scenario, row))
    findings.extend(_delta(manifest, pack, scenario, row))
    return tuple(findings)


def evidence_time(manifest: FaultManifest, now: datetime) -> datetime:
    return min(manifest.expires_at, now)


def verify(
    manifest: FaultManifest,
    evidence: FaultEvidence,
    authority: ProbeAuthority,
    *,
    now: datetime | None = None,
) -> FaultReport:
    current = now or datetime.now(UTC)
    raw = read_json(PACK_PATH)
    pack = FaultPack.model_validate(raw)
    findings = _golden(pack) + (
        _identity(manifest, evidence, authority)
        + _batch(manifest, evidence, current)
        + _attempt_identities(evidence)
    )
    if manifest.pack_digest != canonical_digest(raw) or manifest.scenarios != pack.scenarios:
        findings.append(failure("FAULT_FROZEN_PACK_MISMATCH"))
    rows = {r.scenario_id: r for r in evidence.scenarios}
    required = {s.scenario_id for s in manifest.scenarios}
    if len(rows) != len(evidence.scenarios) or set(rows) - required:
        findings.append(failure("FAULT_SCENARIO_SET_MISMATCH"))
    verdicts: list[Verdict] = []
    previous: tuple[ProbeResource, ...] = ()
    for scenario in manifest.scenarios:
        row = rows.get(scenario.scenario_id)
        errors = (
            (failure("FAULT_REQUIRED_SCENARIO_MISSING", True),)
            if row is None
            else _row(manifest, pack, authority, scenario, row, current)
        )
        if row is not None:
            if row.before.resources != previous:
                errors += (failure("FAULT_SNAPSHOT_CONTINUITY_MISMATCH"),)
            previous = row.after.resources
        status = (
            "incomplete"
            if any(f.status == "incomplete" for f in errors)
            else "mismatched"
            if errors
            else "matched"
        )
        verdicts.append(
            Verdict(scenario_id=scenario.scenario_id, verification_status=status, findings=errors)
        )
    statuses = {f.status for f in findings} | {f.status for r in verdicts for f in r.findings}
    code = 1 if "mismatched" in statuses else 2 if statuses else 0
    return FaultReport(
        batch_key=manifest.batch_key,
        exit_code=code,
        findings=tuple(findings),
        scenarios=tuple(verdicts),
    )


def write_reports(report: FaultReport, evidence: FaultEvidence | None, output: Path) -> None:
    write_json(output / "verification.json", report)
    raw = Element("testsuite", name="mcp-transport-fault-raw", tests=str(len(report.scenarios)))
    observed = {r.scenario_id: r for r in evidence.scenarios} if evidence else {}
    check = Element(
        "testsuite",
        name="mcp-transport-fault-verification",
        tests=str(len(report.scenarios) + bool(report.findings)),
    )
    if report.findings:
        batch = SubElement(check, "testcase", name="batch-global")
        SubElement(batch, "failure", message=",".join(f.code for f in report.findings))
    for row in report.scenarios:
        actual = observed.get(row.scenario_id)
        case = SubElement(raw, "testcase", name=row.scenario_id)
        if (
            actual is None
            or not actual.result.complete
            or actual.result.tool_error
            or actual.result.business_code is not None
        ):
            SubElement(case, "failure", message="raw SDK error or incomplete result")
        verified = SubElement(check, "testcase", name=row.scenario_id)
        if row.findings:
            SubElement(verified, "failure", message=",".join(f.code for f in row.findings))
    output.mkdir(parents=True, exist_ok=True)
    (output / "execution.junit.xml").write_bytes(tostring(raw, encoding="utf-8"))
    (output / "verification.junit.xml").write_bytes(tostring(check, encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="独立核验 MCP 真实传输故障证据")
    for field in ("manifest", "evidence", "authority", "output"):
        parser.add_argument("--" + field, type=Path, required=True)
    args = parser.parse_args()
    evidence = None
    try:
        manifest = FaultManifest.model_validate(read_json(args.manifest))
        evidence = FaultEvidence.model_validate(read_json(args.evidence))
        authority = ProbeAuthority.model_validate(read_json(args.authority))
        report = verify(manifest, evidence, authority)
    except (HarnessError, OSError, ValueError, ValidationError):
        report = FaultReport(
            batch_key="incomplete",
            exit_code=2,
            findings=(failure("FAULT_CONTRACT_INVALID", True),),
            scenarios=(),
        )
    write_reports(report, evidence, args.output)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
