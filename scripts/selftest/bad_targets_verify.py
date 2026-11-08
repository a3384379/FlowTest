"""Recompute both O results and verify immutable paired controls without product imports."""

from __future__ import annotations

from datetime import UTC, datetime

from scripts.selftest.bad_targets_contracts import (
    SCENARIOS,
    BadTargetPhase,
    BadTargetsResult,
    load_bad_targets_pack,
)
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.verify import verify_batch


def verify_bad_targets(result: BadTargetsResult, *, now: datetime | None = None) -> tuple[str, ...]:
    checked = now or datetime.now(UTC)
    reasons: list[str] = []
    pack = load_bad_targets_pack()
    if result.pack_digest != pack.digest:
        reasons.append("BADTARGET_PACK_DIGEST_MISMATCH")
    if len(result.phases) != 2 or tuple(item.phase for item in result.phases) != (
        "positive",
        "fault",
    ):
        return (*reasons, "BADTARGET_PAIRED_CONTROL_MISSING")
    for phase in result.phases:
        manifest = phase.manifest
        if (
            tuple(manifest.expected_scenario_set) != SCENARIOS
            or tuple(manifest.required_scenario_set) != SCENARIOS
            or tuple(manifest.trusted_required_scenario_set) != SCENARIOS
            or manifest.verification_scope != "full_pack"
            or (manifest.batch_key, manifest.nonce, manifest.builds, manifest.pack_digest)
            != (result.batch_key, result.nonce, result.builds, result.pack_digest)
            or manifest.created_at != result.frozen_at
        ):
            reasons.append("BADTARGET_FROZEN_IDENTITY_MISMATCH")
        report = verify_batch(manifest, phase.evidence, now=checked)
        if report.batch_verdict != "passed" or report.evidence_integrity != "complete":
            reasons.append("BADTARGET_PHASE_VERIFICATION_FAILED")
        if canonical_digest(report.model_dump(mode="json")) != canonical_digest(
            phase.report.model_dump(mode="json")
        ):
            reasons.append("BADTARGET_STORED_VERDICT_MISMATCH")
        reasons.extend(_wire_reasons(phase, fault=phase.phase == "fault"))
        if len(manifest.scenarios) == 3:
            reasons.extend(_frozen_goldens(phase))
        else:
            reasons.append("BADTARGET_FROZEN_DENOMINATOR_MISMATCH")
    reasons.extend(_pair_reasons(result))
    reasons.extend(_freeze_reasons(result))
    reasons.extend(_shared_budget_reasons(result))
    total = sum(
        scene.journal.request_count
        for phase in result.phases
        for scene in phase.evidence.scenarios
        if scene.journal is not None
    )
    calls = {
        call.call_id: call
        for scene in result.phases[0].evidence.scenarios
        if scene.provenance is not None
        for call in scene.provenance.calls
    }
    admitted = result.admission
    if (
        total != 8
        or admitted.target_requests != total
        or admitted.tool_attempts != len(calls)
        or admitted.tool_attempts > 100
        or admitted.direct_http_attempts <= 0
        or admitted.direct_http_attempts + admitted.tool_attempts + total > 500
        or admitted.deadline != result.phases[0].manifest.expires_at
        or checked > admitted.deadline
    ):
        reasons.append("BADTARGET_BUDGET_OR_TARGET_COUNT_MISMATCH")
    return tuple(dict.fromkeys(reasons))


def _wire_reasons(phase: BadTargetPhase, *, fault: bool) -> list[str]:
    reasons: list[str] = []
    pack = load_bad_targets_pack()
    by_id = {item.scenario_id: item for item in phase.evidence.scenarios}
    if set(by_id) != set(SCENARIOS):
        return ["BADTARGET_SCENARIO_SET_MISMATCH"]
    for golden in pack.scenarios:
        observed = by_id[golden.scenario_id]
        journal = observed.journal
        if journal is None or len(journal.entries) != golden.requests:
            reasons.append("BADTARGET_JOURNAL_INCOMPLETE")
            continue
        for index, entry in enumerate(journal.entries):
            seed = golden.requests == 2 and index == 0
            expected_value = golden.bad_value if fault and not seed else golden.good_value
            body = entry.response_body
            expected_path = f"/selftest/{phase.manifest.batch_key}/{golden.scenario_id}/" + (
                "sequence" if golden.requests == 2 and not seed else "request"
            )
            if (
                entry.sequence != index + 1
                or entry.path != expected_path
                or entry.method != ("POST" if seed else "GET")
                or body is None
                or canonical_digest(body.value) != canonical_digest(expected_value)
                or body.iteration_key
                != ("dependency-good" if golden.requests == 2 and not seed else "")
                or entry.authorization_present
                or entry.cookie_present
                or entry.request_value_present is not seed
                or (
                    seed
                    and (
                        entry.request_body is None
                        or canonical_digest(entry.request_body.value)
                        != canonical_digest(golden.good_value)
                    )
                )
            ):
                reasons.append("BADTARGET_WIRE_CAUSALITY_MISMATCH")
    return reasons


