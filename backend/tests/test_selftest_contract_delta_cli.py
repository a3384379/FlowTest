"""Public project isolation and exact owned-disposal gates; no Docker acceptance."""

import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from test_selftest_native_api_security import world as world

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest import run_contract_delta as entry  # noqa: E402
from scripts.selftest.bootstrap import Installation  # noqa: E402
from scripts.selftest.contract_delta_budget import DeltaAPI, DeltaBudget  # noqa: E402
from scripts.selftest.contract_delta_contracts import DeltaEvidence, DeltaManifest  # noqa: E402
from scripts.selftest.contract_delta_verify import load_pack, write_reports  # noqa: E402
from scripts.selftest.contract_delta_verify import verify as actual_verify  # noqa: E402
from scripts.selftest.contracts import RequiredDisposal, canonical_digest  # noqa: E402
from scripts.selftest.io import HarnessError, PublicAPI, read_json, write_json  # noqa: E402
from scripts.selftest.local_stack import StackBinding  # noqa: E402

from app.main import app  # noqa: E402


def test_delta_finalizer_rejects_verifier_drift_without_mutating_evidence(tmp_path, monkeypatch):
    directory, output, _, calls = disposal_state(tmp_path, monkeypatch)
    original = (output / "evidence.json").read_bytes()
    monkeypatch.setattr(entry, "_verifier_digest", lambda _profile: "0" * 64)
    with pytest.raises(HarnessError, match="DELTA_VERIFIER_SOURCE_CHANGED"):
        entry.finalize(directory, output)
    assert (output / "evidence.json").read_bytes() == original
    assert calls == []


def binding():
    return StackBinding(
        project_name="flowtest-selftest-123456789abc",
        nonce="a" * 32,
        runner_url="http://127.0.0.1:43001",
        target_url="http://127.0.0.1:43002",
        observer_url="http://127.0.0.1:43003",
        private_subnet="172.27.9.0/24",
        candidate_image="candidate",
        candidate_image_digest="sha256:" + "4" * 64,
        fixture_image="fixture",
        fixture_image_digest="sha256:" + "5" * 64,
        source_digest="source",
        dependency_digest="dependencies",
        runner_container_id="6" * 64,
        target_container_id="7" * 64,
        observer_container_id="8" * 64,
        runner_volume="owned_runner",
        target_volume="owned_target",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["full", "compact"])
async def test_delta_cli_freezes_actual_profile_verifier_before_dispatch(
    tmp_path, monkeypatch, profile
):
    stack = binding().model_copy(update={"runtime_profile": profile})
    frozen = DeltaManifest.model_validate(
        read_json(ROOT / "backend/tests/fixtures/contract_delta_actual/manifest.json")
    )
    credentials = SimpleNamespace(
        admin_token="admin",
        reviewer_token="reviewer",
        capture_viewer_token="viewer",
        mcp_token="machine",
    )

    async def bootstrap(*args):
        return SimpleNamespace(installation=frozen.installation, credentials=credentials)

    async def project(*args):
        return frozen.installation, "reader"

    class API:
        def __init__(self, *args, **kwargs):
            pass

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
    monkeypatch.setattr(
        entry, "private_environment", lambda _: {"FLOWTEST_SELFTEST_OBSERVER_TOKEN": "observer"}
    )
    with pytest.raises(HarnessError, match="TEST_PROTOCOL_BOUNDARY"):
        await entry.run(owned, tmp_path / "delta")
    selected = DeltaManifest.model_validate(
        read_json(tmp_path / "delta/selection-before-protocol.json")
    )
    assert selected.builds.verifier == entry._verifier_digest(profile)


@pytest.mark.asyncio
async def test_cli_prepares_fresh_public_project_and_project_scoped_read_token(world, tmp_path):
    owner = world.owner["Authorization"].removeprefix("Bearer ")
    viewer = world.viewer["Authorization"].removeprefix("Bearer ")
    actor = UUID(jwt.decode(owner, options={"verify_signature": False})["sub"])
    viewer_id = UUID(jwt.decode(viewer, options={"verify_signature": False})["sub"])
    original = Installation(
        binding_nonce="a" * 32,
        organization_id=world.organization,
        project_id=world.project,
        reviewer_id=actor,
        reviewer_email="fixture@example.com",
        mcp_account_id=uuid4(),
        target_project_id=uuid4(),
        target_user_id=uuid4(),
        target_email="target@example.com",
        fixture_environment_id=uuid4(),
        target_environment_id=uuid4(),
        fixture_service_id=uuid4(),
        target_service_id=uuid4(),
        capture_viewer_id=viewer_id,
    )
    api = PublicAPI(
        "http://test", owner, world.organization, transport=httpx.ASGITransport(app=app)
    )
    budget = DeltaBudget(tmp_path, datetime.now(UTC) + timedelta(seconds=600))
    try:
        installed, token = await entry._project_installation(
            DeltaAPI(api, budget), original, binding(), tmp_path
        )
        assert installed.project_id != original.project_id
        safe = PublicAPI("http://test", token, transport=httpx.ASGITransport(app=app))
        view = PublicAPI(
            "http://test", viewer, world.organization, transport=httpx.ASGITransport(app=app)
        )
        try:
            denied = await safe.request(
                "GET",
                f"/ci/projects/{original.project_id}/workflow-executions/{uuid4()}/evidence",
                allow_status=(401,),
            )
            assert denied["error"]["code"] == "INVALID_SERVICE_TOKEN"
            own = await safe.request(
                "GET",
                f"/ci/projects/{installed.project_id}/workflow-executions/{uuid4()}/evidence",
                allow_status=(404,),
            )
            assert own["error"]["code"]
            await view.object("GET", f"/projects/{installed.project_id}")
            denied_write = await view.request(
                "POST",
                f"/projects/{installed.project_id}/environments",
                {"name": "forbidden", "base_url": "https://example.com"},
                allow_status=(403,),
            )
            assert denied_write["error"]["code"]
        finally:
            await safe.close()
            await view.close()
        assert token not in (tmp_path / "installation.json").read_text()
        assert budget.requests > 10
    finally:
        await api.close()


