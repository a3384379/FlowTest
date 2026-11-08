"""Frozen governance expectations remain independent of captured SDK/REST outcomes."""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
from xml.etree.ElementTree import parse

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.mcp_governance_contracts import Evidence, Manifest
from scripts.selftest.mcp_governance_runner import run_local
from scripts.selftest.mcp_governance_verify import Report, verify, write_reports

FIXTURE = Path(__file__).parent / "fixtures/mcp_governance_actual_final"
PACK = Path(__file__).resolve().parents[2] / "selftest/packs/mcp-governance-negative-v1/pack.json"


@pytest.fixture
def original() -> tuple[Manifest, Evidence]:
    return (
        Manifest.model_validate(read_json(FIXTURE / "manifest.json")),
        Evidence.model_validate(read_json(FIXTURE / "evidence.json")),
    )


def checked(manifest: Manifest, evidence: Evidence) -> Report:
    return verify(manifest, evidence, PACK, now=manifest.created_at)


def codes(report: Report) -> set[str]:
    return {finding.code for finding in report.findings} | {
        finding.code for row in report.scenarios for finding in row.findings
    }


@pytest.mark.parametrize("mutation", ["nonce", "expiry", "cleanup"])
def test_global_governance_failure_is_a_failed_junit_case(
    original: tuple[Manifest, Evidence], tmp_path: Path, mutation: str
) -> None:
    manifest, evidence = original
    changed = evidence
    now = manifest.created_at
    if mutation == "nonce":
        changed = evidence.model_copy(update={"nonce": "different-nonce"})
    elif mutation == "expiry":
        now = manifest.expires_at + timedelta(seconds=1)
    else:
        changed = evidence.model_copy(update={"process_cleanup_complete": False})
    report = verify(manifest, changed, PACK, now=now)
    assert report.exit_code != 0 and report.findings
    assert all(row.verification_status == "matched" for row in report.scenarios)
    write_reports(report, changed, tmp_path)
    root = parse(tmp_path / "verification.junit.xml").getroot()
    assert int(root.attrib["tests"]) == len(report.scenarios) + 1
    assert root.find("./testcase[@name='batch-global']/failure") is not None


def test_actual_sdk_42_frozen_negative_governance_preserves_raw_failures(
    original: tuple[Manifest, Evidence], tmp_path: Path
) -> None:
    manifest, evidence = original
    report = checked(manifest, evidence)
    assert report.exit_code == 0 and len(report.scenarios) == 42
    assert evidence.tools_admitted == 22 and evidence.http_admitted <= 500
    assert (
        evidence.scenarios[-1].after.proposals,
        evidence.scenarios[-1].after.designs,
        evidence.scenarios[-1].after.approvals,
    ) == (6, 2, 2)
    write_reports(report, evidence, tmp_path)
    assert "failure" in (tmp_path / "execution.junit.xml").read_text()
    assert "failure" not in (tmp_path / "verification.junit.xml").read_text()


def test_cannot_reuse_same_wire_receipt_for_persist_and_idempotent_replay(
    original: tuple[Manifest, Evidence],
) -> None:
    manifest, evidence = original
    rows = list(evidence.scenarios)
    persist, replay = rows[2], rows[3]
    rows[3] = replay.model_copy(
        update={
            "wire_request": persist.wire_request,
            "wire_response": persist.wire_response,
            "result": persist.result,
            "started_at": persist.started_at,
            "completed_at": persist.completed_at,
        }
    )
    result = checked(manifest, evidence.model_copy(update={"scenarios": tuple(rows)}))
    assert result.exit_code == 1 and "GOVERNANCE_RPC_RECEIPT_REUSED" in codes(result)


def test_collection_cannot_precede_actual_completed_receipts(
    original: tuple[Manifest, Evidence],
) -> None:
    manifest, evidence = original
    result = checked(manifest, evidence.model_copy(update={"collected_at": manifest.created_at}))
    assert result.exit_code == 1 and "GOVERNANCE_COLLECTION_TIME_MISMATCH" in codes(result)


def test_idempotent_proposal_cannot_change_proposed_document_digest(
    original: tuple[Manifest, Evidence],
) -> None:
    manifest, evidence = original
    data = evidence.model_dump(mode="json")
    data["scenarios"][3]["state"]["proposed_document_digest"] = "0" * 64
    result = checked(manifest, Evidence.model_validate(data))
    assert result.exit_code == 1 and "GOVERNANCE_REPLAY_OR_SOURCE_CHANGED" in codes(result)


def _batch_mutation(data: dict, mutation: str) -> None:
    rows = data["scenarios"]
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(rows[0].copy())
    elif mutation == "nonce":
        data["nonce"] = "different-batch"
    elif mutation == "cleanup":
        data["process_cleanup_complete"] = False
    elif mutation == "budget":
        data["http_rejected"] = 1


def _wire_mutation(data: dict, mutation: str) -> None:
    rows = data["scenarios"]
    if mutation == "wire":
        rows[0]["wire_response"] = None
    elif mutation == "counter":
        rows[0]["after"]["executions"] = 1
    elif mutation == "raw":
        rows[0]["result"]["business_code"] = None
    elif mutation == "trace":
        rows[0]["result"]["trace_present"] = False
    elif mutation == "request":
        rows[0]["wire_request"]["arguments_digest"] = "0" * 64


