"""Frozen actual SDK/ASGI receipts; independent tamper and admission counterexamples."""

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contract_delta_budget import DeltaBudget  # noqa: E402
from scripts.selftest.contract_delta_contracts import DeltaEvidence, DeltaManifest  # noqa: E402
from scripts.selftest.contract_delta_verify import load_pack, verify, write_reports  # noqa: E402
from scripts.selftest.contracts import TargetDisposalReceipt, canonical_digest  # noqa: E402
from scripts.selftest.io import HarnessError, read_json  # noqa: E402


@pytest.fixture
def captured():
    base = ROOT / "backend/tests/fixtures/contract_delta_actual"
    manifest = DeltaManifest.model_validate(read_json(base / "manifest.json"))
    evidence = DeltaEvidence.model_validate(read_json(base / "evidence.json"))
    receipt = TargetDisposalReceipt(
        **manifest.required_disposal.model_dump(),
        removed_at=evidence.collected_at,
        containers_absent=True,
        volumes_absent=True,
        networks_absent=True,
    )
    return (
        manifest,
        evidence.model_copy(update={"disposal": receipt}),
        load_pack(ROOT / "selftest/packs/contract-delta-v1/pack.json"),
    )


def codes(report):
    return set(report.findings) | {code for row in report.scenarios for code in row.findings}


def test_historical_fixture_normalization_changes_only_model_defaults_and_phase_digests():
    base = ROOT / "backend/tests/fixtures/contract_delta_actual"
    metadata = read_json(base / "schema-normalization.json")
    captured = base / "evidence.captured-v1.json"
    current = base / "evidence.json"
    assert hashlib.sha256(captured.read_bytes()).hexdigest() == metadata["original_sha256"]
    assert hashlib.sha256(current.read_bytes()).hexdigest() == metadata["normalized_sha256"]
    normalized = DeltaEvidence.model_validate(json.loads(captured.read_text())).model_dump(
        mode="json"
    )
    for row in normalized["observations"]:
        phase = next(item for item in normalized["phases"] if item["phase"] == row["phase"])
        row["frozen_digest"] = canonical_digest(phase)
    assert normalized == read_json(current)


def test_captured_two_real_native_runs_and_three_rejections_have_seven_fixed_checks(
    captured, tmp_path
):
    manifest, evidence, pack = captured
    report = verify(manifest, pack, evidence, now=evidence.collected_at)
    assert report.exit_code == 0, report.model_dump_json(indent=2)
    assert len(report.scenarios) == 7 and all(row.status == "matched" for row in report.scenarios)
    assert len(evidence.calls) == 22 and sum(not call.success for call in evidence.calls) == 2
    write_reports(report, evidence, tmp_path)
    assert "<failure" not in (tmp_path / "verification.junit.xml").read_text()
    assert 'tests="2"' in (tmp_path / "execution.junit.xml").read_text()


def _mutate_phase(data, mutation, manifest):
    after = data["phases"][1]
    if mutation == "missing_phase":
        data["phases"].pop()
    elif mutation == "missing_observation":
        data["observations"].pop()
    elif mutation == "old_version":
        after["asset"]["api_source"]["api_version"] = 1
    elif mutation == "old_design":
        after["asset"]["design"] = data["phases"][0]["asset"]["design"]
    elif mutation == "bad_evidence":
        after["compilation"]["scenarios"] = "broken"
    else:
        return False
    return True


def _mutate_plan(data, mutation, manifest):
    after = data["phases"][1]
    if mutation == "operator":
        row = after["compilation"]["scenarios"][0]
        for graph in (
            row["executable_payload"]["native_definition"],
            after["asset"]["workflow"]["version"]["definition"],
        ):
            next(node for node in graph["nodes"] if node["id"] == "assert_status")["config"][
                "operator"
            ] = "not_equals"
    elif mutation == "preview_run":
        data["observations"][1]["observation"]["execution"]["run_purpose"] = "preview"
    elif mutation == "postrun_freeze":
        after["frozen_at"] = data["observations"][1]["observation"]["execution"]["completed_at"]
        data["observations"][1]["frozen_digest"] = canonical_digest(after)
    elif mutation == "other_plan":
        data["observations"][1]["plan_run"]["test_plan_id"] = str(uuid4())
    else:
        return False
    return True


def _mutate_protocol(data, mutation, manifest):
    if mutation == "missing_attempt":
        data["calls"].pop(1)
        data["admitted_tool_calls"] -= 1
    elif mutation == "unknown_failure":
        data["calls"][-1]["success"] = False
    elif mutation == "wrong_rejection":
        data["previews"][0]["rejection"]["code"] = "OTHER"
    elif mutation == "cleanup":
        data["fixture_cleanup"] = "failed"
    elif mutation == "disposal":
        data["disposal"]["target_container_id"] = "f" * 64
    else:
        return False
    return True


def _mutate_slots(data, mutation, manifest):
    if mutation == "foreign_same_project":
        data["boundaries"][0]["workflow_project_id"] = str(manifest.installation.project_id)
    elif mutation == "unpublished_published":
        data["boundaries"][1]["case_current_version"] = 1
    elif mutation == "drift_equal":
        data["boundaries"][2]["after_fingerprint"] = data["boundaries"][2]["before_fingerprint"]
    elif mutation == "unexpected_execution":
        data["boundaries"][2]["after_execution_ids"].append(str(uuid4()))
    else:
        return False
    return True


