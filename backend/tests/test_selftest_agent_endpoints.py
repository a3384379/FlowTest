"""Role startup checks actual public endpoint identity without deployment secrets."""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from test_selftest_harness import binding_fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.selftest import agent_endpoints, local_stack
from scripts.selftest.io import HarnessError, write_json
from scripts.selftest.local_stack import BuildReceipt


def _public_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    binding, inventory = binding_fixture(tmp_path, monkeypatch)
    write_json(
        tmp_path / "build-receipt.json",
        BuildReceipt(**{name: getattr(binding, name) for name in BuildReceipt.model_fields}),
    )
    projections = {}
    for role, inspection in inventory.items():
        view = deepcopy(inspection)
        del view["Config"]["Env"]
        view["Id"] = role
        if role in {"runner", "target"}:
            view["Config"]["Cmd"] = list(agent_endpoints._command(role, "compact"))
            view["runtime_profile"] = "FLOWTEST_RUNTIME_PROFILE=standalone"
            view["fixture_run_depth"] = "FLOWTEST_SELFTEST_FIXTURE_RUN_DEPTH=" + (
                "1" if role == "target" else "0"
            )
        projections[role] = view
    commands = []

    def docker(arguments: list[str], **kwargs: object) -> str:
        commands.append(arguments)
        if arguments[0] == "ps":
            return "mock-target"
        assert arguments[-1] == agent_endpoints.PUBLIC_INSPECTION
        return json.dumps(projections[arguments[1]])

    def forbidden(*args: object) -> dict:
        pytest.fail("role attempted to load deployment secrets")

    monkeypatch.setattr(agent_endpoints, "_docker", docker)
    monkeypatch.setattr(agent_endpoints, "source_digest", lambda source: "source")
    monkeypatch.setattr(local_stack, "private_environment", forbidden)
    return binding, projections, commands


def test_agent_public_inventory_is_accepted_without_private_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding, _, commands = _public_inventory(tmp_path, monkeypatch)
    (tmp_path / "private.env").unlink()
    agent_endpoints.verify_agent_endpoints(binding, tmp_path)
    assert len(commands) == 5
    assert '"Env"' not in agent_endpoints.PUBLIC_INSPECTION
    assert "SECRET_KEY" not in agent_endpoints.PUBLIC_INSPECTION
    assert "PASSWORD" not in agent_endpoints.PUBLIC_INSPECTION
    assert "ENCRYPTION_KEY" not in agent_endpoints.PUBLIC_INSPECTION


@pytest.mark.parametrize(
    "drift", ["image", "role", "nonce", "id", "port", "network", "depth", "secret_env", "command"]
)
def test_agent_public_inventory_rejects_runtime_drift_before_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    binding, views, _ = _public_inventory(tmp_path, monkeypatch)
    target = views["target"]
    if drift == "image":
        target["Image"] = "different-image"
    elif drift == "role":
        target["Config"]["Labels"]["com.docker.compose.service"] = "runner"
    elif drift == "nonce":
        target["Config"]["Labels"]["dev.flowtest.selftest.nonce"] = "foreign"
    elif drift == "id":
        target["Id"] = "foreign-container"
    elif drift == "port":
        binding = binding.model_copy(update={"target_url": "http://127.0.0.1:29002"})
    elif drift == "network":
        target["NetworkSettings"]["Networks"]["personal-network"] = {}
    elif drift == "depth":
        target["fixture_run_depth"] = "FLOWTEST_SELFTEST_FIXTURE_RUN_DEPTH=0"
    elif drift == "secret_env":
        target["Config"]["Env"] = ["SYNTHETIC_SECRET=must-never-be-read"]
    else:
        target["Config"]["Cmd"] = ["unapproved-server"]
    with pytest.raises(HarnessError):
        agent_endpoints.verify_agent_endpoints(binding, tmp_path)


@pytest.mark.parametrize("profile", ["full", "compact"])
async def test_profile_agents_validate_endpoints_without_loading_dependency_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    import hashlib

    from test_selftest_profile_stack import _fixture

    binding, _, inventory, ids = _fixture(tmp_path, monkeypatch, profile)
    binding = binding.model_copy(
        update={
            "dependency_digest": hashlib.sha256(
                (local_stack.ROOT / "backend/uv.lock").read_bytes()
            ).hexdigest(),
        }
    )
    write_json(
        tmp_path / "ownership.json", {"project_name": binding.project_name, "nonce": binding.nonce}
    )
    write_json(
        tmp_path / "build-receipt.json",
        BuildReceipt(**{name: getattr(binding, name) for name in BuildReceipt.model_fields}),
    )
    projections = {}
    for role in ("runner", "target", "observer", "mock-target"):
        view = deepcopy(inventory[ids[role]])
        environments = dict(value.split("=", 1) for value in view["Config"].pop("Env"))
        view["runtime_profile"] = "FLOWTEST_RUNTIME_PROFILE=" + environments.get(
            "FLOWTEST_RUNTIME_PROFILE", ""
        )
        view["fixture_run_depth"] = "FLOWTEST_SELFTEST_FIXTURE_RUN_DEPTH=" + environments.get(
            "FLOWTEST_SELFTEST_FIXTURE_RUN_DEPTH", ""
        )
        projections[ids[role]] = view

    def docker(arguments: list[str], **kwargs: object) -> str:
        return ids["mock-target"] if arguments[0] == "ps" else json.dumps(projections[arguments[1]])

    def forbidden(*args: object) -> dict:
        pytest.fail("profile agent attempted to read dependency secrets")

    monkeypatch.setattr(agent_endpoints, "_docker", docker)
    monkeypatch.setattr(agent_endpoints, "source_digest", lambda source: "source")
    monkeypatch.setattr(local_stack, "private_environment", forbidden)
    agent_endpoints.verify_agent_endpoints(binding, tmp_path)
    projections[ids["runner"]]["Mounts"] = [
        {"Type": "bind", "Source": "/private", "Destination": "/data"}
    ]
    with pytest.raises(HarnessError, match="UNEXPECTED_MOUNT"):
        agent_endpoints.verify_agent_endpoints(binding, tmp_path)
