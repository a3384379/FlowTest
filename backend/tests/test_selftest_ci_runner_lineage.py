"""CI ordering preserves the frozen disposable runner, without Docker or model calls."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_selftest_verification import (
    COLLECTED,
    DEADLINE,
    EXECUTED,
    START,
    evidence_payload,
    manifest_payload,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import selftest_ci as driver  # noqa: E402
from scripts.selftest import ci_probes, engine_additional  # noqa: E402
from scripts.selftest.contracts import BatchEvidence, BatchManifest  # noqa: E402
from scripts.selftest.fixed_baseline import FixedResult  # noqa: E402
from scripts.selftest.io import write_json  # noqa: E402
from scripts.selftest.local_stack import StackBinding  # noqa: E402
from scripts.selftest.mcp_probe_setup import _retained_binding  # noqa: E402
from scripts.selftest.verify import verify_batch  # noqa: E402


def binding() -> StackBinding:
    return StackBinding(
        project_name="flowtest-selftest-" + "1" * 12,
        nonce="2" * 32,
        runner_url="http://runner.test",
        target_url="http://target.test",
        observer_url="http://observer.test",
        private_subnet="172.18.0.0/24",
        candidate_image="candidate",
        candidate_image_digest="sha256:" + "a" * 64,
        fixture_image="fixture",
        fixture_image_digest="sha256:" + "b" * 64,
        source_digest="c" * 64,
        dependency_digest="d" * 64,
        runner_container_id="e" * 64,
        target_container_id="f" * 64,
        observer_container_id="1" * 64,
        runner_volume="owned-runner",
        target_volume="owned-target",
    )


def frozen_result(current: StackBinding) -> FixedResult:
    now = datetime.now(UTC)
    manifest, evidence = manifest_payload(), evidence_payload()
    manifest["builds"]["target"] = current.candidate_image_digest
    evidence["builds"]["target"] = current.candidate_image_digest
    manifest["scenarios"][0]["expected"]["required_disposal"] = {
        "project_name": current.project_name,
        "target_container_id": current.runner_container_id,
        "target_volume": current.runner_volume,
        "target_image": current.candidate_image_digest,
        "binding_nonce": current.nonce,
    }
    raw = json.dumps([manifest, evidence])
    for original, actual in (
        (START, now - timedelta(seconds=5)),
        (EXECUTED, now - timedelta(seconds=3)),
        (COLLECTED, now - timedelta(seconds=1)),
        (DEADLINE, now + timedelta(seconds=600)),
    ):
        raw = raw.replace(original, actual.isoformat())
    manifest, evidence = json.loads(raw)
    frozen = BatchManifest.model_validate(manifest)
    observed = BatchEvidence.model_validate(evidence)
    return FixedResult(
        manifest=frozen,
        evidence=observed,
        report=verify_batch(frozen, observed),
        installation=None,
    )


def test_ci_configures_probes_before_freezing_native_disposable_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = driver.RunPaths.create(tmp_path / "ci")
    paths.stack.mkdir()
    current = binding()
    frozen: list[FixedResult] = []
    order: list[str] = []

    def command(arguments: list[str], *, log: Path, timeout: int) -> int:
        if "--suite" in arguments:
            suite = arguments[arguments.index("--suite") + 1]
            order.append(suite)
            if suite == "engine-additional":
                frozen.append(frozen_result(current))
        return 0

    def probes(selected: driver.RunPaths, stages: list[driver.StageResult]) -> int:
        nonlocal current
        assert selected == paths
        for index, pack in enumerate(("protocol34", "governance42"), start=3):
            updated = current.model_copy(update={"runner_container_id": str(index) * 64})
            _retained_binding(current, updated)
            current = updated
            order.append(pack)
        return 0

    monkeypatch.setattr(driver, "command", command)
    monkeypatch.setattr(ci_probes, "run_probe_stages", probes)
    removed: list[str] = []
    monkeypatch.setattr(engine_additional, "_verify_removed", removed.append)
    arguments = argparse.Namespace(runtime_image="synthetic-runtime", candidate=tmp_path)
    assert driver.run_stages(arguments, paths, []) == 0
    assert len(frozen) == 1
    write_json(paths.stack / "stack.json", current)
    write_json(
        paths.stack / "ownership.json",
        {"project_name": current.project_name, "nonce": current.nonce},
    )
    write_json(
        paths.stack / "cleanup.json", {"project_name": current.project_name, "status": "completed"}
    )
    output = paths.reports / "engine-additional/round-1"
    sealed = engine_additional.finalize_engine_additional_cleanup(
        frozen[0], binding=current, stack_directory=paths.stack, output_dir=output
    )
    assert sealed.report.exit_code == 0
    assert removed == [current.project_name]
    assert order.index("mcp-core") < order.index("protocol34")
    assert order.index("governance42") < order.index("engine-additional")
    assert order.index("engine-additional") < order.index("native-api")
    receipt = sealed.evidence.scenarios[0].target_disposal
    assert receipt is not None
    assert receipt.target_container_id == current.runner_container_id
