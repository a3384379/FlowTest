"""No credential enters the independent native O; exact owned disposal remains mandatory."""

import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_selftest_contract_delta_cli import binding

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest import run_native_control as entry  # noqa: E402
from scripts.selftest.contracts import RequiredDisposal, canonical_digest  # noqa: E402
from scripts.selftest.io import HarnessError, read_json, write_json  # noqa: E402
from scripts.selftest.native_control_contracts import (  # noqa: E402
    NativeControlEvidence,
    NativeControlManifest,
)
from scripts.selftest.native_control_verify import load_pack, verify, write_reports  # noqa: E402


@pytest.mark.asyncio
async def test_native_cli_freezes_profile_build_before_protocol_dispatch(tmp_path, monkeypatch):
    stack = binding().model_copy(update={"runtime_profile": "full"})
    source = ROOT / "backend/tests/fixtures/native_control_actual/manifest.json"
    frozen = NativeControlManifest.model_validate(read_json(source))
    installation = SimpleNamespace(
        organization_id=frozen.project_id,
        mcp_account_id=frozen.mcp_account_id,
        project_id=frozen.project_id,
        fixture_environment_id=frozen.environment_id,
        reviewer_id=frozen.reviewer_id,
    )
    credentials = SimpleNamespace(
        admin_token="admin",
        reviewer_token="reviewer",
        capture_viewer_token="viewer",
        mcp_token="machine",
    )

    async def bootstrap(*args):
        return SimpleNamespace(installation=installation, credentials=credentials)

    async def project(*args):
        return installation, "reader"

    class API:
        def __init__(self, *args):
            pass

        async def object(self, *args, **kwargs):
            raise HarnessError("UNSUPPORTED_SERVICE_ACCOUNT_DETAIL_ROUTE")

        async def request(self, method, path, *args, **kwargs):
            assert method == "GET" and path.endswith("/service-accounts")
            return [{"id": str(frozen.mcp_account_id), "created_by_id": str(frozen.mcp_actor_id)}]

        async def close(self):
            pass

    @asynccontextmanager
    async def protocol(*args, **kwargs):
        raise HarnessError("TEST_PROTOCOL_BOUNDARY")
        yield

    owned = tmp_path / "owned"
    write_json(owned / "stack.json", stack)
    monkeypatch.setattr(entry, "verify_binding", lambda *_: None)
    monkeypatch.setattr(entry, "bootstrap", bootstrap)
    monkeypatch.setattr(entry, "_project_installation", project)
    monkeypatch.setattr(entry, "PublicAPI", API)
    monkeypatch.setattr(entry, "_protocol", protocol)
    with pytest.raises(HarnessError, match="TEST_PROTOCOL_BOUNDARY"):
        await entry.run(owned, tmp_path / "native")
    selected = NativeControlManifest.model_validate(
        read_json(tmp_path / "native/selection-before-protocol.json")
    )
    assert selected.builds.verifier == entry._verifier_digest("full")


def disposal_state(tmp_path, monkeypatch):
    source = ROOT / "backend/tests/fixtures/native_control_actual"
    frozen = NativeControlManifest.model_validate(read_json(source / "manifest.json"))
    evidence = NativeControlEvidence.model_validate(read_json(source / "evidence.json"))
    stack = binding()
    frozen = frozen.model_copy(
        update={
            "binding_nonce": stack.nonce,
            "binding_fingerprint": canonical_digest(stack.model_dump(mode="json")),
            "required_disposal": RequiredDisposal(
                project_name=stack.project_name,
                target_container_id=stack.runner_container_id,
                target_volume=stack.runner_volume,
                target_image=stack.candidate_image_digest,
                binding_nonce=stack.nonce,
            ),
        }
    )
    evidence = evidence.model_copy(
        update={"manifest_digest": canonical_digest(frozen.model_dump(mode="json"))}
    )
    directory, output = tmp_path / "owned", tmp_path / "output"
    write_json(directory / "stack.json", stack)
    write_json(
        directory / "ownership.json", {"nonce": stack.nonce, "project_name": stack.project_name}
    )
    write_json(
        directory / "cleanup.json", {"status": "completed", "project_name": stack.project_name}
    )
    write_json(output / "manifest.json", frozen)
    write_json(output / "evidence.json", evidence)
    removed = []
    # This unit fixture retains its original frozen H identity and wall clock.
    monkeypatch.setattr(entry, "_verifier_digest", lambda _profile: frozen.builds.verifier)
    monkeypatch.setattr(entry, "_verify_removed", lambda project: removed.append(project))

    def actual_observe(path):
        observed = NativeControlEvidence.model_validate(read_json(path / "evidence.json"))
        report = verify(
            frozen, load_pack(entry.pack_path()), observed, now=observed.disposal.removed_at
        )
        write_reports(report, observed, path)
        return report.exit_code

    monkeypatch.setattr(entry, "observe", actual_observe)

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return evidence.collected_at + timedelta(milliseconds=1)

    monkeypatch.setattr(entry, "datetime", FixedClock)
    return directory, output, stack, removed


