"""Frozen actual facts are not current deployment evidence; tampering must stay red."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.worker_fault_contracts import WorkerEvidence, WorkerManifest
from scripts.selftest.worker_fault_verify import verify

FIXTURE = Path(__file__).parent / "fixtures/worker_fault_actual"


def bundle():
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    evidence = json.loads((FIXTURE / "evidence.json").read_text())
    return manifest, evidence


def test_actual_worker_faults_keep_two_native_failures_and_four_independent_matches():
    manifest, evidence = bundle()
    before = canonical_digest(evidence)
    report = verify(
        WorkerManifest.model_validate(manifest), WorkerEvidence.model_validate(evidence)
    )
    assert report.exit_code == 0
    assert [row.native_status for row in report.scenarios] == [
        "passed",
        "passed",
        "failed",
        "failed",
    ]
    assert all(not row.reason_codes for row in report.scenarios)
    assert len(report.scenario_ids) == 4
    assert canonical_digest(evidence) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "order",
        "native_pass",
        "wrong_code",
        "extra_attempt",
        "extra_request",
        "foreign_case",
        "missing_kill",
        "same_actor",
        "foreign_worker",
        "wrong_kill_stage",
        "budget_count",
        "no_disposal",
        "foreign_disposal",
        "resources_present",
        "changed_manifest",
    ],
)
def test_independent_worker_o_rejects_changed_facts_without_rewriting_raw_fixture(mutation):
    manifest, original = bundle()
    evidence = copy.deepcopy(original)
    rows = evidence["observations"]
    assert (
        _change_native(mutation, rows)
        or _change_fault(mutation, rows)
        or _change_final(mutation, manifest, evidence)
    )
    report = verify(
        WorkerManifest.model_validate(manifest), WorkerEvidence.model_validate(evidence)
    )
    assert report.exit_code == 2
    assert report.reason_codes or any(row.reason_codes for row in report.scenarios)
    assert len(report.scenarios) == 4
    assert json.loads((FIXTURE / "evidence.json").read_text()) == original


def _change_native(mutation, rows) -> bool:
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[1] = copy.deepcopy(rows[0])
    elif mutation == "order":
        rows.reverse()
    elif mutation == "native_pass":
        rows[2]["native"]["run"]["status"] = "passed"
    elif mutation == "wrong_code":
        rows[2]["native_error_codes"] = ["NODE_TIMEOUT"]
    elif mutation == "extra_attempt":
        rows[0]["native"]["execution_ids"] *= 2
    elif mutation == "extra_request":
        rows[0]["journal"]["entries"].append(copy.deepcopy(rows[0]["journal"]["entries"][0]))
    elif mutation == "foreign_case":
        rows[0]["source_case_id"] = "00000000-0000-4000-8000-000000000001"
    else:
        return False
    return True


def _change_fault(mutation, rows) -> bool:
    if mutation == "missing_kill":
        rows[2]["fault"]["killed_signal"] = None
    elif mutation == "same_actor":
        rows[0]["fault"]["actor_processes"][1] = copy.deepcopy(
            rows[0]["fault"]["actor_processes"][0]
        )
    elif mutation == "foreign_worker":
        rows[2]["fault"]["container_id"] = "0" * 64
    elif mutation == "wrong_kill_stage":
        rows[3]["pre_kill_journal"]["metrics"]["active_count"] = 0
    elif mutation == "budget_count":
        rows[3]["journal"]["budget"]["admitted_count"] = 99
    else:
        return False
    return True


def _change_final(mutation, manifest, evidence) -> bool:
    if mutation == "no_disposal":
        evidence["disposal"] = None
    elif mutation == "foreign_disposal":
        evidence["disposal"]["binding_nonce"] = "wrong-owned-namespace"
    elif mutation == "resources_present":
        evidence["disposal"]["containers_absent"] = False
    elif mutation == "changed_manifest":
        manifest["source_digest"] = "0" * 64
    else:
        return False
    return True
