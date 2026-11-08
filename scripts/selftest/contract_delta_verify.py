"""Independent frozen delta/slot checks; no candidate domain or service imports."""

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args
from xml.etree.ElementTree import Element, SubElement, tostring

from pydantic import JsonValue
from scripts.selftest.contract_delta_contracts import (
    BoundaryObservation,
    DeltaCheck,
    DeltaEvidence,
    DeltaManifest,
    DeltaPack,
    DeltaPhaseFreeze,
    DeltaPhaseGolden,
    DeltaReport,
    Variant,
)
from scripts.selftest.contracts import BatchEvidence, FixtureJournal, canonical_digest
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    object_value,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.verify import verify_batch

PACK_DIGEST = "0ad08bb798f8864fcc46cb53ac4b24703e175bc8453b82ba3c58faa38a6f9dbe"

INCOMPLETE_CODES = frozenset(
    {
        "DELTA_PHASE_SET_INCOMPLETE",
        "DELTA_PHASE_EXECUTION_MISSING",
        "DELTA_PUBLISHED_SOURCE_MISSING",
        "DELTA_JOURNAL_MISSING",
        "DELTA_JOURNAL_INCOMPLETE",
        "DELTA_JOURNAL_METRICS_INCOMPLETE",
        "DELTA_PREVIEW_SET_MISSING",
        "DELTA_PREVIEW_REJECTION_MISSING",
        "DELTA_SLOT_EVIDENCE_MISSING",
        "DELTA_SLOT_SET_INCOMPLETE",
        "DELTA_CONTRACT_INSPECTION_INCOMPLETE",
        "DELTA_COMPLETE_TOOL_TRAIL_MISSING",
        "DELTA_BATCH_EXPIRED",
        "DELTA_FIXTURE_CLEANUP_INCOMPLETE",
        "DELTA_HARNESS_FAILED",
        "OWNED_ASSET_DISPOSAL_PENDING",
        "DELTA_ADMISSION_BUDGET_EXCEEDED",
        "CLEANUP_INCOMPLETE",
        "SCENARIO_CLEANUP_INCOMPLETE",
        "BATCH_EXPIRED",
        "EVIDENCE_EXPIRED",
        "EXECUTION_MISSING",
        "EVIDENCE_TRUNCATED",
        "ORACLE_NODE_MISSING",
        "ORACLE_ASSERTION_MISSING",
        "GENERATION_PROVENANCE_MISSING",
        "SUITE_EVIDENCE_MISSING",
    }
)


def load_pack(path: Path) -> DeltaPack:
    pack = DeltaPack.model_validate(read_json(path))
    if canonical_digest(pack.model_dump(mode="json")) != PACK_DIGEST:
        raise HarnessError("DELTA_FROZEN_PACK_CHANGED")
    return pack


def _semantic_mutations(design: JsonObject) -> set[str]:
    return {
        text_value(item["kind"]) + ":" + text_value(mutation["path"])
        for item in objects_value(design["scenarios"])
        for mutation in objects_value(item["mutations"])
    }


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise HarnessError("DELTA_STRING_LIST_INVALID")
    return tuple(text_value(item) for item in value)


