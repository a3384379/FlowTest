"""Independent negative-only deployment oracle; no app, fixture, or engine imports."""

from __future__ import annotations

import argparse
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import Element, SubElement, tostring

from pydantic import ValidationError
from scripts.selftest.contracts import Contract, canonical_digest
from scripts.selftest.io import HarnessError, JsonObject, read_json, write_json
from scripts.selftest.mcp_governance_contracts import Manifest, Observation, Scenario
from scripts.selftest.mcp_governance_verify import (
    Finding,
    Report,
    Verdict,
    _mcp_request,
    _raw,
    _receipts,
    _times,
    failure,
    write_incomplete_reports,
)
from scripts.selftest.mcp_negative_contracts import ProtocolManifest, ProtocolObservation
from scripts.selftest.mcp_negative_verify import verify_protocol
from scripts.selftest.mcp_probe_contracts import ProbeAuthority, ProbeResource, ProbeSnapshot
from scripts.selftest.mcp_probe_evidence import DeployedEvidence, ScenarioSnapshots
from scripts.selftest.mcp_probe_reader import validate_snapshot

ROOT = Path(__file__).resolve().parents[2]
# Authored from the explicit TestDesign 1.0 contract/defaults and the synthetic
# request, before reading any run: see normalized-design.golden.json.
EXPECTED_SYNTHETIC_DESIGN_DIGEST = (
    "dd958e1e2be520d514eaa07df36151a76e0c33b8e0e9cda601fc34f3d69a27a0"
)


class StateReference(Contract):
    proposal_id: str
    item_id: str
    source_digest: str | None
    document_digest: str | None
    approval_id: str | None
    materialized_id: str | None


def _profile_pack(authority: ProbeAuthority) -> JsonObject:
    raw = read_json(ROOT / "selftest/packs/mcp-negative-v1/pack.json")
    rows = raw["scenarios"]
    if not isinstance(rows, list):
        raise HarnessError("SELFTEST_PROBE_FROZEN_PACK_INVALID")
    for row in rows:
        if isinstance(row, dict) and row.get("operation") == "inspect":
            expected = row.get("expected")
            if not isinstance(expected, dict):
                raise HarnessError("SELFTEST_PROBE_FROZEN_PACK_INVALID")
            expected["runtime_profile"] = authority.runtime_profile
    return raw


def _authority(
    manifest: Manifest | ProtocolManifest, evidence: DeployedEvidence, authority: ProbeAuthority
) -> tuple[Finding, ...]:
    stack = evidence.stack
    actual = canonical_digest(manifest.model_dump(mode="json"))
    if evidence.manifest_digest != actual or authority.manifest_digest != actual:
        return (failure("PROBE_MANIFEST_BINDING_MISMATCH"),)
    if evidence.authority_digest != canonical_digest(authority.model_dump(mode="json")):
        return (failure("PROBE_AUTHORITY_BINDING_MISMATCH"),)
    if (
        canonical_digest(stack.model_dump(mode="json", exclude={"runner_container_id"}))
        != authority.binding_fingerprint
    ):
        return (failure("PROBE_STACK_BINDING_MISMATCH"),)
    if (
        stack.source_digest,
        stack.runtime_profile,
        stack.candidate_image_digest,
        stack.fixture_image_digest.removeprefix("sha256:"),
    ) != (
        authority.source_digest,
        authority.runtime_profile,
        authority.builds.runner,
        authority.builds.fixture,
    ):
        return (failure("PROBE_BUILD_OR_PROFILE_MISMATCH"),)
    if (
        manifest.source_digest != authority.source_digest
        or authority.builds.target != authority.builds.runner
    ):
        return (failure("PROBE_SOURCE_BINDING_MISMATCH"),)
    if manifest.nonce != authority.probe_id.hex:
        return (failure("PROBE_NONCE_BINDING_MISMATCH"),)
    if (manifest.created_at, manifest.expires_at) != (authority.issued_at, authority.expires_at):
        return (failure("PROBE_DEADLINE_BINDING_MISMATCH"),)
    raw = evidence.protocol if evidence.protocol is not None else evidence.governance
    if (
        raw is None
        or raw.collected_at != evidence.collected_at
        or not max((row.completed_at for row in raw.scenarios), default=manifest.created_at)
        <= evidence.collected_at
        <= manifest.expires_at
    ):
        return (failure("PROBE_COLLECTION_TIME_MISMATCH"),)
    return _fixtures(manifest, authority)


