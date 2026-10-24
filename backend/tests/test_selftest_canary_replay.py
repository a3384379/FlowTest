"""Diagnostic replay must prove a green control and leave original artifacts byte-identical."""

import copy
import sys
from pathlib import Path

import pytest
from test_selftest_verification import COLLECTED, evidence_payload, manifest_payload

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.canary_replay import CanaryReport, _copy, _recheck_identity, load_pack, run
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, write_json
from scripts.selftest.run import _verifier_digest


def test_frozen_observer_canaries_keep_all_28_independent_mutations():
    pack = load_pack()
    assert len(pack.scenarios) == len({row.key for row in pack.scenarios}) == 28
    assert all(row.expected_reason for row in pack.scenarios)
    assert {"expiry", "junit_zero", "delete_tool_receipt", "missing_page"} <= {
        row.key for row in pack.scenarios
    }


def test_real_o_child_ignores_zero_failure_xml_and_keeps_raw_failure(tmp_path):
    manifest, evidence = manifest_payload(), evidence_payload()
    original = copy.deepcopy(evidence)
    code, reasons = _copy(tmp_path / "positive", manifest, evidence, clock=COLLECTED)
    assert code == 0 and reasons == ()
    evidence["scenarios"][0]["execution"]["error_code"] = "NODE_TIMEOUT"
    code, reasons = _copy(tmp_path / "negative", manifest, evidence, clock=COLLECTED)
    assert code == 1 and "EXECUTION_ERROR_MISMATCH" in reasons
    assert original["scenarios"][0]["execution"]["error_code"] == "WORKFLOW_ASSERTION_FAILED"
    assert 'failures="0"' in (tmp_path / "negative/execution.junit.xml").read_text()


def test_invalid_positive_control_cannot_make_all_canaries_look_successful(tmp_path):
    reports = tmp_path / "reports"
    for suite in ("mcp-core", "fixed-core"):
        source = reports / suite / "round-1"
        source.mkdir(parents=True)
        evidence = evidence_payload()
        evidence["scenarios"] = []
        write_json(source / "manifest.json", manifest_payload())
        write_json(source / "evidence.json", evidence)
    originals = {path: path.read_bytes() for path in reports.rglob("*.json")}
    with pytest.raises(HarnessError, match="CANARY_POSITIVE_CONTROL_NOT_GREEN"):
        run(reports, tmp_path / "output", "standalone")
    assert not (tmp_path / "output/verification.json").exists()
    assert all(path.read_bytes() == content for path, content in originals.items())


def test_replay_never_overwrites_an_existing_attempt(tmp_path):
    tmp_path.joinpath("output").mkdir()
    marker = tmp_path / "output/original.log"
    marker.write_text("original failure")
    with pytest.raises(FileExistsError):
        run(tmp_path / "reports", tmp_path / "output", "standalone")
    assert marker.read_text() == "original failure"


@pytest.mark.parametrize(
    "change", ["profile", "verifier", "pack", "sources", "denominator", "originals", "exit"]
)
def test_copied_zero_canary_summary_cannot_replace_the_frozen_source_identity(change):
    pack = load_pack()
    hashes = {str(index): "a" * 64 for index in range(4)}
    payload = {
        "scope": "unit_control_only",
        "pack_digest": canonical_digest(pack.model_dump(mode="json")),
        "profile": "standalone",
        "verifier_digest": _verifier_digest(),
        "source_hashes": hashes,
        "originals_unchanged": True,
        "exit_code": 0,
        "scenarios": [
            {
                "scenario_id": spec.key,
                "acceptance_variants": spec.acceptance_variants,
                "observer_exit_code": 2,
                "reason_codes": [spec.expected_reason],
                "matched": True,
            }
            for spec in pack.scenarios
        ],
    }
    report = CanaryReport.model_validate(payload)
    _recheck_identity(report, pack, "standalone", hashes)
    changes = {
        "profile": {"profile": "full"},
        "verifier": {"verifier_digest": "0" * 64},
        "pack": {"pack_digest": "0" * 64},
        "sources": {"source_hashes": {}},
        "denominator": {"scenarios": report.scenarios[:-1]},
        "originals": {"originals_unchanged": False},
        "exit": {"exit_code": 2},
    }
    with pytest.raises(HarnessError, match="CANARY_ARCHIVE_SOURCE_OR_DENOMINATOR_CHANGED"):
        _recheck_identity(report.model_copy(update=changes[change]), pack, "standalone", hashes)