def _generation(golden: DeltaPhaseGolden, phase: DeltaPhaseFreeze) -> list[str]:
    result: list[str] = []
    asset = phase.asset
    if (asset.api_source.api_version, phase.origin.get("api_version")) != (golden.api_version,) * 2:
        result.append("DELTA_API_VERSION_MISMATCH")
    if canonical_digest(asset.design) != asset.design_fingerprint:
        result.append("DELTA_DESIGN_FINGERPRINT_CHANGED")
    if canonical_digest(phase.coverage) != canonical_digest(asset.design.get("coverage")):
        result.append("DELTA_COVERAGE_READBACK_CHANGED")
    if (phase.origin.get("api_definition_id"), phase.origin.get("contract_fingerprint")) != (
        str(asset.api_source.api_definition_id),
        asset.api_source.contract_fingerprint,
    ):
        result.append("DELTA_ORIGIN_SOURCE_CHANGED")
    mutations = _semantic_mutations(asset.design)
    if not set(golden.required_mutations) <= mutations or set(golden.absent_mutations) & mutations:
        result.append("DELTA_GENERATED_CONSTRAINT_MISSING")
    happy = [
        item for item in objects_value(asset.design["scenarios"]) if item["kind"] == "happy_path"
    ]
    if len(happy) != 1:
        return [*result, "DELTA_HAPPY_PATH_MISSING"]
    request = object_value(object_value(happy[0]["request"])["body"])
    expected: JsonObject = {
        "value": 0,
        **({"marker": golden.marker} if golden.phase == "v2" else {}),
    }
    if canonical_digest(request) != canonical_digest(expected):
        result.append("DELTA_GENERATED_REQUEST_MISMATCH")
    oracles = {text_value(item["id"]): item for item in objects_value(asset.design["oracles"])}
    schema = oracles.get("oracle_response_schema_200", {})
    success = {
        text_value(item["id"])
        for item in objects_value(asset.design["scenarios"])
        if item["expected_category"] == "success"
    }
    if (
        canonical_digest(schema.get("expected")) != canonical_digest(golden.response_schema)
        or set(_strings(schema.get("applies_to", []))) != success
    ):
        result.append("DELTA_RESPONSE_ORACLE_MISMATCH")
    if not phase.slot.startswith("scenario:") or phase.slot != "scenario:" + text_value(
        happy[0]["id"]
    ):
        result.append("DELTA_SLOT_NOT_SYMBOLIC")
    return result


def _inspection(frozen: DeltaManifest, phase: DeltaPhaseFreeze) -> list[str]:
    inspected = phase.inspection
    rows = objects_value(inspected["items"])
    if (
        len(rows) != 1
        or inspected.get("truncated") is not False
        or inspected.get("has_more") is not False
    ):
        return ["DELTA_CONTRACT_INSPECTION_INCOMPLETE"]
    row = rows[0]
    source = phase.asset.api_source
    if (row.get("id"), row.get("version"), row.get("method"), row.get("path")) != (
        str(source.api_definition_id),
        source.api_version,
        "POST",
        f"/selftest/{frozen.batch_key}/ST-MCP-012/request",
    ):
        return ["DELTA_CONTRACT_INSPECTION_CHANGED"]
    return _source_requests(frozen, phase)


def _source_requests(frozen: DeltaManifest, phase: DeltaPhaseFreeze) -> list[str]:
    source = phase.asset.api_source
    policy: JsonObject = {
        "max_scenarios": 50,
        "include_negative": True,
        "include_auth": False,
        "include_state": False,
        "include_data_constraints": True,
        "pairwise_enabled": False,
    }
    if canonical_digest(phase.origin.get("generation_policy")) != canonical_digest(policy):
        return ["DELTA_GENERATION_POLICY_CHANGED"]
    base: JsonObject = {
        "project_id": str(frozen.installation.project_id),
        "api_definition_id": str(source.api_definition_id),
    }
    expected = (
        {**base, "version": source.api_version},
        {**base, "api_version": source.api_version, "generation_policy": policy},
        {**base, "api_version": source.api_version, "generation_policy": policy},
    )
    calls = phase.asset.calls
    if len(calls) < 3 or any(
        call.request_digest != canonical_digest(arguments)
        for call, arguments in zip(calls[:3], expected, strict=True)
    ):
        return ["DELTA_SOURCE_TOOL_ARGUMENT_CHANGED"]
    return []


def _compilation(golden: DeltaPhaseGolden, phase: DeltaPhaseFreeze) -> list[str]:
    compiled = phase.compilation
    if (compiled.get("readiness"), compiled.get("persisted"), compiled.get("execution_status")) != (
        "ready",
        False,
        "not_run",
    ):
        return ["DELTA_COMPILATION_IS_NOT_PREVIEW"]
    rows = objects_value(compiled["scenarios"])
    if len(rows) != 1:
        return ["DELTA_COMPILED_SELECTION_MISMATCH"]
    template = object_value(rows[0]["case_template"])
    if template.get("workflow_slot") != phase.slot or "workflow_id" in template:
        return ["DELTA_FUTURE_WORKFLOW_ID_IN_TEMPLATE"]
    native = object_value(object_value(rows[0]["executable_payload"])["native_definition"])
    if canonical_digest(native) != canonical_digest(phase.asset.workflow.version["definition"]):
        return ["DELTA_COMPILED_GRAPH_CHANGED"]
    if compiled.get("compilation_fingerprint") != phase.asset.compilation_fingerprint:
        return ["DELTA_COMPILATION_FINGERPRINT_CHANGED"]
    return _compiled_oracles(golden, phase, rows[0], native)


