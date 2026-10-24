"""Disposal receipt unit checks; Docker inventory is explicitly substituted."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from test_selftest_harness import binding_fixture
from test_selftest_verification import (
    API,
    COLLECTED,
    EXECUTED,
    PROJECT,
    evidence_payload,
    manifest_payload,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest import native_api_pack  # noqa: E402
from scripts.selftest.contracts import BatchEvidence, BatchManifest  # noqa: E402
from scripts.selftest.io import HarnessError, write_json  # noqa: E402
from scripts.selftest.native_api_pack import (  # noqa: E402
    NativeAPIResult,
    finalize_disposable_cleanup,
)
from scripts.selftest.verify import verify_batch  # noqa: E402


def pending_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    binding, _ = binding_fixture(tmp_path, monkeypatch)
    binding = binding.model_copy(update={"candidate_image_digest": "target-1"})
    write_json(tmp_path / "stack.json", binding)
    write_json(
        tmp_path / "cleanup.json", {"project_name": binding.project_name, "status": "completed"}
    )
    target = {
        "project_name": binding.project_name,
        "target_container_id": binding.target_container_id,
        "target_volume": binding.target_volume,
        "target_image": binding.candidate_image_digest,
    }
    expected = {
        "organization_id": PROJECT,
        "created_by_id": API,
        "name": "batch-1-project-updated",
        "disposal_binding_nonce": binding.nonce,
        "disposable_target": target,
    }
    manifest_value = manifest_payload()
    manifest_value["scenarios"][0]["expected"]["project_state"] = expected
    evidence_value = evidence_payload()
    evidence_value["scenarios"][0]["project_state"] = {
        **expected,
        "project_id": str(uuid4()),
        "created_at": EXECUTED,
        "observed_at": COLLECTED,
        "disposal_status": "pending",
    }
    manifest = BatchManifest.model_validate(manifest_value)
    evidence = BatchEvidence.model_validate(evidence_value)
    monkeypatch.setattr(
        native_api_pack,
        "verify_batch",
        lambda expected, actual: verify_batch(
            expected, actual, now=datetime.fromisoformat(COLLECTED)
        ),
    )
    return binding, NativeAPIResult(manifest, evidence, verify_batch(manifest, evidence), ())


def test_native_disposal_is_idempotent_and_preserves_pending_evidence_and_raw_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding, original = pending_result(tmp_path, monkeypatch)
    reads: list[str] = []
    monkeypatch.setattr(native_api_pack, "_verify_removed", reads.append)
    output = tmp_path / "evidence"
    sealed = finalize_disposable_cleanup(
        original, binding=binding, stack_directory=tmp_path, output_dir=output
    )
    before = (output / "evidence.pre-disposal.json").read_bytes()
    repeated = finalize_disposable_cleanup(
        sealed, binding=binding, stack_directory=tmp_path, output_dir=output
    )
    assert reads == [binding.project_name, binding.project_name]
    assert repeated.evidence == sealed.evidence
    assert repeated.evidence.scenarios[0].execution.status == "failed"
    assert repeated.evidence.scenarios[0].attempts == original.evidence.scenarios[0].attempts
    assert (output / "evidence.pre-disposal.json").read_bytes() == before
    prior = json.loads(before)
    assert prior["scenarios"][0]["project_state"]["disposal_status"] == "pending"
    receipt = sealed.evidence.scenarios[0].project_state.disposal_receipt
    assert receipt.target_volume == binding.target_volume
    assert receipt.containers_absent and receipt.volumes_absent and receipt.networks_absent


@pytest.mark.parametrize("tamper", ["cleanup", "ownership", "binding", "target_identity"])
def test_native_disposal_rejects_foreign_receipt_before_recording_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    binding, original = pending_result(tmp_path, monkeypatch)
    reads: list[str] = []
    monkeypatch.setattr(native_api_pack, "_verify_removed", reads.append)
    if tamper == "cleanup":
        write_json(tmp_path / "cleanup.json", {"project_name": "foreign", "status": "completed"})
    elif tamper == "ownership":
        write_json(
            tmp_path / "ownership.json", {"project_name": binding.project_name, "nonce": "old"}
        )
    elif tamper == "binding":
        write_json(tmp_path / "stack.json", binding.model_copy(update={"target_volume": "foreign"}))
    else:
        observation = original.evidence.scenarios[0]
        changed = observation.project_state.model_copy(update={"disposal_binding_nonce": "old"})
        evidence = original.evidence.model_copy(
            update={"scenarios": (observation.model_copy(update={"project_state": changed}),)}
        )
        original = NativeAPIResult(original.manifest, evidence, original.report, ())
    with pytest.raises(HarnessError, match=r"DISPOSAL_.*_MISMATCH"):
        finalize_disposable_cleanup(
            original, binding=binding, stack_directory=tmp_path, output_dir=tmp_path / "evidence"
        )
    assert not (tmp_path / "evidence/evidence.json").exists()
    assert reads == ([binding.project_name] if tamper == "target_identity" else [])