def _fixtures(
    manifest: Manifest | ProtocolManifest, authority: ProbeAuthority
) -> tuple[Finding, ...]:
    first, second = authority.fixtures
    if isinstance(manifest, ProtocolManifest):
        actual = (
            manifest.fixture.project_a,
            manifest.fixture.organization_a,
            manifest.fixture.project_b,
            manifest.fixture.organization_b,
        )
        wanted = (
            first.project_id,
            first.organization_id,
            second.project_id,
            second.organization_id,
        )
        if actual != wanted:
            return (failure("PROBE_FIXTURE_BINDING_MISMATCH"),)
    elif (
        manifest.fixture.project_id,
        manifest.fixture.organization_id,
        manifest.fixture.owner_user_id,
        manifest.fixture.reviewer_user_id,
    ) != (
        first.project_id,
        first.organization_id,
        authority.owner_user_id,
        authority.reviewer_user_id,
    ) or manifest.fixture.machine_id not in authority.machine_account_ids:
        return (failure("PROBE_FIXTURE_BINDING_MISMATCH"),)
    return ()


def _disposal(evidence: DeployedEvidence, deadline: datetime, now: datetime) -> tuple[Finding, ...]:
    receipt, stack = evidence.disposal_receipt, evidence.stack
    if not evidence.gateway_cleanup_complete:
        return (failure("PROBE_GATEWAY_CLEANUP_INCOMPLETE", True),)
    if receipt is None:
        return (failure("OWNED_ASSET_DISPOSAL_PENDING", True),)
    wanted = (
        stack.project_name,
        stack.nonce,
        stack.runner_volume,
        stack.target_volume,
        stack.candidate_image_digest,
    )
    observed = (
        receipt.project_name,
        receipt.binding_nonce,
        receipt.runner_volume,
        receipt.target_volume,
        receipt.candidate_image_digest,
    )
    if wanted != observed or not evidence.collected_at <= receipt.removed_at <= min(deadline, now):
        return (failure("PROBE_DISPOSAL_BINDING_OR_TIME_MISMATCH"),)
    return ()


def _snapshots(
    manifest: Manifest | ProtocolManifest, evidence: DeployedEvidence, authority: ProbeAuthority
) -> tuple[Finding, ...]:
    raw = evidence.protocol if evidence.protocol is not None else evidence.governance
    if raw is None:
        return (failure("PROBE_RAW_EVIDENCE_MISSING", True),)
    required = {row.scenario_id for row in manifest.scenarios}
    actual = {row.scenario_id: row for row in evidence.snapshots}
    if len(actual) != len(evidence.snapshots) or set(actual) - required:
        return (failure("PROBE_SNAPSHOT_SET_MISMATCH"),)
    findings: list[Finding] = []
    for row in raw.scenarios:
        snapshot = actual.get(row.scenario_id)
        if snapshot is None:
            findings.append(failure("PROBE_SCENARIO_SNAPSHOTS_MISSING", True))
            continue
        try:
            validate_snapshot(authority, snapshot.before, now=evidence.collected_at)
            validate_snapshot(authority, snapshot.after, now=evidence.collected_at)
        except HarnessError:
            findings.append(failure("PROBE_INVENTORY_INCOMPLETE_OR_CHANGED", True))
            continue
        times = [page.observed_at for page in snapshot.before.pages + snapshot.after.pages]
        if not row.started_at <= min(times) <= max(times) <= row.completed_at:
            findings.append(failure("PROBE_OBSERVATION_TIME_MISMATCH"))
        findings.extend(_observed_counts(row, snapshot))
    return tuple(findings)