def _compiled_oracles(
    golden: DeltaPhaseGolden, phase: DeltaPhaseFreeze, row: JsonObject, native: JsonObject
) -> list[str]:
    goldens: dict[str, tuple[str, JsonValue]] = {
        "oracle_success_status": ("status_code", 200),
        "oracle_response_schema_200": ("body", golden.response_schema),
    }
    bindings = objects_value(row["oracle_bindings"])
    if {item["oracle_id"] for item in bindings} != set(goldens) or len(bindings) != 2:
        return ["DELTA_REQUIRED_ORACLE_BINDING_MISSING"]
    nodes = {node["id"]: node for node in objects_value(native["nodes"])}
    for binding in bindings:
        expression, value = goldens[text_value(binding["oracle_id"])]
        node = nodes.get(binding["node_id"])
        if node is None:
            return ["DELTA_ORACLE_NODE_MISSING"]
        config = object_value(node["config"])
        kind = "status" if binding["oracle_id"] == "oracle_success_status" else "json_schema"
        if (
            binding.get("assertion_kind"),
            node.get("type"),
            node.get("phase"),
            node.get("run_when"),
        ) != (kind, "assert", "main", "always"):
            return ["DELTA_ORACLE_KIND_CHANGED"]
        if kind == "json_schema" and config.get("assertion_type") != "json_schema":
            return ["DELTA_ORACLE_KIND_CHANGED"]
        if (config.get("expression"), config.get("operator"), config.get("source_node_id")) != (
            expression,
            "equals",
            "request",
        ):
            return ["DELTA_ORACLE_SEMANTICS_CHANGED"]
        if (
            canonical_digest(config.get("expected")) != canonical_digest(value)
            or binding["normalized_expression"] != expression
            or binding.get("expected_value_fingerprint") != canonical_digest(value)
        ):
            return ["DELTA_ORACLE_GOLDEN_CHANGED"]
    return []


def _phase_execution(
    frozen: DeltaManifest, phase: DeltaPhaseFreeze, evidence: DeltaEvidence, now: datetime
) -> list[str]:
    observations = [item for item in evidence.observations if item.phase == phase.phase]
    if len(observations) != 1:
        return ["DELTA_PHASE_EXECUTION_MISSING"]
    item = observations[0]
    if item.frozen_digest != canonical_digest(phase.model_dump(mode="json")):
        return ["DELTA_PHASE_FREEZE_CHANGED"]
    observation = item.observation
    execution = observation.execution
    if execution is None or execution.started_at <= phase.frozen_at:
        return ["DELTA_RUN_PRECEDES_FREEZE"]
    source = observation.provenance
    if source is None or source.run.run_id is None:
        return ["DELTA_PUBLISHED_SOURCE_MISSING"]
    run = item.plan_run
    if (run.get("test_plan_id"), run.get("run_id"), run.get("project_id")) != (
        str(phase.selection.plan_id),
        str(source.run.run_id),
        str(frozen.installation.project_id),
    ):
        return ["DELTA_PLAN_SOURCE_CHANGED"]
    batch = BatchEvidence(
        batch_key=phase.manifest.batch_key,
        nonce=frozen.nonce,
        pack_digest=frozen.pack_digest,
        policy_digest=phase.manifest.policy_digest,
        builds=frozen.builds,
        collected_at=item.observed_at,
        scenarios=(observation.model_copy(update={"cleanup_status": evidence.fixture_cleanup}),),
        cleanup_status=evidence.fixture_cleanup,
    )
    report = verify_batch(phase.manifest, batch, now=now)
    return [finding.code for finding in report.findings] + [
        finding.code for row in report.scenarios for finding in row.findings
    ]


