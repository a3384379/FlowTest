"""Typed synthetic oracle mutations; real SDK transport tests are a separate layer."""

import os
import subprocess
import sys
from pathlib import Path
from xml.etree.ElementTree import parse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fixtures.mcp_fault_unit_evidence import unit_evidence
from scripts.selftest.io import read_json, write_json
from scripts.selftest.mcp_fault_verify import verify, write_reports

ROOT = Path(__file__).resolve().parents[2]


def codes(report):
    return {f.code for f in report.findings} | {
        f.code for row in report.scenarios for f in row.findings
    }


def test_synthetic_oracle_fixture_matches_frozen_fourteen_but_raw_junit_remains_failed(tmp_path):
    manifest, evidence, authority = unit_evidence()
    report = verify(manifest, evidence, authority)
    assert report.exit_code == 0 and len(report.scenarios) == 14
    write_reports(report, evidence, tmp_path)
    assert parse(tmp_path / "verification.junit.xml").getroot().find("./testcase/failure") is None
    assert parse(tmp_path / "execution.junit.xml").getroot().find("./testcase/failure") is not None


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("missing_scenario", "FAULT_REQUIRED_SCENARIO_MISSING"),
        ("duplicate_scenario", "FAULT_SCENARIO_SET_MISMATCH"),
        ("nonce", "FAULT_BATCH_IDENTITY_MISMATCH"),
        ("build", "FAULT_BUILD_SOURCE_MISMATCH"),
        ("cleanup", "FAULT_BUDGET_OR_PROCESS_CLEANUP_INCOMPLETE"),
        ("missing_removal", "FAULT_EXACT_PROCESS_REMOVAL_RECEIPT_MISSING"),
        ("wrong_pid", "FAULT_EXACT_PROCESS_REMOVAL_RECEIPT_MISSING"),
        ("missing_discovery", "FAULT_DISCOVERY_OR_CATALOG_RESPONSE_MISSING"),
        ("missing_frame", "FAULT_FRAME_RECEIPT_MISSING_OR_MISMATCH"),
        ("extra_attempt", "FAULT_SINGLE_DISPATCH_RECEIPT_REQUIRED"),
        ("no_dispatch", "FAULT_SINGLE_DISPATCH_RECEIPT_REQUIRED"),
        ("rpc_id_type", "FAULT_WIRE_REQUEST_BINDING_MISMATCH"),
        ("no_kill", "FAULT_NOT_APPLIED_OR_PROCESS_NOT_REMOVED"),
        ("raw_success", "FAULT_RAW_SDK_RESULT_MISMATCH"),
        ("wrong_design", "FAULT_UNKNOWN_MUTATION_FROZEN_DESIGN_MISMATCH"),
        ("inactive_identity", "FAULT_INACTIVE_FIXTURE_BINDING_MISMATCH"),
        ("budget_rejected", "FAULT_BUDGET_OR_PROCESS_CLEANUP_INCOMPLETE"),
    ],
)
def test_oracle_rejects_evidence_tampering_with_specific_finding(mutation, expected):
    manifest, evidence, authority = unit_evidence()
    row = mutate_call(evidence.scenarios[0], mutation)
    rows = (row, *evidence.scenarios[1:])
    global_updates = {
        "missing_scenario": {"scenarios": rows[1:]},
        "duplicate_scenario": {"scenarios": (*rows, rows[0])},
        "nonce": {"nonce": "foreign"},
        "build": {"stack": evidence.stack.model_copy(update={"candidate_image_digest": "foreign"})},
        "cleanup": {"process_cleanup_complete": False},
        "inactive_identity": {
            "inactive_fixture": evidence.inactive_fixture.model_copy(
                update={"creator_id": manifest.owner_user_id}
            )
        },
        "budget_rejected": {"http_rejected": 1},
    }
    changed = evidence.model_copy(
        update={
            "scenarios": mutate_state(manifest, rows, mutation),
            **global_updates.get(mutation, {}),
        }
    )
    report = verify(manifest, changed, authority)
    assert report.exit_code != 0 and expected in codes(report)


def mutate_call(row, mutation):
    updates = {
        "missing_removal": {"dispatch": row.dispatch.model_copy(update={"removal": None})},
        "wrong_pid": {
            "dispatch": row.dispatch.model_copy(
                update={"process": row.dispatch.process.model_copy(update={"pid": 999999})}
            )
        },
        "missing_discovery": {"responses": row.responses[1:]},
        "missing_frame": {"frames": row.frames[:-1]},
        "extra_attempt": {"requests": (*row.requests, row.requests[-1])},
        "no_dispatch": {"requests": row.requests[:-1]},
        "rpc_id_type": {"dispatch": row.dispatch.model_copy(update={"request_id": "2"})},
        "raw_success": {"result": row.result.model_copy(update={"complete": True})},
    }
    return row.model_copy(update=updates.get(mutation, {}))