def _observed_counts(
    row: Observation | ProtocolObservation, snapshot: ScenarioSnapshots
) -> tuple[Finding, ...]:
    before = row.before_assets if isinstance(row, ProtocolObservation) else row.before
    after = row.assets if isinstance(row, ProtocolObservation) else row.after
    kinds = {
        "workflows": "workflow",
        "workflow_versions": "workflow_version",
        "cases": "test_case",
        "case_versions": "test_case_version",
        "plans": "test_plan",
        "runs": "test_plan_run",
        "executions": "workflow_execution",
        "proposals": "ai_change_set",
        "designs": "test_design",
        "approvals": "change_set_approval",
    }
    for observed, captured in ((before, snapshot.before), (after, snapshot.after)):
        for field, value in observed.model_dump().items():
            if value != sum(item.kind == kinds[field] for item in captured.resources):
                return (failure("PROBE_OBSERVED_ASSET_COUNTER_MISMATCH"),)
    return ()


def _protocol(
    manifest: ProtocolManifest, evidence: DeployedEvidence, authority: ProbeAuthority, now: datetime
) -> Report:
    raw = evidence.protocol
    if raw is None:
        raise HarnessError("SELFTEST_PROBE_RAW_KIND_MISMATCH")
    with tempfile.TemporaryDirectory(prefix="flowtest-probe-o-") as temporary:
        pack = Path(temporary) / "trusted-derived-pack.json"
        write_json(pack, _profile_pack(authority))
        checked = verify_protocol(manifest, raw, now=now, pack_path=pack)
    findings = [Finding.model_validate(row.model_dump()) for row in checked.findings]
    if any(
        snapshot.before.resources or snapshot.after.resources for snapshot in evidence.snapshots
    ):
        findings.append(failure("PROBE_UNEXPECTED_ASSET_SIDE_EFFECT"))
    rows = tuple(Verdict.model_validate(row.model_dump()) for row in checked.scenarios)
    return Report(
        batch_key=manifest.batch_key,
        exit_code=_exit(tuple(findings), rows),
        findings=tuple(findings),
        scenarios=rows,
    )


def _summary(resource: ProbeResource) -> tuple[Finding, ...]:
    design = resource.items[0].design
    if design is None:
        return (failure("PROBE_DESIGN_SUMMARY_MISSING", True),)
    if (
        design.intent_key_digest != canonical_digest("synthetic.governance")
        or design.objective_digest != canonical_digest("合成治理验证, 不执行发布运行")
        or len(design.oracles) != 1
    ):
        return (failure("PROBE_DESIGN_SEMANTICS_MISMATCH"),)
    oracle = design.oracles[0]
    if (
        oracle.id,
        oracle.kind,
        oracle.expression_digest,
        oracle.operator,
        oracle.expected_digest,
    ) != ("status", "status", canonical_digest("$.status"), "equals", canonical_digest(200)):
        return (failure("PROBE_ORACLE_MISMATCH"),)
    if (
        resource.items[0].proposed_document_digest != design.document_digest
        or design.document_digest != EXPECTED_SYNTHETIC_DESIGN_DIGEST
    ):
        return (failure("PROBE_PROPOSED_DOCUMENT_MISMATCH"),)
    return ()