def _journal(frozen: DeltaManifest, evidence: DeltaEvidence) -> list[str]:
    journal = evidence.journal
    if journal is None:
        return ["DELTA_JOURNAL_MISSING"]
    if (journal.batch_key, journal.scenario_id, journal.nonce, journal.fixture_digest) != (
        frozen.batch_key,
        "ST-MCP-012",
        frozen.nonce,
        frozen.builds.fixture,
    ):
        return ["DELTA_JOURNAL_IDENTITY_CHANGED"]
    if (
        journal.truncated
        or journal.expired
        or journal.request_count != 2
        or len(journal.entries) != 2
    ):
        return ["DELTA_JOURNAL_INCOMPLETE"]
    return _wire(frozen, journal) + _journal_budget(frozen, journal)


def _wire(frozen: DeltaManifest, journal: FixtureJournal) -> list[str]:
    for index, entry in enumerate(journal.entries):
        marker = "" if index == 0 else "delta-v2"
        if (entry.sequence, entry.method, entry.path, entry.response_status, entry.marker) != (
            index + 1,
            "POST",
            f"/selftest/{frozen.batch_key}/ST-MCP-012/request",
            200,
            marker,
        ):
            return ["DELTA_WIRE_REQUEST_MISMATCH"]
        request, response = entry.request_body, entry.response_body
        if (
            request is None
            or response is None
            or canonical_digest(request.value) != canonical_digest(0)
            or canonical_digest(response.value) != canonical_digest(0)
        ):
            return ["DELTA_WIRE_VALUE_MISMATCH"]
        if (request.marker, response.marker, entry.authorization_present, entry.cookie_present) != (
            None if index == 0 else marker,
            marker,
            False,
            False,
        ):
            return ["DELTA_WIRE_MARKER_MISMATCH"]
    return []


def _journal_budget(frozen: DeltaManifest, journal: FixtureJournal) -> list[str]:
    budget = journal.budget
    if (
        budget is None
        or budget.model_dump(include=set(type(frozen.scope).model_fields))
        != frozen.scope.model_dump()
    ):
        return ["DELTA_SHARED_BUDGET_SCOPE_CHANGED"]
    if budget.admitted_count != 2 or budget.rejected_count != 0:
        return ["DELTA_SHARED_BUDGET_COUNT_MISMATCH"]
    if (
        journal.metrics is None
        or journal.metrics.active_count != 0
        or journal.metrics.completed_count != 2
        or not journal.metrics.complete
    ):
        return ["DELTA_JOURNAL_METRICS_INCOMPLETE"]
    return []


def _previews(frozen: DeltaManifest, pack: DeltaPack, evidence: DeltaEvidence) -> list[str]:
    if [item.phase for item in evidence.previews] != ["v1", "v2"]:
        return ["DELTA_PREVIEW_SET_MISSING"]
    result: list[str] = []
    calls = {item.call_id: item for item in evidence.calls}
    for item in evidence.previews:
        rejection = item.rejection
        expected = "IMPORT_PREVIEW_STALE" if item.phase == "v1" else "IMPORT_REVIEW_REQUIRED"
        call = None if rejection is None else calls.get(rejection.call_id)
        if rejection is None or call is None:
            result.append("DELTA_PREVIEW_REJECTION_MISSING")
            continue
        if (
            rejection.code != expected
            or call.success
            or call.request_digest != canonical_digest(rejection.request)
        ):
            result.append("DELTA_PREVIEW_REJECTION_CHANGED")
        if rejection.before_execution_ids != rejection.after_execution_ids:
            result.append("DELTA_PREVIEW_CREATED_EXECUTION")
        preview = item.preview
        if (
            preview.get("project_id") != str(frozen.installation.project_id)
            or preview.get("persisted") is not True
        ):
            result.append("DELTA_PREVIEW_IDENTITY_MISMATCH")
        applied = item.commit if item.phase == "v1" else item.merge
        if applied is None or applied.get("source_sha256") != preview.get("source_sha256"):
            result.append("DELTA_PREVIEW_SOURCE_CHANGED")
        if item.phase == "v2" and (item.commit is not None or item.merge is None):
            result.append("DELTA_EXISTING_IMPORT_REVIEW_BYPASSED")
    return result


