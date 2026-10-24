"""Independent frozen-rubric oracle; never invokes candidate generation or lowering."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.oracle_semantics import validate_published_oracles
from scripts.selftest.semantic_contracts import (
    SemanticArtifact,
    SemanticEvidence,
    SemanticManifest,
    SemanticObservation,
    SemanticReport,
    SemanticVerdict,
)

VARIANTS = (
    "positive_control",
    "missing_assertion",
    "wrong_field",
    "wrong_operator",
    "expected_from_actual",
)


def golden_schema() -> JsonObject:
    return {
        "type": "object",
        "required": ["actual", "code"],
        "properties": {
            "actual": {"type": "integer", "const": 1},
            "code": {"type": "integer", "const": 0},
        },
    }


def _source(artifact: SemanticArtifact) -> tuple[str, ...]:
    selected = {item.oracle_id: item for item in artifact.oracle_bindings}
    oracles = {text_value(item["id"]): item for item in objects_value(artifact.design["oracles"])}
    if set(selected) != {"oracle_success_status", "oracle_response_schema_200"}:
        return ("SEMANTIC_REQUIRED_ORACLE_SET_CHANGED",)
    status, schema = oracles.get("oracle_success_status"), oracles.get("oracle_response_schema_200")
    if status is None or schema is None:
        return ("SEMANTIC_SOURCE_ORACLE_MISSING",)
    if (
        status["kind"] != "status"
        or status["operator"] != "equals"
        or status["expected"] != 200
        or schema["kind"] != "schema"
        or canonical_digest(schema["expected"]) != canonical_digest(golden_schema())
        or selected["oracle_success_status"].expected_value_digest != canonical_digest(200)
        or selected["oracle_response_schema_200"].expected_value_digest
        != canonical_digest(golden_schema())
    ):
        return ("SEMANTIC_INDEPENDENT_RUBRIC_MISMATCH",)
    return ()


def _execution(
    manifest: SemanticManifest, artifact: SemanticArtifact, row: SemanticObservation
) -> tuple[str, ...]:
    raw, run = row.execution, row.run
    selected = [item for item in manifest.selection.cases if item.case_id == artifact.case_id]
    if len(selected) != 1:
        return ("SEMANTIC_CASE_SELECTION_MISMATCH",)
    identities = (
        raw.project_id == artifact.api_source.project_id == manifest.selection.project_id,
        raw.workflow_id == artifact.workflow_id == run.workflow_id,
        raw.workflow_version_id == artifact.workflow_version_id,
        raw.workflow_fingerprint == artifact.workflow_fingerprint,
        raw.environment_id == artifact.environment_id == run.environment_id,
        raw.api_sources == (artifact.api_source,),
        run.target_id == row.source_case_id == artifact.case_id,
        run.target_version == artifact.case_version == selected[0].version,
        run.execution_id == raw.id,
        run.run_item_id == row.source_plan_run_item_id,
        run.target_snapshot_digest == selected[0].target_snapshot_digest,
        run.source_suite is not None and run.source_suite.id == manifest.selection.suite_id,
        run.source_suite is not None
        and run.source_suite.version == manifest.selection.suite_version,
        run.workflow_version == artifact.workflow_version,
    )
    if not all(identities):
        return ("SEMANTIC_NATIVE_SOURCE_BINDING_MISMATCH",)
    if (
        not row.complete
        or raw.status != "passed"
        or raw.error_code is not None
        or raw.run_purpose != "standard"
        or run.status != "passed"
        or run.attempts != 1
        or raw.completed_at is None
        or not artifact.frozen_at <= raw.started_at <= raw.completed_at <= manifest.expires_at
        or any(item.status != "passed" for item in raw.nodes)
        or any(not assertion.passed for item in raw.nodes for assertion in item.assertions)
    ):
        return ("SEMANTIC_PASSED_COUNTEREXAMPLE_NOT_OBSERVED",)
    native_ids = {item["id"] for item in objects_value(artifact.definition["nodes"])}
    if {item.node_id for item in raw.nodes} != native_ids:
        return ("SEMANTIC_NATIVE_NODE_SET_MISMATCH",)
    return ()


def _frozen_identity(manifest: SemanticManifest) -> tuple[str, ...]:
    artifacts, stack, builds = manifest.artifacts, manifest.stack, manifest.builds
    if (
        builds.runner != builds.target
        or builds.runner != stack.candidate_image_digest
        or builds.fixture != stack.fixture_image_digest.removeprefix("sha256:")
        or not 0 < (manifest.expires_at - manifest.created_at).total_seconds() <= 600
        or len({item.api_source for item in artifacts}) != 1
        or len({item.design_fingerprint for item in artifacts}) != 1
        or len({canonical_digest(item.design) for item in artifacts}) != 1
        or len({item.compilation_fingerprint for item in artifacts}) != 1
    ):
        return ("SEMANTIC_FROZEN_SOURCE_OR_BUILD_CHANGED",)
    for item in artifacts:
        if (
            canonical_digest(item.definition) != item.definition_digest
            or item.workflow_proposal.materialized_resource_id != item.workflow_id
            or item.case_proposal.materialized_resource_id != item.case_id
            or item.workflow_proposal.reviewer_id != item.case_proposal.reviewer_id
            or item.workflow_proposal.project_id != manifest.selection.project_id
            or item.case_proposal.project_id != manifest.selection.project_id
            or item.frozen_at > manifest.expires_at
        ):
            return ("SEMANTIC_PUBLISHED_REVIEW_BINDING_MISMATCH",)
    return ()


def _pack(manifest: SemanticManifest) -> tuple[str, ...]:
    path = Path(__file__).resolve().parents[2] / "selftest/packs/mcp-semantic-review-v1/pack.json"
    pack = read_json(path)
    if (
        manifest.pack_digest != canonical_digest(pack)
        or pack["variants"] != list(VARIANTS)
        or pack["expected_review_rejections"] != [False, True, True, True, True]
        or canonical_digest(pack["response_schema"]) != canonical_digest(golden_schema())
    ):
        return ("SEMANTIC_PACK_BINDING_MISMATCH",)
    return ()


def _verdict(
    manifest: SemanticManifest, artifact: SemanticArtifact, row: SemanticObservation
) -> SemanticVerdict:
    findings = (*_source(artifact), *_execution(manifest, artifact, row))
    rejected = False
    try:
        validate_published_oracles(
            artifact.definition, artifact.design, artifact.oracle_bindings, source_kind="design"
        )
    except HarnessError as error:
        if str(error).startswith("SELFTEST_PUBLISHED_ORACLE"):
            rejected = True
        else:
            findings += ("SEMANTIC_REVIEW_UNAVAILABLE",)
    if rejected != (artifact.variant != "positive_control"):
        findings += ("SEMANTIC_REVIEW_DECISION_MISMATCH",)
    return SemanticVerdict(
        variant=artifact.variant,
        raw_status=row.execution.status,
        source_rejected=rejected,
        reason_codes=findings,
    )


def _journal(manifest: SemanticManifest, evidence: SemanticEvidence) -> tuple[str, ...]:
    journal = evidence.journal
    if (
        journal.batch_key != manifest.batch_key
        or journal.nonce != manifest.nonce
        or journal.scenario_id != "ST-MCP-026"
        or journal.fixture_epoch != manifest.fixture_epoch
        or journal.fixture_digest != manifest.builds.fixture
        or journal.truncated
        or journal.expired
        or journal.request_count != 5
        or len(journal.entries) != 5
        or {item.sequence for item in journal.entries} != set(range(1, 6))
    ):
        return ("SEMANTIC_TARGET_JOURNAL_INCOMPLETE",)
    for item in journal.entries:
        if (
            item.method != "GET"
            or item.authorization_present
            or item.cookie_present
            or item.response_status != 200
            or item.response_body is None
            or item.response_body.actual != 1
            or item.response_body.code != 0
            or item.fixture_epoch != manifest.fixture_epoch
        ):
            return ("SEMANTIC_TARGET_GOLDEN_MISMATCH",)
    return ()


def verify_semantic(
    manifest: SemanticManifest, evidence: SemanticEvidence, *, now: datetime | None = None
) -> SemanticReport:
    current = now or datetime.now(UTC)
    findings: list[str] = []
    findings.extend(_frozen_identity(manifest))
    findings.extend(_pack(manifest))
    artifacts = manifest.artifacts
    if tuple(item.variant for item in artifacts) != VARIANTS:
        findings.append("SEMANTIC_FROZEN_DENOMINATOR_MISMATCH")
    if canonical_digest(manifest.rubric.response_schema) != canonical_digest(golden_schema()):
        findings.append("SEMANTIC_FROZEN_RUBRIC_CHANGED")
    if evidence.manifest_digest != canonical_digest(manifest.model_dump(mode="json")):
        findings.append("SEMANTIC_MANIFEST_DIGEST_MISMATCH")
    if not manifest.created_at < evidence.collected_at <= current <= manifest.expires_at:
        findings.append("SEMANTIC_DEADLINE_MISMATCH")
    if not evidence.cleanup_completed:
        findings.append("SEMANTIC_FIXTURE_CLEANUP_PENDING")
    findings.extend(_journal(manifest, evidence))
    findings.extend(_calls(manifest, evidence))
    rows = {item.variant: item for item in evidence.observations}
    if len(rows) != len(evidence.observations) or set(rows) != set(VARIANTS):
        findings.append("SEMANTIC_OBSERVATION_SET_MISMATCH")
    verdicts = tuple(
        _verdict(manifest, item, rows[item.variant]) for item in artifacts if item.variant in rows
    )
    if len({item.execution.id for item in evidence.observations}) != len(rows):
        findings.append("SEMANTIC_EXECUTION_REUSED")
    if (
        len({item.case_id for item in artifacts}) != 5
        or len({item.workflow_id for item in artifacts}) != 5
    ):
        findings.append("SEMANTIC_PUBLISHED_ASSET_REUSED")
    disposal_pending = _disposal(manifest, evidence, current)
    findings.extend(disposal_pending)
    failed = any(item.reason_codes for item in verdicts) or bool(
        [code for code in findings if code != "SEMANTIC_OWNED_DISPOSAL_PENDING"]
    )
    return SemanticReport(
        batch_key=manifest.batch_key,
        exit_code=1 if failed else 2 if findings else 0,
        reason_codes=tuple(findings),
        scenarios=verdicts,
    )


def _calls(manifest: SemanticManifest, evidence: SemanticEvidence) -> tuple[str, ...]:
    calls = evidence.tool_receipts
    if (
        not calls
        or evidence.tool_attempts != len(calls)
        or len({item.call_id for item in calls}) != len(calls)
        or any(
            not item.success
            or item.batch_key != manifest.batch_key
            or item.sdk_version != "2.2.0"
            or item.transport != manifest.transport
            for item in calls
        )
    ):
        return ("SEMANTIC_MCP_RECEIPTS_INCOMPLETE",)
    if sum(item.tool_name == "flowtest.generate_test_design" for item in calls) != 1:
        return ("SEMANTIC_REAL_GENERATION_MISSING",)
    if sum(item.tool_name == "flowtest.propose_flow_draft" for item in calls) != 5:
        return ("SEMANTIC_REAL_PROPOSAL_SET_MISMATCH",)
    if evidence.direct_http_attempts + evidence.tool_attempts + 8 > 500:
        return ("SEMANTIC_SHARED_REQUEST_BUDGET_EXCEEDED",)
    return ()


def _disposal(
    manifest: SemanticManifest, evidence: SemanticEvidence, now: datetime
) -> tuple[str, ...]:
    receipt, stack = evidence.disposal, manifest.stack
    if receipt is None:
        return ("SEMANTIC_OWNED_DISPOSAL_PENDING",)
    if (
        receipt.project_name != stack.project_name
        or receipt.binding_nonce != stack.nonce
        or receipt.runner_volume != stack.runner_volume
        or receipt.target_volume != stack.target_volume
        or receipt.candidate_image_digest != stack.candidate_image_digest
        or not evidence.collected_at <= receipt.removed_at <= now <= manifest.expires_at
    ):
        return ("SEMANTIC_DISPOSAL_BINDING_MISMATCH",)
    return ()


def write_semantic_reports(
    report: SemanticReport, evidence: SemanticEvidence, directory: Path
) -> None:
    write_json(directory / "verification.json", report)
    for kind in ("execution", "verification"):
        suite = Element(
            "testsuite", name="mcp-semantic-review-" + kind, tests=str(len(report.scenarios))
        )
        failures = 0
        for row in report.scenarios:
            case = SubElement(suite, "testcase", name="ST-MCP-014-" + row.variant)
            failed = row.raw_status != "passed" if kind == "execution" else bool(row.reason_codes)
            if kind == "verification" and report.reason_codes:
                failed = True
            if failed:
                failures += 1
                SubElement(
                    case, "failure", message=",".join(row.reason_codes or report.reason_codes)
                )
        suite.set("failures", str(failures))
        (directory / (kind + ".junit.xml")).write_bytes(
            tostring(suite, encoding="utf-8", xml_declaration=True)
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="独立语义审核负向核验; 不导入候选编译器")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = SemanticManifest.model_validate(read_json(args.manifest))
    evidence = SemanticEvidence.model_validate(read_json(args.evidence))
    report = verify_semantic(manifest, evidence)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_semantic_reports(report, evidence, args.output)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