def disposal_state(tmp_path, monkeypatch):
    source = ROOT / "backend/tests/fixtures/contract_delta_actual"
    frozen = DeltaManifest.model_validate(read_json(source / "manifest.json"))
    observed = DeltaEvidence.model_validate(read_json(source / "evidence.json"))
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
    evidence = observed.model_copy(
        update={"manifest_digest": canonical_digest(frozen.model_dump(mode="json"))}
    )
    directory, output = tmp_path / "owned", tmp_path / "result"
    write_json(directory / "stack.json", stack)
    write_json(
        directory / "ownership.json", {"nonce": stack.nonce, "project_name": stack.project_name}
    )
    write_json(
        directory / "cleanup.json", {"status": "completed", "project_name": stack.project_name}
    )
    write_json(output / "manifest.json", frozen)
    write_json(output / "evidence.json", evidence)
    calls = []
    # This unit fixture retains its original frozen H identity and wall clock.
    monkeypatch.setattr(entry, "_verifier_digest", lambda _profile: frozen.builds.verifier)
    monkeypatch.setattr(entry, "_verify_removed", lambda project: calls.append(project))

    def observe_fixture(output):
        evidence = DeltaEvidence.model_validate(read_json(output / "evidence.json"))
        report = actual_verify(
            frozen,
            load_pack(entry.pack_path()),
            evidence,
            now=evidence.disposal.removed_at if evidence.disposal else evidence.collected_at,
        )
        write_reports(report, evidence, output)
        return report.exit_code

    monkeypatch.setattr(entry, "observe", observe_fixture)

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return evidence.collected_at + timedelta(milliseconds=1)

    monkeypatch.setattr(entry, "datetime", FixedClock)
    return directory, output, stack, calls


def test_observer_child_receives_no_credentials_and_missing_report_cannot_reuse_green(
    tmp_path, monkeypatch
):
    source = ROOT / "backend/tests/fixtures/contract_delta_actual"
    write_json(tmp_path / "manifest.json", read_json(source / "manifest.json"))
    write_json(tmp_path / "evidence.json", read_json(source / "evidence.json"))
    monkeypatch.setenv("FLOWTEST_SELFTEST_OBSERVER_TOKEN", "must-not-enter-child")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-enter-child-either")

    def child(command, **kwargs):
        assert set(kwargs["env"]) == {"PATH", "PYTHONPATH", "PYTHONUNBUFFERED"}
        assert command[:3] == [sys.executable, "-m", "scripts.selftest.contract_delta_verify"]
        from types import SimpleNamespace

        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(entry.subprocess, "run", child)
    assert entry.observe(tmp_path) == 2
    report = read_json(tmp_path / "verification.json")
    assert report["verdict"] == "blocked" and len(report["scenarios"]) == 7
    assert report["findings"] == ["DELTA_OBSERVER_PROCESS_FAILED"]


def test_finalize_preserves_pre_disposal_receipt_and_checks_exact_owned_removal(
    tmp_path, monkeypatch
):
    directory, output, stack, calls = disposal_state(tmp_path, monkeypatch)
    before = (output / "evidence.json").read_bytes()
    assert entry.finalize(directory, output) == 0
    assert (output / "evidence.pre-disposal.json").read_bytes() == before
    assert calls == [stack.project_name]
    assert entry.finalize(directory, output) == 0
    assert (output / "evidence.pre-disposal.json").read_bytes() == before


@pytest.mark.parametrize("mutation", ["pending", "nonce", "project", "runner", "not_removed"])
def test_finalize_rejects_unconfirmed_foreign_drifted_or_existing_resources(
    tmp_path, monkeypatch, mutation
):
    directory, output, stack, _calls = disposal_state(tmp_path, monkeypatch)
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

        def not_removed(project):
            raise HarnessError("STILL_EXISTS")

        monkeypatch.setattr(entry, "_verify_removed", not_removed)
    with pytest.raises(HarnessError):
        entry.finalize(directory, output)
    assert not (output / "evidence.pre-disposal.json").exists()


@pytest.mark.asyncio
async def test_cli_refuses_reusing_any_output_directory_before_loading_credentials(
    tmp_path, monkeypatch
):
    def forbidden(*args):
        raise AssertionError("must not load credentials or access stack")

    monkeypatch.setattr(entry, "read_json", forbidden)
    with pytest.raises(HarnessError, match="NO_MUTATION_REPLAY"):
        await entry.run(tmp_path / "unknown", tmp_path)