def _boundary(frozen: DeltaManifest, pack: DeltaPack, row: BoundaryObservation) -> list[str]:
    result: list[str] = []
    code = pack.expected_codes[row.variant]
    status = 404 if row.variant == "slot_foreign" else 409
    if (row.project_id, row.status_code, row.error_code, row.trace_present) != (
        frozen.installation.project_id,
        status,
        code,
        True,
    ):
        result.append("DELTA_SLOT_REJECTION_MISMATCH")
    if row.before_execution_ids != row.after_execution_ids:
        result.append("DELTA_REJECTED_SLOT_CREATED_EXECUTION")
    if row.variant == "slot_foreign":
        valid = (
            row.workflow_project_id != frozen.installation.project_id
            and row.workflow_project_id is not None
            and row.workflow_version is not None
            and row.workflow_fingerprint is not None
            and row.materialized_case_id is None
            and row.proposal_review_status == "pending"
            and row.proposal_item_id is not None
        )
    elif row.variant == "slot_unpublished":
        valid = (
            row.workflow_project_id == frozen.installation.project_id
            and row.workflow_version is None
            and row.workflow_fingerprint is None
            and row.case_current_version is None
            and row.materialized_case_id == row.case_id
        )
    else:
        valid = (
            row.workflow_project_id == frozen.installation.project_id
            and row.before_fingerprint is not None
            and row.after_fingerprint is not None
            and row.before_fingerprint != row.after_fingerprint
            and row.case_current_version is None
        )
    if not valid or row.slot is None or not row.slot.startswith("scenario:"):
        result.append("DELTA_SLOT_BOUNDARY_NOT_EXERCISED")
    return result + _slot_request(frozen, row)


def _slot_request(frozen: DeltaManifest, row: BoundaryObservation) -> list[str]:
    root = f"/projects/{frozen.installation.project_id}/test-cases/{row.case_id}"
    if row.variant == "slot_foreign":
        path = f"/mcp/write/change-sets/{row.proposal_id}/items/{row.proposal_item_id}/accept"
        request: JsonObject = {"note": "ci_fixture槽位边界"}
    elif row.variant == "slot_unpublished":
        path, request = root + "/versions", {}
    else:
        path, request = (
            root + "/runs",
            {
                "source": "draft",
                "publish_draft": True,
                "expected_draft_fingerprint": row.before_fingerprint,
            },
        )
    if (
        row.path != path
        or row.request_digest != canonical_digest(request)
        or row.proposal_id is None
    ):
        return ["DELTA_SLOT_REQUEST_CHANGED"]
    if row.slot != "scenario:scenario_happy_path":
        return ["DELTA_COMPILED_SLOT_CHANGED"]
    return []


def _identity(
    frozen: DeltaManifest, pack: DeltaPack, evidence: DeltaEvidence, now: datetime
) -> list[str]:
    result: list[str] = []
    if (
        canonical_digest(pack.model_dump(mode="json")) != frozen.pack_digest
        or frozen.pack_digest != PACK_DIGEST
    ):
        result.append("DELTA_FROZEN_PACK_CHANGED")
    if evidence.manifest_digest != canonical_digest(frozen.model_dump(mode="json")):
        result.append("DELTA_MANIFEST_CHANGED")
    if now.tzinfo is None or now > frozen.expires_at or evidence.collected_at > frozen.expires_at:
        result.append("DELTA_BATCH_EXPIRED")
    if evidence.collected_at < frozen.created_at:
        result.append("DELTA_EVIDENCE_REPLAY")
    if evidence.fixture_cleanup != "completed":
        result.append("DELTA_FIXTURE_CLEANUP_INCOMPLETE")
    if evidence.failure_code is not None:
        result.append("DELTA_HARNESS_FAILED")
    if (
        evidence.admitted_request_upper_bound > 500
        or evidence.rejected_requests
        or evidence.rejected_tool_calls
    ):
        result.append("DELTA_ADMISSION_BUDGET_EXCEEDED")
    if len(evidence.calls) != evidence.admitted_tool_calls or len(
        {item.call_id for item in evidence.calls}
    ) != len(evidence.calls):
        result.append("DELTA_TOOL_ATTEMPT_SET_CHANGED")
    return result + _disposal(frozen, evidence, now) + _trail(frozen, evidence)