def _saved(
    manifest: Manifest, proposal: ProbeResource, after: ProbeSnapshot
) -> tuple[Finding, ...]:
    item = proposal.items[0]
    if item.review_status != "accepted":
        if item.materialized_resource_id is not None or item.materialized_resource_type is not None:
            return (failure("PROBE_UNEXPECTED_MATERIALIZATION"),)
        return ()
    materialized = [
        row
        for row in after.resources
        if row.kind == "test_design" and row.id == item.materialized_resource_id
    ]
    if len(materialized) != 1 or item.materialized_resource_type != "test_design":
        return (failure("PROBE_SAVED_DESIGN_MISSING", True),)
    saved = materialized[0]
    if (
        saved.project_id != manifest.fixture.project_id
        or saved.source_change_set_id != proposal.id
        or saved.reviewed_by_id != manifest.fixture.reviewer_user_id
        or saved.status != "approved"
    ):
        return (failure("PROBE_SAVED_DESIGN_BINDING_MISMATCH"),)
    if (
        saved.design is None
        or saved.design.document_digest != item.proposed_document_digest
        or saved.fingerprint != item.proposed_document_digest
    ):
        return (failure("PROBE_SAVED_DESIGN_DIGEST_MISMATCH"),)
    return ()


def _proposal(
    manifest: Manifest,
    scenario: Scenario,
    row: Observation,
    after: ProbeSnapshot,
    prior: dict[tuple[str, str], StateReference],
) -> tuple[tuple[Finding, ...], StateReference | None]:
    key = (scenario.transport, scenario.expected.target or "")
    old = prior.get(key)
    identifier = (
        row.result.proposal_id
        if scenario.action.startswith("persist_")
        else old.proposal_id
        if old
        else None
    )
    proposals = [
        resource
        for resource in after.resources
        if resource.kind == "ai_change_set" and str(resource.id) == str(identifier)
    ]
    if len(proposals) != 1 or len(proposals[0].items) != 1:
        return (failure("PROBE_PROPOSAL_ITEM_SET_MISMATCH", True),), None
    proposal = proposals[0]
    item = proposal.items[0]
    if (
        proposal.project_id,
        proposal.actor_type,
        proposal.created_by_id,
        proposal.status,
        item.item_type,
        item.action,
        item.review_status,
    ) != (
        manifest.fixture.project_id,
        "service_account",
        manifest.fixture.owner_user_id,
        scenario.expected.state_status,
        "test_design",
        "create",
        scenario.expected.item_review,
    ):
        return (failure("PROBE_PROPOSAL_STATE_MISMATCH"),), None
    if item.review_status != "pending" and item.reviewed_by_id != manifest.fixture.reviewer_user_id:
        return (failure("PROBE_REVIEWER_MISMATCH"),), None
    approvals = [
        resource
        for resource in after.resources
        if resource.kind == "change_set_approval" and resource.parent_id == proposal.id
    ]
    needed = scenario.action in {"high_approve", "high_accept", "high_reaccept"}
    if len(approvals) != int(needed) or any(
        resource.status != "approved"
        or resource.reviewed_by_id != manifest.fixture.reviewer_user_id
        for resource in approvals
    ):
        return (failure("PROBE_APPROVAL_BINDING_MISMATCH"),), None
    reference = StateReference(
        proposal_id=str(proposal.id),
        item_id=str(item.id),
        source_digest=proposal.fingerprint,
        document_digest=item.proposed_document_digest,
        approval_id=str(approvals[0].id) if approvals else None,
        materialized_id=str(item.materialized_resource_id)
        if item.materialized_resource_id
        else None,
    )
    failures = (
        *_summary(proposal),
        *_saved(manifest, proposal, after),
        *_stable(reference, old, prior),
    )
    return failures, reference


def _stable(
    current: StateReference,
    old: StateReference | None,
    prior: dict[tuple[str, str], StateReference],
) -> tuple[Finding, ...]:
    if current.source_digest is None or current.document_digest is None:
        return (failure("PROBE_SOURCE_FINGERPRINT_MISSING", True),)
    if old is None:
        return (
            (failure("PROBE_PROPOSAL_REUSED"),)
            if current.proposal_id in {row.proposal_id for row in prior.values()}
            else ()
        )
    keys = ("proposal_id", "item_id", "source_digest", "document_digest")
    if any(getattr(old, key) != getattr(current, key) for key in keys):
        return (failure("PROBE_PROPOSAL_SOURCE_CHANGED"),)
    if (old.approval_id is not None and old.approval_id != current.approval_id) or (
        old.materialized_id is not None and old.materialized_id != current.materialized_id
    ):
        return (failure("PROBE_REVIEW_RECEIPT_CHANGED"),)
    return ()