def _mutate_journal(data, mutation, manifest):
    if mutation == "missing_journal":
        data["journal"] = None
    elif mutation == "wire_nonce":
        data["journal"]["nonce"] = "foreign"
    elif mutation == "false_is_not_zero":
        data["journal"]["entries"][0]["request_body"]["value"] = False
    elif mutation == "wrong_marker":
        data["journal"]["entries"][1]["response_body"]["marker"] = "stale"
    elif mutation == "journal_count":
        data["journal"]["request_count"] = 3
    elif mutation == "scope_count":
        data["journal"]["budget"]["admitted_count"] = 3
    elif mutation == "scope_nonce":
        data["journal"]["budget"]["nonce"] = "foreign"
    else:
        return False
    return True


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing_phase", "DELTA_PHASE_SET_INCOMPLETE"),
        ("missing_observation", "DELTA_PHASE_EXECUTION_MISSING"),
        ("missing_journal", "DELTA_JOURNAL_MISSING"),
        ("old_version", "DELTA_API_VERSION_MISMATCH"),
        ("old_design", "DELTA_GENERATED_CONSTRAINT_MISSING"),
        ("operator", "DELTA_ORACLE_SEMANTICS_CHANGED"),
        ("preview_run", "EXECUTION_BINDING_MISMATCH"),
        ("postrun_freeze", "DELTA_RUN_PRECEDES_FREEZE"),
        ("other_plan", "DELTA_PLAN_SOURCE_CHANGED"),
        ("missing_attempt", "DELTA_COMPLETE_TOOL_TRAIL_MISSING"),
        ("unknown_failure", "DELTA_UNKNOWN_TOOL_FAILURE"),
        ("wrong_rejection", "DELTA_PREVIEW_REJECTION_CHANGED"),
        ("foreign_same_project", "DELTA_SLOT_BOUNDARY_NOT_EXERCISED"),
        ("unpublished_published", "DELTA_SLOT_BOUNDARY_NOT_EXERCISED"),
        ("drift_equal", "DELTA_SLOT_BOUNDARY_NOT_EXERCISED"),
        ("unexpected_execution", "DELTA_REJECTED_SLOT_CREATED_EXECUTION"),
        ("wire_nonce", "DELTA_JOURNAL_IDENTITY_CHANGED"),
        ("false_is_not_zero", "DELTA_WIRE_VALUE_MISMATCH"),
        ("wrong_marker", "DELTA_WIRE_MARKER_MISMATCH"),
        ("journal_count", "DELTA_JOURNAL_INCOMPLETE"),
        ("scope_count", "DELTA_SHARED_BUDGET_COUNT_MISMATCH"),
        ("scope_nonce", "DELTA_SHARED_BUDGET_SCOPE_CHANGED"),
        ("cleanup", "DELTA_FIXTURE_CLEANUP_INCOMPLETE"),
        ("disposal", "DELTA_DISPOSAL_IDENTITY_MISMATCH"),
        ("bad_evidence", "DELTA_EVIDENCE_INVALID"),
    ],
)
def test_independent_o_rejects_replayed_missing_swapped_or_tampered_evidence(
    captured, mutation, expected
):
    manifest, evidence, pack = captured
    data = evidence.model_dump(mode="json")
    helpers = (_mutate_phase, _mutate_plan, _mutate_protocol, _mutate_slots, _mutate_journal)
    assert any(helper(data, mutation, manifest) for helper in helpers)
    changed = DeltaEvidence.model_validate(data)
    report = verify(manifest, pack, changed, now=evidence.collected_at)
    assert report.exit_code != 0 and expected in codes(report), report.model_dump_json(indent=2)
    assert len(report.scenarios) == 7


def test_expiry_and_mutating_both_pack_and_manifest_cannot_remove_required_denominator(captured):
    manifest, evidence, pack = captured
    expired = verify(manifest, pack, evidence, now=manifest.expires_at + timedelta(seconds=1))
    assert expired.exit_code != 0 and "DELTA_BATCH_EXPIRED" in codes(expired)
    smaller = pack.model_copy(update={"variants": pack.variants[:1]})
    shrunk = verify(manifest, smaller, evidence, now=evidence.collected_at)
    assert shrunk.exit_code != 0 and len(shrunk.scenarios) == 7
    assert "DELTA_FROZEN_PACK_CHANGED" in codes(shrunk)


def test_admission_refuses_501st_request_and_preserves_rejection_before_any_dispatch(
    tmp_path, captured
):
    budget = DeltaBudget(tmp_path, datetime.now(UTC) + timedelta(seconds=60))
    budget.admit(500)
    with pytest.raises(HarnessError, match="ADMISSION_BUDGET_EXCEEDED"):
        budget.admit()
    assert budget.requests == 500 and budget.rejected_requests == 1
    receipt = read_json(budget.path)
    assert receipt["conservative_request_upper_bound"] == 500 and receipt["rejected_requests"] == 1


def test_admission_deadline_does_not_grant_more_execution_time_but_allows_bounded_cleanup(
    tmp_path, captured
):
    from datetime import UTC, datetime

    budget = DeltaBudget(tmp_path, datetime.now(UTC) - timedelta(seconds=1))
    with pytest.raises(HarnessError, match="ADMISSION_BUDGET_EXCEEDED"):
        budget.admit(tool=True)
    budget.admit(cleanup=True)
    assert budget.requests == 1 and budget.tools == 0 and budget.rejected_tools == 1