def _state_mutation(data: dict, mutation: str, manifest: Manifest) -> None:
    rows = data["scenarios"]
    if mutation == "reviewer":
        rows[13]["state"]["reviewed_by_id"] = str(manifest.fixture.owner_user_id)
    elif mutation == "saved":
        rows[13]["state"]["materialized"]["source_change_set_id"] = str(uuid4())
    elif mutation == "oracle":
        rows[2]["state"]["oracles"][0]["expected_digest"] = "0" * 64
    elif mutation == "source":
        rows[3]["state"]["source_fingerprint"] = "0" * 64


@pytest.mark.parametrize(
    ("mutation", "code", "exit_code"),
    [
        ("missing", "GOVERNANCE_REQUIRED_SCENARIO_MISSING", 2),
        ("duplicate", "GOVERNANCE_SCENARIO_SET_MISMATCH", 1),
        ("nonce", "GOVERNANCE_BATCH_IDENTITY_MISMATCH", 1),
        ("cleanup", "GOVERNANCE_PROCESS_CLEANUP_INCOMPLETE", 2),
        ("budget", "GOVERNANCE_ADMISSION_OR_ATTEMPT_MISMATCH", 1),
        ("wire", "GOVERNANCE_WIRE_RECEIPT_MISSING", 2),
        ("counter", "GOVERNANCE_ASSET_SIDE_EFFECT_MISMATCH", 1),
        ("raw", "GOVERNANCE_RAW_RESULT_MISMATCH", 1),
        ("trace", "GOVERNANCE_TRACE_MISSING", 2),
        ("request", "GOVERNANCE_REQUEST_BINDING_MISMATCH", 1),
        ("reviewer", "GOVERNANCE_REVIEWER_MISMATCH", 1),
        ("saved", "GOVERNANCE_SAVED_ASSET_BINDING_MISMATCH", 1),
        ("oracle", "GOVERNANCE_ORACLE_MISMATCH", 1),
        ("source", "GOVERNANCE_REPLAY_OR_SOURCE_CHANGED", 1),
    ],
)
def test_false_green_mutations_reject_with_precise_finding(
    original: tuple[Manifest, Evidence], mutation: str, code: str, exit_code: int
) -> None:
    manifest, evidence = original
    data = evidence.model_dump(mode="json")
    _batch_mutation(data, mutation)
    _wire_mutation(data, mutation)
    _state_mutation(data, mutation, manifest)
    result = checked(manifest, Evidence.model_validate(data))
    assert result.exit_code == exit_code and code in codes(result)


@pytest.mark.parametrize("field", ["business_code", "trace_present", "proposal_id", "status"])
def test_optional_projection_omissions_do_not_become_positive_observations(
    original: tuple[Manifest, Evidence], field: str
) -> None:
    manifest, evidence = original
    data = evidence.model_dump(mode="json")
    del data["scenarios"][1]["result"][field]
    result = checked(manifest, Evidence.model_validate(data))
    assert result.exit_code == 2 and "GOVERNANCE_RAW_RESULT_FIELD_MISSING" in codes(result)


@pytest.mark.parametrize("mutation", ["missing", "boolean", "negative"])
def test_all_ten_actual_asset_counters_are_strict_required_observations(
    original: tuple[Manifest, Evidence], mutation: str
) -> None:
    _, evidence = original
    data = evidence.model_dump(mode="json")
    counts = data["scenarios"][0]["before"]
    if mutation == "missing":
        del counts["designs"]
    else:
        counts["designs"] = False if mutation == "boolean" else -1
    with pytest.raises(ValidationError):
        Evidence.model_validate(data)


def test_expiry_is_independent_of_expected_raw_failure(original: tuple[Manifest, Evidence]) -> None:
    manifest, evidence = original
    result = verify(manifest, evidence, PACK, now=manifest.expires_at + timedelta(seconds=1))
    assert result.exit_code == 2 and "GOVERNANCE_BATCH_EXPIRED" in codes(result)


def test_contract_invalid_cli_emits_safe_json_and_both_junits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts.selftest.mcp_governance_verify import main

    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text('{"unrecognized":"synthetic-secret-never-echo"}')
    output = tmp_path / "reports"
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify", "--manifest", str(unsafe), "--evidence", str(unsafe), "--output", str(output)],
    )
    assert main() == 2
    assert all(
        (output / name).is_file()
        for name in ("verification.json", "verification.junit.xml", "execution.junit.xml")
    )
    assert "synthetic-secret-never-echo" not in "".join(p.read_text() for p in output.iterdir())


def test_fixture_failure_is_nonzero_reports_and_preserves_owned_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts.selftest import mcp_governance_runner

    async def rejected(*args: object) -> None:
        raise HarnessError("synthetic-secret-never-echo")

    monkeypatch.setattr(mcp_governance_runner, "run_owned", rejected)
    output = tmp_path / "owned"
    assert asyncio.run(run_local(output, Path("python"), Path("backend"), PACK)) == 2
    report = read_json(output / "public/verification.json")
    assert report["exit_code"] == 2 and "synthetic-secret-never-echo" not in str(report)
    write_json(output / "receipt.json", {"owned": True})
    with pytest.raises(FileExistsError):
        asyncio.run(run_local(output, Path("python"), Path("backend"), PACK))
    assert read_json(output / "receipt.json") == {"owned": True}