def _rest(
    scenario: Scenario, row: Observation, prior: dict[tuple[str, str], StateReference]
) -> tuple[Finding, ...]:
    selected = prior.get((scenario.transport, scenario.expected.target or ""))
    if selected is None:
        return (failure("PROBE_PRIOR_REFERENCE_MISSING", True),)
    path = f"/mcp/write/change-sets/{selected.proposal_id}"
    body: JsonObject = {}
    if scenario.action.endswith("approve"):
        path += "/approve"
    else:
        path += f"/items/{selected.item_id}/" + (
            "reject" if scenario.action == "low_reject" else "accept"
        )
    if scenario.action in {"high_accept", "wrong_approval"}:
        approval = prior.get((scenario.transport, "high"))
        if approval is None or approval.approval_id is None:
            return (failure("PROBE_APPROVAL_REFERENCE_MISSING", True),)
        body = {"approval_id": approval.approval_id}
    if (
        row.request_path != path
        or row.request_digest != canonical_digest(body)
        or row.wire_request is not None
        or row.wire_response is not None
    ):
        return (failure("PROBE_REVIEW_REQUEST_BINDING_MISMATCH"),)
    return ()


def _inventory_transition(
    scenario: Scenario,
    snapshot: ScenarioSnapshots,
    reference: StateReference | None,
    previous: tuple[ProbeResource, ...] | None,
) -> tuple[Finding, ...]:
    before, after = snapshot.before.resources, snapshot.after.resources
    if previous is not None and previous != before:
        return (failure("PROBE_PRIOR_ASSET_SET_CHANGED"),)
    old = {(r.kind, str(r.id)): r for r in before}
    current = {(r.kind, str(r.id)): r for r in after}
    added: set[tuple[str, str]] = set()
    if reference is not None:
        if scenario.action.startswith("persist_"):
            added.add(("ai_change_set", reference.proposal_id))
        if scenario.action == "high_approve" and reference.approval_id is not None:
            added.add(("change_set_approval", reference.approval_id))
        if scenario.action == "high_accept" and reference.materialized_id is not None:
            added.add(("test_design", reference.materialized_id))
    if set(current) != set(old) | added:
        return (failure("PROBE_EXACT_ASSET_SET_MISMATCH"),)
    changing = ("ai_change_set", reference.proposal_id) if reference is not None else None
    if any(key != changing and current.get(key) != value for key, value in old.items()):
        return (failure("PROBE_UNRELATED_ASSET_CHANGED"),)
    return ()


def _gov_row(
    manifest: Manifest,
    scenario: Scenario,
    row: Observation,
    snapshot: ScenarioSnapshots,
    prior: dict[tuple[str, str], StateReference],
    previous: tuple[ProbeResource, ...] | None,
) -> tuple[Finding, ...]:
    findings = list(_raw(scenario, row))
    if row.state is not None:
        findings.append(failure("PROBE_UNEXPECTED_RAW_DESIGN_CAPTURE"))
    if (
        not row.complete
        or row.actor != scenario.expected.actor
        or row.transport != scenario.transport
        or not manifest.created_at <= row.started_at <= row.completed_at <= manifest.expires_at
    ):
        findings.append(failure("PROBE_SCENARIO_IDENTITY_OR_TIME_MISMATCH"))
    findings.extend(
        _mcp_request(manifest, scenario, row)
        if scenario.expected.channel == "mcp"
        else _rest(scenario, row, prior)
    )
    reference = None
    if scenario.expected.target is not None:
        extra, reference = _proposal(manifest, scenario, row, snapshot.after, prior)
        findings.extend(extra)
    elif row.result.proposal_id is not None:
        findings.append(failure("PROBE_UNEXPECTED_RESULT_REFERENCE"))
    findings.extend(_inventory_transition(scenario, snapshot, reference, previous))
    if reference is not None and not findings:
        prior[(scenario.transport, scenario.expected.target or "")] = reference
    return tuple(findings)