def _pair_reasons(result: BadTargetsResult) -> list[str]:
    positive, fault = result.phases
    reasons: list[str] = []
    first = {item.scenario_id: item for item in positive.evidence.scenarios}
    second = {item.scenario_id: item for item in fault.evidence.scenarios}
    if set(first) != set(SCENARIOS) or set(second) != set(SCENARIOS):
        return ["BADTARGET_PAIR_SET_INCOMPLETE"]
    completed, started = [], []
    run_ids: list[set[object]] = [set(), set()]
    for identity in SCENARIOS:
        good, bad = first[identity], second[identity]
        if (
            good.execution is None
            or bad.execution is None
            or good.provenance is None
            or bad.provenance is None
        ):
            reasons.append("BADTARGET_PAIR_EXECUTION_MISSING")
            continue
        a, b = good.provenance, bad.provenance
        refs = (
            "api_source",
            "design_sources",
            "design_fingerprint",
            "combined_design_fingerprint",
            "compilation_fingerprint",
            "catalog_digest",
            "oracle_bindings",
            "calls",
            "workflow_proposal",
            "case_proposal",
            "workflow",
            "case",
            "suite",
        )
        if any(getattr(a, name) != getattr(b, name) for name in refs) or (
            a.run.target_snapshot_digest != b.run.target_snapshot_digest
            or a.run.run_id == b.run.run_id
            or good.execution.id == bad.execution.id
        ):
            reasons.append("BADTARGET_IMMUTABLE_PAIR_MISMATCH")
        if good.execution.completed_at is None:
            reasons.append("BADTARGET_POSITIVE_NOT_TERMINAL")
        else:
            completed.append(good.execution.completed_at)
        started.append(bad.execution.started_at)
        run_ids[0].add(a.run.run_id)
        run_ids[1].add(b.run.run_id)
    if completed and started and max(completed) > min(started):
        reasons.append("BADTARGET_CONTROL_ORDER_MISMATCH")
    if len(run_ids[0]) != 1 or len(run_ids[1]) != 1 or run_ids[0] & run_ids[1]:
        reasons.append("BADTARGET_FORMAL_RUN_SET_MISMATCH")
    good_regs = {item.scenario_id: item for item in positive.registrations}
    bad_regs = {item.scenario_id: item for item in fault.registrations}
    if set(good_regs) != set(SCENARIOS) or set(bad_regs) != set(SCENARIOS):
        reasons.append("BADTARGET_REGISTRATION_SET_MISMATCH")
    elif any(
        good_regs[key].fixture_epoch != bad_regs[key].fixture_epoch
        or good_regs[key].registration_epoch == bad_regs[key].registration_epoch
        for key in SCENARIOS
    ):
        reasons.append("BADTARGET_REGISTRATION_REPLAY")
    return reasons


def _shared_budget_reasons(result: BadTargetsResult) -> list[str]:
    scope = result.fixture_budget
    if (
        scope.parent_batch_key != result.batch_key
        or scope.nonce != result.nonce
        or scope.limit != 500
        or scope.expires_at != result.admission.deadline.timestamp()
    ):
        return ["BADTARGET_SHARED_BUDGET_IDENTITY_MISMATCH"]
    counters = []
    registration_epochs: set[str] = set()
    for index, phase in enumerate(result.phases):
        receipts = [
            scene.journal.budget
            for scene in phase.evidence.scenarios
            if scene.journal is not None and scene.journal.budget is not None
        ]
        if len(receipts) != 3:
            return ["BADTARGET_SHARED_BUDGET_RECEIPT_MISSING"]
        for receipt in receipts:
            registration_epochs.add(receipt.registration_epoch)
            if (
                receipt.parent_batch_key != scope.parent_batch_key
                or receipt.nonce != scope.nonce
                or receipt.limit != scope.limit
                or receipt.expires_at != scope.expires_at
                or receipt.fixture_digest != result.builds.fixture.removeprefix("sha256:")
                or receipt.rejected_count
                or receipt.admitted_count > (index + 1) * 4
            ):
                return ["BADTARGET_SHARED_BUDGET_RECEIPT_MISMATCH"]
        counters.append(max(item.admitted_count for item in receipts))
    if counters != [4, 8] or len(registration_epochs) != 1:
        return ["BADTARGET_SHARED_BUDGET_COUNTER_MISMATCH"]
    return []