def mutate_state(manifest, rows, mutation):
    if mutation == "no_kill":
        index = next(i for i, s in enumerate(manifest.scenarios) if s.fault == "server_crash")
        chosen = rows[index]
        replacement = chosen.model_copy(
            update={"dispatch": chosen.dispatch.model_copy(update={"server_killed": False})}
        )
    elif mutation == "wrong_design":
        index = next(i for i, s in enumerate(manifest.scenarios) if s.fault == "unknown_mutation")
        chosen = rows[index]
        page = chosen.after.pages[0]
        resource = page.items[-1]
        item = resource.items[0]
        design = item.design.model_copy(update={"document_digest": "0" * 64})
        resource = resource.model_copy(
            update={"items": (item.model_copy(update={"design": design}),)}
        )
        page = page.model_copy(update={"items": (*page.items[:-1], resource)})
        replacement = chosen.model_copy(
            update={"after": chosen.after.model_copy(update={"pages": (page,)})}
        )
    else:
        return rows
    return (*rows[:index], replacement, *rows[index + 1 :])


def test_expiry_does_not_hide_the_specific_missing_receipt_finding_and_global_junit(tmp_path):
    from datetime import timedelta

    manifest, evidence, authority = unit_evidence()
    first = evidence.scenarios[0]
    changed = evidence.model_copy(
        update={
            "scenarios": (
                first.model_copy(update={"frames": first.frames[:-1]}),
                *evidence.scenarios[1:],
            )
        }
    )
    report = verify(manifest, changed, authority, now=manifest.expires_at + timedelta(seconds=1))
    assert report.exit_code != 0
    assert {
        "FAULT_EVIDENCE_EXPIRED_OR_TIME_MISMATCH",
        "FAULT_FRAME_RECEIPT_MISSING_OR_MISMATCH",
    } <= codes(report)
    write_reports(report, changed, tmp_path)
    root = parse(tmp_path / "verification.junit.xml").getroot()
    assert int(root.attrib["tests"]) == 15
    assert root.find("./testcase[@name='batch-global']/failure") is not None


def test_real_verifier_cli_on_synthetic_copy_is_nonzero_and_keeps_original_hashes(tmp_path):
    import hashlib

    manifest, evidence, authority = unit_evidence()
    for name, value in (("manifest", manifest), ("authority", authority), ("evidence", evidence)):
        write_json(tmp_path / (name + ".json"), value)
    originals = {
        name: hashlib.sha256((tmp_path / (name + ".json")).read_bytes()).hexdigest()
        for name in ("manifest", "evidence", "authority")
    }
    copied = evidence.model_copy(update={"scenarios": evidence.scenarios[1:]})
    write_json(tmp_path / "tampered.json", copied)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.selftest.mcp_fault_verify",
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--authority",
            str(tmp_path / "authority.json"),
            "--evidence",
            str(tmp_path / "tampered.json"),
            "--output",
            str(tmp_path / "report"),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        check=False,
        capture_output=True,
    )
    assert result.returncode != 0
    report = read_json(tmp_path / "report/verification.json")
    assert any(
        f["code"] == "FAULT_REQUIRED_SCENARIO_MISSING"
        for row in report["scenarios"]
        for f in row["findings"]
    )
    assert originals == {
        name: hashlib.sha256((tmp_path / (name + ".json")).read_bytes()).hexdigest()
        for name in originals
    }


def test_independent_oracle_does_not_import_candidate_application_modules():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import scripts.selftest.mcp_fault_verify; "
            "assert not any(k == 'app' or k.startswith('app.') for k in sys.modules)",
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0


def test_business_rejection_is_raw_junit_failure_when_sdk_iserror_false(tmp_path):
    manifest, evidence, authority = unit_evidence()
    report = verify(manifest, evidence, authority)
    assert report.exit_code == 0
    inactive = [row for row in evidence.scenarios if "inactive_account_creator" in row.scenario_id]
    assert len(inactive) == 2
    assert all(
        row.result.complete
        and row.result.tool_error is False
        and row.result.business_code == "MCP_AUTHENTICATION_REQUIRED"
        for row in inactive
    )
    write_reports(report, evidence, tmp_path)
    root = parse(tmp_path / "execution.junit.xml").getroot()
    for row in inactive:
        assert root.find(f"./testcase[@name='{row.scenario_id}']/failure") is not None


def test_inactive_business_rejection_requires_its_actual_error_trace():
    manifest, evidence, authority = unit_evidence()
    index = next(
        i
        for i, row in enumerate(evidence.scenarios)
        if "inactive_account_creator" in row.scenario_id
    )
    row = evidence.scenarios[index]
    changed = row.model_copy(
        update={"result": row.result.model_copy(update={"trace_present": False})}
    )
    evidence = evidence.model_copy(
        update={
            "scenarios": (*evidence.scenarios[:index], changed, *evidence.scenarios[index + 1 :])
        }
    )
    report = verify(manifest, evidence, authority)
    assert report.exit_code == 1 and "FAULT_REQUIRED_ERROR_TRACE_MISSING" in codes(report)