def _governance(
    manifest: Manifest, evidence: DeployedEvidence, authority: ProbeAuthority, now: datetime
) -> Report:
    raw = evidence.governance
    if raw is None:
        raise HarnessError("SELFTEST_PROBE_RAW_KIND_MISMATCH")
    from scripts.selftest.mcp_governance_contracts import Pack

    pack_raw = read_json(ROOT / "selftest/packs/mcp-governance-negative-v1/pack.json")
    pack = Pack.model_validate(pack_raw)
    findings: list[Finding] = []
    if manifest.pack_digest != canonical_digest(pack_raw) or manifest.scenarios != pack.scenarios:
        findings.append(failure("PROBE_FROZEN_GOLDEN_MISMATCH"))
    fields = ("batch_key", "nonce", "pack_digest", "source_digest", "sdk_version", "claim", "trust")
    if any(getattr(manifest, key) != getattr(raw, key) for key in fields):
        findings.append(failure("PROBE_RAW_BATCH_IDENTITY_MISMATCH"))
    findings.extend((*_times(manifest, raw, now), *_receipts(raw)))
    if (
        not raw.process_cleanup_complete
        or raw.http_rejected
        or raw.tools_rejected
        or raw.tools_admitted != sum(s.expected.channel == "mcp" for s in manifest.scenarios)
    ):
        findings.append(failure("PROBE_ADMISSION_OR_CLEANUP_MISMATCH"))
    rows = {row.scenario_id: row for row in raw.scenarios}
    snapshots = {row.scenario_id: row for row in evidence.snapshots}
    if len(rows) != len(raw.scenarios) or set(rows) - {
        row.scenario_id for row in manifest.scenarios
    }:
        findings.append(failure("PROBE_SCENARIO_SET_MISMATCH"))
    prior: dict[tuple[str, str], StateReference] = {}
    previous: tuple[ProbeResource, ...] | None = None
    verdicts: list[Verdict] = []
    for scenario in manifest.scenarios:
        row, snapshot = rows.get(scenario.scenario_id), snapshots.get(scenario.scenario_id)
        failures = (
            (failure("PROBE_REQUIRED_SCENARIO_MISSING", True),)
            if row is None or snapshot is None
            else _gov_row(manifest, scenario, row, snapshot, prior, previous)
        )
        if snapshot is not None:
            previous = snapshot.after.resources
        verdicts.append(
            Verdict(
                scenario_id=scenario.scenario_id,
                verification_status=_status(failures),
                findings=failures,
            )
        )
    return Report(
        batch_key=manifest.batch_key,
        exit_code=_exit(tuple(findings), tuple(verdicts)),
        findings=tuple(findings),
        scenarios=tuple(verdicts),
    )


def _status(findings: tuple[Finding, ...]) -> Literal["incomplete", "mismatched", "matched"]:
    return (
        "incomplete"
        if any(row.status == "incomplete" for row in findings)
        else "mismatched"
        if findings
        else "matched"
    )


def _exit(findings: tuple[Finding, ...], rows: tuple[Verdict, ...]) -> Literal[0, 1, 2]:
    statuses = {row.status for row in findings} | {f.status for row in rows for f in row.findings}
    return 1 if "mismatched" in statuses else 2 if statuses else 0


