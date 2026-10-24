"""Boundary entrypoints preserve no-replay and observer credential isolation."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_selftest_mcp_probe_setup import binding

sys.path.insert(0, str(Path(__file__).parents[2]))
from scripts.selftest import run_boundaries
from scripts.selftest.io import HarnessError, write_json


@pytest.mark.asyncio
@pytest.mark.parametrize("pack", ["security", "initialization", "auth-expiry"])
async def test_existing_output_is_rejected_before_reading_credentials_or_stack(
    pack, tmp_path, monkeypatch
):
    def forbidden(*args):
        raise AssertionError("不能读取凭据或操作目标")

    monkeypatch.setattr(run_boundaries, "read_json", forbidden)
    with pytest.raises(HarnessError, match="OUTPUT_EXISTS_NO_REPLAY"):
        await run_boundaries.execute(pack, tmp_path / "unknown", tmp_path)


def test_observer_does_not_inherit_tokens_and_cannot_reuse_old_green(tmp_path, monkeypatch):
    write_json(tmp_path / "result.json", {"manifest": {"source": "synthetic"}})
    write_json(tmp_path / "independent-o/verification.json", {"exit_code": 0})
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-o")
    monkeypatch.setenv("FLOWTEST_SELFTEST_OBSERVER_TOKEN", "must-not-reach-o")

    def child(command, **kwargs):
        assert command[:3] == [sys.executable, "-m", "scripts.selftest.boundary_verify"]
        assert set(kwargs["env"]) == {"PATH", "PYTHONPATH", "PYTHONUNBUFFERED"}
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_boundaries.subprocess, "run", child)
    report = run_boundaries.observe("security", tmp_path)
    assert report.exit_code == 2
    assert report.reason_codes == ("BOUNDARY_OBSERVER_PROCESS_UNAVAILABLE",)
    assert len(report.scenario_ids) == 5


def test_finalizer_rejects_changed_stack_before_disposal_or_old_result(tmp_path, monkeypatch):
    frozen = binding()
    directory, output = tmp_path / "owned", tmp_path / "round"
    write_json(directory / "stack.json", frozen)
    write_json(
        output / "frozen-stack.json", {"binding": frozen.model_dump(mode="json"), "verifier": "old"}
    )
    monkeypatch.setattr(run_boundaries, "_verifier_digest", lambda _: "current")
    with pytest.raises(HarnessError, match="STACK_OR_VERIFIER_CHANGED"):
        run_boundaries.finalize("security", directory, output)
    assert not (output / "evidence.pre-disposal.json").exists()