def _disposal(frozen: DeltaManifest, evidence: DeltaEvidence, now: datetime) -> list[str]:
    if evidence.disposal is None:
        return ["OWNED_ASSET_DISPOSAL_PENDING"]
    receipt, expected = evidence.disposal, frozen.required_disposal.model_dump()
    if receipt.model_dump(include=set(expected)) != expected or not all(
        (receipt.containers_absent, receipt.volumes_absent, receipt.networks_absent)
    ):
        return ["DELTA_DISPOSAL_IDENTITY_MISMATCH"]
    if receipt.removed_at.tzinfo is None or not evidence.collected_at <= receipt.removed_at <= now:
        return ["DELTA_DISPOSAL_TIME_MISMATCH"]
    return []


def _trail(frozen: DeltaManifest, evidence: DeltaEvidence) -> list[str]:
    if len(evidence.boundaries) != 3 or {row.variant for row in evidence.boundaries} != {
        "slot_foreign",
        "slot_unpublished",
        "slot_drift",
    }:
        return ["DELTA_SLOT_SET_INCOMPLETE"]
    phases = ["v1:preview", "v1:stale_preview", "v1:commit"]
    generated = [
        "inspect",
        "generate",
        "coverage",
        "context",
        "compile",
        "workflow_proposal",
        "case_proposal",
    ]
    phases += ["v1:" + name for name in generated]
    phases += ["v2:preview", "v2:commit_review"] + ["v2:" + name for name in generated]
    phases += [
        name + ":case_proposal" for name in ("slot_foreign", "slot_unpublished", "slot_drift")
    ]
    if [call.phase for call in evidence.calls] != phases:
        return ["DELTA_COMPLETE_TOOL_TRAIL_MISSING"]
    for call in evidence.calls:
        phase = "v1" if call.phase.startswith("v1:") else "v2"
        if call.batch_key != frozen.batch_key + "-" + phase:
            return ["DELTA_CALL_BATCH_CHANGED"]
    failed = {call.call_id for call in evidence.calls if not call.success}
    rejected = {row.rejection.call_id for row in evidence.previews if row.rejection is not None}
    if failed != rejected:
        return ["DELTA_UNKNOWN_TOOL_FAILURE"]
    return []