def verify_deployed(
    manifest: Manifest | ProtocolManifest,
    evidence: DeployedEvidence,
    authority: ProbeAuthority,
    *,
    now: datetime | None = None,
) -> Report:
    current = now or datetime.now(UTC)
    base = (
        _protocol(manifest, evidence, authority, current)
        if isinstance(manifest, ProtocolManifest)
        else _governance(manifest, evidence, authority, current)
    )
    findings = (
        *base.findings,
        *_authority(manifest, evidence, authority),
        *_snapshots(manifest, evidence, authority),
        *_disposal(evidence, manifest.expires_at, current),
        *_budget(evidence),
    )
    return base.model_copy(
        update={"findings": findings, "exit_code": _exit(findings, base.scenarios)}
    )


def _budget(evidence: DeployedEvidence) -> tuple[Finding, ...]:
    raw = evidence.protocol if evidence.protocol is not None else evidence.governance
    if raw is None:
        return (failure("PROBE_BUDGET_RAW_EVIDENCE_MISSING", True),)
    admitted = (
        evidence.protocol.http_requests
        if evidence.protocol is not None
        else evidence.governance.http_admitted
        if evidence.governance is not None
        else 0
    )
    if (
        evidence.candidate_rpc_rejected
        or admitted != evidence.http_outbound_admitted + evidence.candidate_rpc_admitted
    ):
        return (failure("PROBE_REQUEST_BUDGET_MISMATCH"),)
    if evidence.protocol is not None and evidence.candidate_rpc_admitted != sum(
        len(row.requests) for row in evidence.protocol.scenarios
    ):
        return (failure("PROBE_RPC_BUDGET_RECEIPTS_MISMATCH"),)
    if (
        evidence.governance is not None
        and evidence.candidate_rpc_admitted < evidence.governance.tools_admitted
    ):
        return (failure("PROBE_RPC_BUDGET_RECEIPTS_MISSING", True),)
    return ()


def write_deployed_reports(report: Report, evidence: DeployedEvidence, output: Path) -> None:
    write_json(output / "verification.json", report)
    raw = evidence.protocol if evidence.protocol is not None else evidence.governance
    if raw is None:
        raise HarnessError("SELFTEST_PROBE_RAW_EVIDENCE_MISSING")
    verification = Element(
        "testsuite",
        name="negative-deployment-independent",
        tests=str(len(report.scenarios) + bool(report.findings)),
    )
    if report.findings:
        SubElement(
            SubElement(verification, "testcase", name="batch-global"), "failure"
        ).text = ",".join(row.code for row in report.findings)
    for row in report.scenarios:
        test = SubElement(verification, "testcase", name=row.scenario_id)
        if row.findings:
            SubElement(test, "failure").text = ",".join(f.code for f in row.findings)
    execution = Element("testsuite", name="negative-deployment-raw", tests=str(len(raw.scenarios)))
    for observed in raw.scenarios:
        test = SubElement(execution, "testcase", name=observed.scenario_id)
        values = (
            observed.results if isinstance(observed, ProtocolObservation) else (observed.result,)
        )
        if any(
            row.is_error or row.business_code or getattr(row, "rpc_error_code", None)
            for row in values
        ):
            SubElement(test, "failure").text = "原始协议/工具/业务失败保留"
    for name, root in (("verification", verification), ("execution", execution)):
        (output / (name + ".junit.xml")).write_bytes(
            tostring(root, encoding="utf-8", xml_declaration=True)
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="仅独立核验已部署负向pack, 不计普通生成执行闭环")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = DeployedEvidence.model_validate(read_json(args.evidence))
        model = ProtocolManifest if evidence.pack_kind == "protocol34" else Manifest
        manifest = model.model_validate(read_json(args.manifest))
        authority = ProbeAuthority.model_validate(read_json(args.authority))
        report = verify_deployed(manifest, evidence, authority)
    except (HarnessError, ValidationError, OSError, ValueError):
        return write_incomplete_reports(args.output, "PROBE_CONTRACT_INVALID").exit_code
    write_deployed_reports(report, evidence, args.output)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
