"""Independent frozen review/recovery oracle, with separate diagnostic JUnit."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, get_args

from scripts.selftest.boundary_reporting import write_boundary_junit
from scripts.selftest.contracts import Contract, canonical_digest
from scripts.selftest.io import (
    HarnessError,
    object_value,
    objects_value,
    read_json,
    write_json,
)
from scripts.selftest.mcp_governance_verify import Finding, Verdict, failure
from scripts.selftest.mcp_probe_contracts import ProbeAuthority, ProbeResource
from scripts.selftest.review_boundary_checks import http_outcomes, receipts, snapshots
from scripts.selftest.review_boundary_contracts import (
    ReviewAction,
    ReviewEvidence,
    ReviewManifest,
    ReviewObservation,
    ReviewScenario,
    ReviewSource,
    ReviewTransport,
)
from scripts.selftest.review_boundary_preview_verify import verify_preview
from scripts.selftest.review_boundary_requests import http_bindings

PACK_PATH = Path(__file__).resolve().parents[2] / "selftest/packs/mcp-review-recovery-v1/pack.json"


class ReviewReport(Contract):
    batch_key: str
    exit_code: Literal[0, 1, 2]
    findings: tuple[Finding, ...]
    scenarios: tuple[Verdict, ...]
    claim: Literal["review_recovery_and_preview_only"] = "review_recovery_and_preview_only"
    trust: Literal["local_untrusted"] = "local_untrusted"


def _identity(
    manifest: ReviewManifest, evidence: ReviewEvidence, authority: ProbeAuthority
) -> tuple[Finding, ...]:
    digest = canonical_digest(manifest.model_dump(mode="json"))
    if (
        digest != evidence.manifest_digest
        or digest != authority.manifest_digest
        or evidence.authority_digest != canonical_digest(authority.model_dump(mode="json"))
    ):
        return (failure("REVIEW_AUTHORITY_OR_MANIFEST_BINDING_MISMATCH"),)
    stack = evidence.stack
    if (
        canonical_digest(stack.model_dump(mode="json", exclude={"runner_container_id"}))
        != authority.binding_fingerprint
    ):
        return (failure("REVIEW_STACK_BINDING_MISMATCH"),)
    if (
        (
            stack.source_digest,
            stack.runtime_profile,
            stack.candidate_image_digest,
            stack.fixture_image_digest.removeprefix("sha256:"),
        )
        != (
            manifest.source_digest,
            authority.runtime_profile,
            authority.builds.runner,
            authority.builds.fixture,
        )
        or authority.builds.target != authority.builds.runner
        or authority.source_digest != manifest.source_digest
    ):
        return (failure("REVIEW_SOURCE_BUILD_MISMATCH"),)
    if (
        manifest.nonce,
        manifest.created_at,
        manifest.expires_at,
        manifest.scope.project_id,
        manifest.reviewer_id,
    ) != (
        authority.probe_id.hex,
        authority.issued_at,
        authority.expires_at,
        authority.fixtures[0].project_id,
        authority.reviewer_user_id,
    ) or manifest.writer_machine_id not in authority.machine_account_ids:
        return (failure("REVIEW_IDENTITY_OR_REVIEWER_SCOPE_MISMATCH"),)
    return ()


def _batch(
    manifest: ReviewManifest, evidence: ReviewEvidence, current: datetime
) -> tuple[Finding, ...]:
    findings = []
    raw = read_json(PACK_PATH)
    expected = tuple(
        ("REVIEW-" + action + "-" + transport, action, transport)
        for transport in get_args(ReviewTransport)
        for action in get_args(ReviewAction)
    )
    if (
        manifest.pack_digest != canonical_digest(raw)
        or tuple((r.scenario_id, r.action, r.transport) for r in manifest.scenarios) != expected
    ):
        findings.append(failure("REVIEW_FROZEN_DENOMINATOR_MISMATCH"))
    if (
        not manifest.created_at <= evidence.collected_at <= current < manifest.expires_at
        or not 0 < (manifest.expires_at - manifest.created_at).total_seconds() <= 600
    ):
        findings.append(failure("REVIEW_DEADLINE_OR_COLLECTION_MISMATCH", True))
    calls = [c for source in evidence.sources for c in source.calls] + [
        c for row in evidence.observations for c in row.calls
    ]
    if (
        len(calls) != 30
        or len({c.call_id for c in calls}) != 30
        or evidence.tools_admitted != 30
        or evidence.http_admitted < 30
    ):
        findings.append(failure("REVIEW_EXACT_CALL_OR_BUDGET_SET_MISMATCH"))
    if evidence.http_rejected or evidence.tools_rejected or not evidence.protocol_cleanup_complete:
        findings.append(failure("REVIEW_BUDGET_OR_PROTOCOL_CLEANUP_INCOMPLETE", True))
    if tuple(s.transport for s in evidence.sources) != get_args(ReviewTransport):
        findings.append(failure("REVIEW_FROZEN_SOURCE_SET_INCOMPLETE", True))
    findings.extend(_disposal(manifest, evidence, current))
    return tuple(findings)


def _disposal(
    manifest: ReviewManifest, evidence: ReviewEvidence, now: datetime
) -> tuple[Finding, ...]:
    receipt, stack = evidence.disposal, evidence.stack
    if receipt is None:
        return (failure("OWNED_ASSET_DISPOSAL_PENDING", True),)
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
        return (failure("REVIEW_EXACT_DISPOSAL_BINDING_MISMATCH"),)
    return ()


def _source(manifest: ReviewManifest, source: ReviewSource) -> tuple[Finding, ...]:
    names = (
        "preview_contract_import",
        "commit_contract_import",
        "generate_test_design",
        "begin_test_context",
    )
    if tuple(c.tool_name for c in source.calls) != tuple("flowtest." + n for n in names) or any(
        not c.success
        or c.sdk_version != "2.2.0"
        or c.protocol_version != "2026-07-28"
        or c.transport != source.transport
        or c.batch_key != manifest.batch_key + "-" + source.transport
        or not manifest.created_at <= c.completed_at <= source.frozen_at
        for c in source.calls
    ):
        return (failure("REVIEW_SOURCE_SDK_CHAIN_MISMATCH"),)
    if (
        source.spec_digest != canonical_digest(source.spec)
        or not manifest.created_at <= source.frozen_at <= manifest.expires_at
    ):
        return (failure("REVIEW_SOURCE_FREEZE_CHANGED"),)
    spec = source.spec
    if spec.get("security_policy") != {
        "max_requests": 20,
        "secret_refs_only": True,
        "allow_private_network": False,
    }:
        return (failure("REVIEW_PORTABLE_SPEC_POLICY_CHANGED"),)
    nodes = objects_value(spec["nodes"])
    kinds = {n["id"]: (n["kind"], n.get("config", {})) for n in nodes}
    if len(nodes) != 3 or kinds != {
        "start": ("start", {}),
        "pause": ("delay", {"seconds": 10}),
        "end": ("end", {}),
    }:
        return (failure("REVIEW_PREVIEW_NODE_RUBRIC_CHANGED"),)
    if spec.get("cleanup") != [
        {"id": "cleanup_after_cancel", "operation_ref": "fixture.cleanup", "run_when": "always"}
    ] or spec.get("run_policy") != {
        "request_budget": 1,
        "cleanup_request_budget": 1,
        "max_runtime_seconds": 30,
        "force_cancel_skips_cleanup": False,
    }:
        return (failure("REVIEW_PREVIEW_RUN_POLICY_CHANGED"),)
    operation = objects_value(spec["operations"])
    path = (
        f"/selftest/{manifest.batch_key}-{source.transport}/ST-MCP-022-{source.transport}/request"
    )
    if len(operation) != 1 or (
        operation[0].get("method"),
        operation[0].get("path"),
        operation[0].get("source_version"),
        operation[0].get("contract_fingerprint"),
    ) != ("GET", path, 1, source.contract_fingerprint):
        return (failure("REVIEW_PREVIEW_OPERATION_SOURCE_MISMATCH"),)
    return ()


def _design(
    manifest: ReviewManifest, scenario: ReviewScenario, row: ReviewObservation
) -> tuple[Finding, ...]:
    if scenario.action in {"preview_cancel", "unknown_publish", "stale_proposal"}:
        return ()
    arguments, golden = row.proposal_arguments, read_json(PACK_PATH)
    design = object_value(golden["design_input"])
    if objects_value(design["oracles"])[0]["expected"] != 200 or arguments.get("design") != design:
        return (failure("REVIEW_INDEPENDENT_DESIGN_RUBRIC_MISMATCH"),)
    risk = "high" if scenario.action == "stale_approval" else "low"
    if arguments.get("risk_level") != risk or arguments.get("confidence") != 1.0:
        return (failure("REVIEW_PROPOSAL_GOVERNANCE_CHANGED"),)
    cases = objects_value(arguments["test_cases"])
    if len(cases) != (2 if scenario.action == "partial_resume" else 0):
        return (failure("REVIEW_PARTIAL_CASE_INPUT_SET_MISMATCH"),)
    for case in cases:
        definition = object_value(case["definition"])
        if (
            definition["workflow_id"],
            definition["workflow_version"],
            definition["environment_id"],
        ) != (str(row.workflow_id), 1, str(manifest.scope.fixture_environment_id)):
            return (failure("REVIEW_CASE_VERSION_OR_TARGET_CHANGED"),)
    return ()


def _row(
    manifest: ReviewManifest,
    source: ReviewSource,
    scenario: ReviewScenario,
    row: ReviewObservation,
    authority: ProbeAuthority,
    now: datetime,
) -> tuple[Finding, ...]:
    if (
        not source.frozen_at <= row.started_at <= row.completed_at <= evidence_time(now, manifest)
        or (row.completed_at - row.started_at).total_seconds() > 180
    ):
        return (failure("REVIEW_SCENARIO_TIME_WINDOW_MISMATCH"),)
    try:
        findings = (
            *snapshots(manifest, scenario, row, authority, now),
            *receipts(manifest, source, scenario, row),
            *http_outcomes(scenario, row),
            *http_bindings(manifest, scenario, row),
            *_design(manifest, scenario, row),
        )
        if scenario.action == "preview_cancel":
            return (*findings, *verify_preview(manifest, source, scenario, row))
        return findings
    except (HarnessError, KeyError, TypeError, ValueError):
        return (failure("REVIEW_REQUIRED_RAW_EVIDENCE_INVALID", True),)


def evidence_time(now: datetime, manifest: ReviewManifest) -> datetime:
    return min(now, manifest.expires_at)


def verify(
    manifest: ReviewManifest,
    evidence: ReviewEvidence,
    authority: ProbeAuthority,
    *,
    now: datetime | None = None,
) -> ReviewReport:
    current = now or datetime.now(UTC)
    findings = [*_identity(manifest, evidence, authority), *_batch(manifest, evidence, current)]
    rows = {r.scenario_id: r for r in evidence.observations}
    sources = {s.transport: s for s in evidence.sources}
    if len(rows) != len(evidence.observations) or set(rows) != {
        r.scenario_id for r in manifest.scenarios
    }:
        findings.append(failure("REVIEW_REQUIRED_OBSERVATION_SET_INCOMPLETE", True))
    for frozen_source in evidence.sources:
        findings.extend(_source(manifest, frozen_source))
    previous: tuple[ProbeResource, ...] = ()
    verdicts = []
    for scenario in manifest.scenarios:
        row, source = rows.get(scenario.scenario_id), sources.get(scenario.transport)
        errors = (
            (failure("REVIEW_REQUIRED_SCENARIO_MISSING", True),)
            if row is None or source is None
            else _row(manifest, source, scenario, row, authority, current)
        )
        if row is not None:
            if row.before.resources != previous:
                errors += (failure("REVIEW_INVENTORY_SEQUENCE_CHANGED"),)
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
    total = findings + [f for row in verdicts for f in row.findings]
    code: Literal[0, 1, 2] = (
        1 if any(f.status == "mismatched" for f in total) else 2 if total else 0
    )
    return ReviewReport(
        batch_key=manifest.batch_key,
        exit_code=code,
        findings=tuple(findings),
        scenarios=tuple(verdicts),
    )


def write_reports(report: ReviewReport, evidence: ReviewEvidence | None, output: Path) -> None:
    write_json(output / "verification.json", report)
    if evidence is not None:
        write_json(output / "evidence.json", evidence)
    reasons = tuple(
        f.code for f in (*report.findings, *(f for r in report.scenarios for f in r.findings))
    )
    write_boundary_junit(
        output,
        tuple(r.scenario_id for r in report.scenarios),
        reasons,
        purpose="受限Preview及治理探针不算正式Case/Suite/Plan Run",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="独立核验审核恢复和Preview证据")
    for name in ("manifest", "evidence", "authority", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    report = verify(
        ReviewManifest.model_validate(read_json(args.manifest)),
        ReviewEvidence.model_validate(read_json(args.evidence)),
        ProbeAuthority.model_validate(read_json(args.authority)),
    )
    write_reports(report, None, args.output)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