def _verify(
    frozen: DeltaManifest, pack: DeltaPack, evidence: DeltaEvidence, *, now: datetime | None = None
) -> DeltaReport:
    checked = now or datetime.now(UTC)
    findings = _identity(frozen, pack, evidence, checked)
    phase_errors: list[str] = []
    if [item.phase for item in evidence.phases] != ["v1", "v2"]:
        phase_errors.append("DELTA_PHASE_SET_INCOMPLETE")
    else:
        for golden, phase in zip(pack.phases, evidence.phases, strict=True):
            if (
                phase.manifest.project_id,
                phase.manifest.builds,
                phase.manifest.nonce,
                phase.manifest.batch_key,
            ) != (
                frozen.installation.project_id,
                frozen.builds,
                frozen.nonce,
                frozen.batch_key + "-" + golden.phase,
            ):
                phase_errors.append("DELTA_PHASE_IDENTITY_CHANGED")
            phase_errors.extend(_generation(golden, phase))
            phase_errors.extend(_inspection(frozen, phase))
            phase_errors.extend(_compilation(golden, phase))
            phase_errors.extend(_phase_execution(frozen, phase, evidence, checked))
        before, after = evidence.phases
        if (
            before.asset.api_source.api_definition_id != after.asset.api_source.api_definition_id
            or before.asset.api_source.contract_fingerprint
            == after.asset.api_source.contract_fingerprint
            or before.asset.design_fingerprint == after.asset.design_fingerprint
            or before.manifest.batch_key == after.manifest.batch_key
            or canonical_digest(before.asset.design["coverage"])
            == canonical_digest(after.asset.design["coverage"])
        ):
            phase_errors.append("DELTA_NOT_A_REAL_VERSION_CHANGE")
    checks: list[DeltaCheck] = []
    for variant in get_args(Variant):
        errors = list(phase_errors)
        if variant == "preview_freeze":
            errors.extend(_previews(frozen, pack, evidence))
        elif variant.startswith("slot_") and variant != "slot_positive":
            rows = [item for item in evidence.boundaries if item.variant == variant]
            errors.extend(
                ["DELTA_SLOT_EVIDENCE_MISSING"]
                if len(rows) != 1
                else _boundary(frozen, pack, rows[0])
            )
        else:
            errors.extend(_journal(frozen, evidence))
        unique = tuple(dict.fromkeys(errors))
        checks.append(
            DeltaCheck(
                variant=variant,
                status="matched"
                if not unique
                else "incomplete"
                if set(unique) <= INCOMPLETE_CODES
                else "mismatched",
                findings=unique,
            )
        )
    all_errors = findings + [code for row in checks for code in row.findings]
    mismatched = bool(set(findings) - INCOMPLETE_CODES) or any(
        row.status == "mismatched" for row in checks
    )
    return DeltaReport(
        pack_digest=frozen.pack_digest,
        manifest_digest=evidence.manifest_digest,
        batch_key=frozen.batch_key,
        verdict="passed" if not all_errors else "failed" if mismatched else "blocked",
        exit_code=0 if not all_errors else 1 if mismatched else 2,
        findings=tuple(dict.fromkeys(findings)),
        scenarios=tuple(checks),
    )


def verify(
    frozen: DeltaManifest, pack: DeltaPack, evidence: DeltaEvidence, *, now: datetime | None = None
) -> DeltaReport:
    try:
        return _verify(frozen, pack, evidence, now=now)
    except (HarnessError, KeyError, TypeError, ValueError):
        return DeltaReport(
            pack_digest=frozen.pack_digest,
            manifest_digest=evidence.manifest_digest,
            batch_key=frozen.batch_key,
            verdict="blocked",
            exit_code=2,
            findings=("DELTA_EVIDENCE_INVALID",),
            scenarios=tuple(
                DeltaCheck(
                    variant=variant, status="incomplete", findings=("DELTA_EVIDENCE_INVALID",)
                )
                for variant in get_args(Variant)
            ),
        )


def write_reports(report: DeltaReport, evidence: DeltaEvidence, directory: Path) -> None:
    write_json(directory / "verification.json", report)
    for raw in (True, False):
        root = Element(
            "testsuite", name="contract-delta-native" if raw else "contract-delta-verification"
        )
        if raw:
            for item in evidence.observations:
                execution = item.observation.execution
                case = SubElement(root, "testcase", name=item.phase)
                if execution is None or execution.status != "passed":
                    SubElement(case, "failure", message="原生执行未通过")
        else:
            for check in report.scenarios:
                case = SubElement(root, "testcase", name=check.variant)
                if check.status != "matched":
                    SubElement(case, "failure", message=",".join(check.findings))
            if report.findings:
                case = SubElement(root, "testcase", name="batch-global")
                SubElement(case, "failure", message=",".join(report.findings))
        root.set("tests", str(len(root)))
        (directory / ("execution.junit.xml" if raw else "verification.junit.xml")).write_bytes(
            tostring(root, encoding="utf-8", xml_declaration=True)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="独立只读核验契约变更和槽位回填")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frozen = DeltaManifest.model_validate(read_json(args.manifest))
    evidence = DeltaEvidence.model_validate(read_json(args.evidence))
    report = verify(frozen, load_pack(args.pack), evidence)
    args.output.mkdir(parents=True, exist_ok=True)
    write_reports(report, evidence, args.output)
    raise SystemExit(report.exit_code)


if __name__ == "__main__":
    main()
