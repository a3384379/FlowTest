"""Historical real Standalone facts are a unit control, never a current deployment pass."""

import copy
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.product_boundary_contracts import (
    ProductBoundaryEvidence,
    ProductBoundaryManifest,
)
from scripts.selftest.product_boundary_verify import verify

FIXTURE = Path(__file__).parent / "fixtures/product_boundary_actual"


def inputs():
    return (
        json.loads((FIXTURE / "manifest.json").read_text()),
        json.loads((FIXTURE / "evidence.json").read_text()),
    )


def result(manifest, evidence):
    return verify(
        ProductBoundaryManifest.model_validate(manifest),
        ProductBoundaryEvidence.model_validate(evidence),
    )


def test_real_product_control_retains_two_native_failures_per_batch_and_exact_27_rows():
    manifest, evidence = inputs()
    report = result(manifest, evidence)
    assert report.exit_code == 0
    assert len(report.scenarios) == 27
    assert all(not row.reason_codes for row in report.scenarios)
    assert all(
        sum(row["execution"]["status"] == "failed" for row in native["evidence"]["scenarios"]) == 2
        for native in evidence["native"]
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "native_missing",
        "foreign_native",
        "snapshot_execution",
        "retention",
        "recursion",
        "seal",
        "cancel",
        "expiry",
        "requests",
        "disposal",
        "budget",
        "clock",
    ],
)
def test_green_summary_cannot_hide_independent_product_boundary_tampering(change):
    manifest, evidence = inputs()
    original = copy.deepcopy(evidence)
    rows = {row["key"]: row for row in evidence["observations"]}
    mutations = {
        "missing": lambda: evidence["observations"].pop(),
        "duplicate": lambda: evidence["observations"].__setitem__(-1, evidence["observations"][0]),
        "native_missing": lambda: evidence["native"].pop(),
        "foreign_native": lambda: evidence["native"][0]["manifest"].__setitem__(
            "project_id", str(uuid4())
        ),
        "snapshot_execution": lambda: rows["new_run"]["batches"][0]["execution_ids"].__setitem__(
            0, str(uuid4())
        ),
        "retention": lambda: rows["retention"]["maintenance"][1].__setitem__(
            "artifacts_deleted", 1
        ),
        "recursion": lambda: rows["recursive_target"].__setitem__("safe_fields", []),
        "seal": lambda: rows["seal_conflict"]["batches"][1].__setitem__("verdict", "failed"),
        "cancel": lambda: rows["cancel_cleanup"].__setitem__("namespace_statuses", [200] * 8),
        "expiry": lambda: rows["nonce_expiry"]["batches"][0].__setitem__("phase", "completed"),
        "requests": lambda: rows["cross_project"]["requests"][0].__setitem__("status", 200),
        "disposal": lambda: evidence["disposal"].__setitem__("volumes_absent", False),
        "budget": lambda: evidence.__setitem__("rejected_attempts", 1),
        "clock": lambda: evidence.__setitem__("collected_at", "2099-01-01T00:00:00Z"),
    }
    mutations[change]()
    report = result(manifest, evidence)
    assert report.exit_code == 2
    assert report.reason_codes or any(row.reason_codes for row in report.scenarios)
    assert inputs()[1] == original


def test_disposal_is_mandatory_even_after_all_http_and_native_checks_match():
    manifest, evidence = inputs()
    evidence["disposal"] = None
    report = result(manifest, evidence)
    assert report.exit_code == 2
    assert report.reason_codes == ("OWNED_ASSET_DISPOSAL_PENDING",)
    assert all(not row.reason_codes for row in report.scenarios)