def _frozen_goldens(phase: BadTargetPhase) -> list[str]:
    """Never accept a caller-edited manifest as the independent expected body or status."""
    from collections import Counter

    reasons: list[str] = []
    pack = load_bad_targets_pack()
    fault = phase.phase == "fault"
    for expected, golden in zip(phase.manifest.scenarios, pack.scenarios, strict=True):
        wanted = expected.expected
        count = golden.requests
        failures = [item for item in wanted.assertions if not item.passed]
        if (
            expected.variant_key != golden.fault_kind
            or wanted.execution_status != ("failed" if fault else "passed")
            or wanted.request_count != count
            or wanted.error_code != ("WORKFLOW_ASSERTION_FAILED" if fault else None)
            or wanted.phase != ("main" if fault else None)
            or len(failures) != int(fault)
            or (fault and failures[0].node_id != wanted.node_id)
            or len(wanted.assertions) != count * 2
            or len(expected.expected_oracle_bindings) != count * 2
            or not {"execution", "assertions", "fixture_journal", "provenance"}
            <= set(expected.required_evidence)
            or not expected.require_suite_provenance
        ):
            reasons.append("BADTARGET_FROZEN_GOLDEN_CHANGED")
            continue
        actual = Counter(
            canonical_digest([item.expected, item.actual, item.passed])
            for item in wanted.assertions
        )
        fixed: list[str] = []
        for index in range(count):
            fixed.append(canonical_digest([golden.status, golden.status, True]))
            response = {
                "actual": golden.actual,
                "code": golden.bad_code if fault else golden.good_code,
                "value": golden.bad_value if fault and index == count - 1 else golden.good_value,
                "marker": "",
                "branch": "",
                "iteration_key": "dependency-good" if count == 2 and index == 1 else "",
                "request_count": index + 1,
                "fixture_epoch": phase.manifest.fixture_epoch,
            }
            fixed.append(
                canonical_digest([golden.schema_, response, not (fault and index == count - 1)])
            )
        if actual != Counter(fixed):
            reasons.append("BADTARGET_FROZEN_GOLDEN_CHANGED")
        bindings = {item.node_id: item for item in expected.expected_oracle_bindings}
        if any(
            item.node_id not in bindings
            or canonical_digest(item.expected) != bindings[item.node_id].expected_value_digest
            for item in wanted.assertions
        ):
            reasons.append("BADTARGET_FROZEN_BINDING_CHANGED")
    return reasons


def _freeze_reasons(result: BadTargetsResult) -> list[str]:
    if result.expectations_frozen_at.tzinfo is None:
        return ["BADTARGET_EXPECTATIONS_NOT_PRE_RUN"]
    actual = tuple(
        canonical_digest(phase.manifest.model_dump(mode="json")) for phase in result.phases
    )
    if actual != result.expectation_digests:
        return ["BADTARGET_EXPECTATION_RECEIPT_MISMATCH"]
    executions = [
        scene.execution
        for scene in result.phases[0].evidence.scenarios
        if scene.execution is not None
    ]
    if (
        len(executions) != 3
        or result.frozen_at > result.expectations_frozen_at
        or any(result.expectations_frozen_at > execution.started_at for execution in executions)
    ):
        return ["BADTARGET_EXPECTATIONS_NOT_PRE_RUN"]
    return []


def main() -> None:
    """Re-run the independent paired verifier against saved safe receipts."""
    import argparse
    from pathlib import Path
    from xml.etree.ElementTree import Element, SubElement, tostring

    from pydantic import ValidationError
    from scripts.selftest.io import HarnessError, read_json, write_json

    parser = argparse.ArgumentParser(description="核验同版本正确目标/坏目标两轮的独立证据")
    parser.add_argument("result", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = BadTargetsResult.model_validate(read_json(arguments.result))
        reasons = verify_bad_targets(result)
        code = 0 if not reasons else 1
        verdict = "passed" if not reasons else "blocked"
    except (HarnessError, ValidationError, OSError, ValueError):
        reasons, code, verdict = ("BADTARGET_VERIFIER_INPUT_INVALID",), 2, "blocked"
    write_json(
        arguments.output_dir / "badtargets-verification.json",
        {
            "provenance": "local_untrusted",
            "batch_verdict": verdict,
            "exit_code": code,
            "reason_codes": list(reasons),
            "scope": "synthetic_target_fault_detection",
        },
    )
    suite = Element("testsuite", name="坏目标独立核验", tests="3", failures="3" if reasons else "0")
    for identity in SCENARIOS:
        case = SubElement(suite, "testcase", name=identity)
        if reasons:
            SubElement(case, "failure", message=",".join(reasons))
    (arguments.output_dir / "verification.junit.xml").write_bytes(
        tostring(suite, encoding="utf-8", xml_declaration=True)
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