def test_native_finalizer_preserves_original_and_requires_exact_removed_owned_ids(
    tmp_path, monkeypatch
):
    directory, output, stack, removed = disposal_state(tmp_path, monkeypatch)
    before = (output / "evidence.json").read_bytes()
    assert entry.finalize(directory, output) == 0
    assert (output / "evidence.pre-disposal.json").read_bytes() == before
    assert removed == [stack.project_name]
    assert entry.finalize(directory, output) == 0
    assert (output / "evidence.pre-disposal.json").read_bytes() == before


def test_native_finalizer_rejects_verifier_drift_before_disposal_receipt(tmp_path, monkeypatch):
    directory, output, _, removed = disposal_state(tmp_path, monkeypatch)
    original = (output / "evidence.json").read_bytes()
    monkeypatch.setattr(entry, "_verifier_digest", lambda _profile: "0" * 64)
    with pytest.raises(HarnessError, match="NATIVE_CONTROL_VERIFIER_SOURCE_CHANGED"):
        entry.finalize(directory, output)
    assert (output / "evidence.json").read_bytes() == original
    assert removed == []


@pytest.mark.parametrize("mutation", ["pending", "nonce", "project", "runner", "existing"])
def test_native_finalizer_rejects_missing_foreign_or_live_resources(
    tmp_path, monkeypatch, mutation
):
    directory, output, stack, _ = disposal_state(tmp_path, monkeypatch)
    if mutation == "pending":
        write_json(
            directory / "cleanup.json", {"status": "pending", "project_name": stack.project_name}
        )
    elif mutation == "nonce":
        write_json(
            directory / "ownership.json", {"nonce": "b" * 32, "project_name": stack.project_name}
        )
    elif mutation == "project":
        write_json(directory / "cleanup.json", {"status": "completed", "project_name": "foreign"})
    elif mutation == "runner":
        write_json(
            directory / "stack.json", stack.model_copy(update={"runner_container_id": "9" * 64})
        )
    else:

        def still_exists(project):
            raise HarnessError("RESOURCES_STILL_EXIST")

        monkeypatch.setattr(entry, "_verify_removed", still_exists)
    with pytest.raises(HarnessError):
        entry.finalize(directory, output)
    assert not (output / "evidence.pre-disposal.json").exists()


def test_native_observer_cannot_reuse_old_green_and_receives_no_credentials(tmp_path, monkeypatch):
    source = ROOT / "backend/tests/fixtures/native_control_actual"
    for name in ("manifest.json", "evidence.json"):
        write_json(tmp_path / name, read_json(source / name))
    write_json(tmp_path / "verification.json", {"verdict": "passed"})
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-enter-o")
    monkeypatch.setenv("FLOWTEST_SELFTEST_OBSERVER_TOKEN", "must-not-enter-o-either")

    def child(command, **kwargs):
        assert command[:3] == [sys.executable, "-m", "scripts.selftest.native_control_verify"]
        assert set(kwargs["env"]) == {"PATH", "PYTHONPATH", "PYTHONUNBUFFERED"}
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(entry.subprocess, "run", child)
    assert entry.observe(tmp_path) == 2
    report = read_json(tmp_path / "verification.json")
    assert report["verdict"] == "blocked"
    assert len(report["scenarios"]) == 3
    assert report["findings"] == ["NATIVE_CONTROL_OBSERVER_PROCESS_FAILED"]


@pytest.mark.asyncio
async def test_existing_native_output_blocks_before_any_credentials_or_network(
    tmp_path, monkeypatch
):
    def forbidden(*args):
        raise AssertionError("must not access credentials or stack")

    monkeypatch.setattr(entry, "read_json", forbidden)
    with pytest.raises(HarnessError, match="NO_REPLAY"):
        await entry.run(tmp_path / "unknown", tmp_path)
