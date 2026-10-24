"""Independent quality oracle and CLI; no product imports or privileged credentials."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import Element, SubElement, tostring

from pydantic import ValidationError
from scripts.selftest.contracts import Contract, canonical_digest
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.mcp_governance_verify import Finding, Verdict, failure
from scripts.selftest.mcp_probe_contracts import ProbeAuthority, ProbeResource
from scripts.selftest.quality_checks import (
    check_boundary,
    check_calls,
    check_generated,
    check_inventory,
)
from scripts.selftest.quality_contracts import (
    QualityEvidence,
    QualityManifest,
    QualityObservation,
    QualityPack,
    QualityScenario,
)

PACK_PATH = (
    Path(__file__).resolve().parents[2] / "selftest/packs/mcp-quality-boundaries-v1/pack.json"
)


class QualityReport(Contract):
    batch_key: str
    exit_code: Literal[0, 1, 2]
    findings: tuple[Finding, ...]
    scenarios: tuple[Verdict, ...]
    claim: Literal["generation_quality_negative_only"] = "generation_quality_negative_only"
    trust: Literal["local_untrusted"] = "local_untrusted"


def _identity(
    manifest: QualityManifest, evidence: QualityEvidence, authority: ProbeAuthority
) -> list[Finding]:
    findings: list[Finding] = []
    actual = canonical_digest(manifest.model_dump(mode="json"))
    if evidence.manifest_digest != actual or authority.manifest_digest != actual:
        findings.append(failure("QUALITY_MANIFEST_BINDING_MISMATCH"))
    if evidence.authority_digest != canonical_digest(authority.model_dump(mode="json")):
        findings.append(failure("QUALITY_AUTHORITY_BINDING_MISMATCH"))
    stack = evidence.stack
    if (
        canonical_digest(stack.model_dump(mode="json", exclude={"runner_container_id"}))
        != authority.binding_fingerprint
    ):
        findings.append(failure("QUALITY_STACK_BINDING_MISMATCH"))
    if (
        manifest.nonce,
        manifest.source_digest,
        manifest.created_at,
        manifest.expires_at,
        manifest.scope.project_id,
    ) != (
        authority.probe_id.hex,
        authority.source_digest,
        authority.issued_at,
        authority.expires_at,
        authority.fixtures[0].project_id,
    ):
        findings.append(failure("QUALITY_AUTHORITY_SCOPE_OR_TIME_MISMATCH"))
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
        findings.append(failure("QUALITY_BUILD_SOURCE_MISMATCH"))
    machines = {manifest.writer_machine_id, manifest.reader_machine_id}
    if len(machines) != 2 or not machines <= set(authority.machine_account_ids):
        findings.append(failure("QUALITY_MACHINE_SCOPE_MISMATCH"))
    if not 0 < (manifest.expires_at - manifest.created_at).total_seconds() <= 600:
        findings.append(failure("QUALITY_DEADLINE_UNBOUNDED"))
    return findings


def _batch(manifest: QualityManifest, evidence: QualityEvidence, now: datetime) -> list[Finding]:
    findings: list[Finding] = []
    raw = read_json(PACK_PATH)
    pack = QualityPack.model_validate(raw)
    if canonical_digest(raw) != manifest.pack_digest or pack.scenarios != manifest.scenarios:
        findings.append(failure("QUALITY_FROZEN_PACK_MISMATCH"))
    if not manifest.created_at <= evidence.collected_at <= now < manifest.expires_at:
        findings.append(failure("QUALITY_EVIDENCE_EXPIRED_OR_TIME_MISMATCH", True))
    calls = [call for row in evidence.observations for call in row.calls]
    if len(calls) != 68 or len({c.call_id for c in calls}) != 68 or evidence.tool_attempts != 68:
        findings.append(failure("QUALITY_EXACT_ATTEMPT_SET_MISMATCH"))
    if (
        evidence.http_admitted < len(calls)
        or evidence.http_rejected
        or evidence.tools_rejected
        or not evidence.protocol_cleanup_complete
    ):
        findings.append(failure("QUALITY_BUDGET_OR_PROTOCOL_CLEANUP_INCOMPLETE", True))
    if evidence.disposal is None:
        findings.append(failure("OWNED_ASSET_DISPOSAL_PENDING", True))
    else:
        receipt, stack = evidence.disposal, evidence.stack
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
            findings.append(failure("QUALITY_DISPOSAL_BINDING_MISMATCH"))
    return findings


def _row(
    manifest: QualityManifest,
    scenario: QualityScenario,
    row: QualityObservation,
    authority: ProbeAuthority,
    now: datetime,
) -> tuple[Finding, ...]:
    if not manifest.created_at <= row.started_at <= row.completed_at <= now:
        return (failure("QUALITY_OBSERVATION_TIME_MISMATCH"),)
    try:
        findings = (
            *check_inventory(manifest, row, scenario, authority, now),
            *check_calls(manifest, scenario, row),
        )
        if scenario.expected_readiness is None:
            return (*findings, *check_boundary(manifest, scenario, row))
        return (*findings, *check_generated(manifest, scenario, row))
    except (HarnessError, KeyError, TypeError, ValueError):
        return (failure("QUALITY_OBSERVATION_CONTRACT_INCOMPLETE", True),)


def verify(
    manifest: QualityManifest,
    evidence: QualityEvidence,
    authority: ProbeAuthority,
    *,
    now: datetime | None = None,
) -> QualityReport:
    current = now or datetime.now(UTC)
    findings = _identity(manifest, evidence, authority) + _batch(manifest, evidence, current)
    actual = {r.scenario_id: r for r in evidence.observations}
    if len(actual) != len(evidence.observations) or set(actual) != {
        r.scenario_id for r in manifest.scenarios
    }:
        findings.append(failure("QUALITY_REQUIRED_SCENARIO_SET_MISMATCH", True))
    verdicts: list[Verdict] = []
    previous: tuple[ProbeResource, ...] = ()
    for scenario in manifest.scenarios:
        row = actual.get(scenario.scenario_id)
        errors = (
            (failure("QUALITY_REQUIRED_OBSERVATION_MISSING", True),)
            if row is None
            else _row(manifest, scenario, row, authority, current)
        )
        if row is not None:
            if row.before.resources != previous:
                errors += (failure("QUALITY_INVENTORY_CHAIN_CHANGED"),)
            previous = row.after.resources
        status = (
            "incomplete"
            if any(f.status == "incomplete" for f in errors)
            else "mismatched"
            if errors
            else "matched"
        )
        verdicts.append(
            Verdict(
                scenario_id=scenario.scenario_id,
                verification_status=status,
                findings=errors,
            )
        )
    all_findings = findings + [f for v in verdicts for f in v.findings]
    code: Literal[0, 1, 2] = (
        1 if any(f.status == "mismatched" for f in all_findings) else 2 if all_findings else 0
    )
    return QualityReport(
        batch_key=manifest.batch_key,
        exit_code=code,
        findings=tuple(findings),
        scenarios=tuple(verdicts),
    )


def write_reports(report: QualityReport, evidence: QualityEvidence | None, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "verification.json", report)
    if evidence is not None:
        write_json(output / "evidence.json", evidence)
    for kind in ("execution", "verification"):
        root = Element("testsuite", name="mcp-quality-" + kind, tests=str(len(report.scenarios)))
        failures = 0
        for row in report.scenarios:
            case = SubElement(root, "testcase", name=row.scenario_id)
            if kind == "execution":
                SubElement(case, "skipped", message="设计质量负向检查未执行正式用例")
            elif row.verification_status != "matched" or report.findings:
                failures += 1
                SubElement(
                    case,
                    "failure",
                    message=";".join(f.code for f in (*report.findings, *row.findings)),
                )
        root.set("failures", str(failures))
        root.set("skipped", str(len(report.scenarios) if kind == "execution" else 0))
        (output / (kind + ".junit.xml")).write_bytes(
            tostring(root, encoding="utf-8", xml_declaration=True)
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="独立核验生成质量和不可信材料边界")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify(
            QualityManifest.model_validate(read_json(args.manifest)),
            QualityEvidence.model_validate(read_json(args.evidence)),
            ProbeAuthority.model_validate(read_json(args.authority)),
        )
    except (HarnessError, ValidationError, OSError) as error:
        report = QualityReport(
            batch_key="unavailable",
            exit_code=2,
            findings=(failure(type(error).__name__, True),),
            scenarios=(),
        )
    write_reports(report, None, args.output)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
