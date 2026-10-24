"""Gateway commands keep candidate imports remote and all secrets out of argv."""

import ast
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.selftest.io import HarnessError
from scripts.selftest.mcp_container_http import (
    REMOTE,
    GatewayProcess,
    GatewayRelay,
    ProcessRemoval,
    command,
)


@pytest.mark.parametrize("field", ["container", "nonce", "mode", "key"])
def test_gateway_rejects_nonallowlisted_arguments(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/docker")
    values = {"container_id": "a" * 64, "mode": "gateway", "nonce": "b" * 32, "key": "gateway"}
    name = "container_id" if field == "container" else field
    values[name] = "unsafe;synthetic"
    with pytest.raises(HarnessError, match="ARGUMENT_INVALID"):
        command(**values)


def test_fixed_remote_gateway_argv_has_no_bearer_or_host_candidate_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/docker")
    argv = command("a" * 64, "relay", "b" * 32, "c" * 32)
    assert argv[:6] == ["/usr/local/bin/docker", "exec", "--interactive", "a" * 64, "python", "-c"]
    assert "Authorization" not in " ".join(argv) and "SERVICE_ACCOUNT_TOKEN" not in " ".join(argv)
    assert argv[-4:] == ["relay", "b" * 32, "8766", "c" * 32]
    # Only the fixed candidate-side script can import the gateway.
    module = ast.parse(REMOTE)
    assert any(
        isinstance(row, ast.ImportFrom) and row.module == "app.mcp.cli" for row in ast.walk(module)
    )


def test_gateway_cleanup_receipts_require_positive_owned_process_identity() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GatewayProcess.model_validate(
            {
                "nonce": "a" * 32,
                "pid": 1,
                "start_ticks": "1",
                "port": 8766,
                "alive": True,
                "listening": False,
            }
        )
    with pytest.raises(ValidationError):
        ProcessRemoval.model_validate({"nonce": "a" * 32, "key": "gateway", "removed": False})


def test_gateway_cleanup_attempts_all_owned_processes_after_one_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.selftest import mcp_container_http

    calls = []
    nonce = "b" * 32

    async def control(container: str, mode: str, actual_nonce: str, key: str) -> dict:
        calls.append((container, mode, actual_nonce, key))
        if key == "c" * 32:
            raise HarnessError("synthetic-owned-stop-failure")
        return {"nonce": nonce, "key": key, "removed": True}

    monkeypatch.setattr(mcp_container_http, "_control", control)
    relay = GatewayRelay("a" * 64, nonce, datetime.now(UTC) + timedelta(seconds=60))
    relay.keys.extend(("c" * 32, "d" * 32))
    with pytest.raises(HarnessError, match="CLEANUP_INCOMPLETE"):
        asyncio.run(relay.stop())
    assert [call[-1] for call in calls] == ["c" * 32, "d" * 32, "gateway"]


def test_gateway_cleanup_wrong_nonce_cannot_be_claimed_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.selftest import mcp_container_http

    async def control(*args: object) -> dict:
        return {"nonce": "c" * 32, "key": "gateway", "removed": True}

    monkeypatch.setattr(mcp_container_http, "_control", control)
    relay = GatewayRelay("a" * 64, "b" * 32, datetime.now(UTC) + timedelta(seconds=60))
    with pytest.raises(HarnessError, match="CLEANUP_INCOMPLETE"):
        asyncio.run(relay.stop())


@pytest.mark.parametrize("candidate_source", [None, "/candidate-source"])
async def test_deployed_stdio_uses_candidate_container_for_both_source_shapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, candidate_source: str | None
) -> None:
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from scripts.selftest import run

    binding = SimpleNamespace(candidate_source=candidate_source, runner_container_id="a" * 64)
    calls = []
    client = object()

    @asynccontextmanager
    async def candidate(**kwargs: object):
        calls.append(kwargs)
        yield client

    monkeypatch.setattr(run, "container_stdio_protocol", candidate)
    async with run._protocol(
        binding, "stdio", "synthetic-private-token", "batch", tmp_path
    ) as active:
        assert active is client
    assert calls == [
        {
            "container_id": "a" * 64,
            "token": "synthetic-private-token",
            "batch_key": "batch",
            "output_dir": tmp_path,
        }
    ]


async def test_deployed_http_cannot_fall_back_to_host_candidate_without_owned_binding(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from scripts.selftest import run

    binding = SimpleNamespace(candidate_source=None, runner_container_id="a" * 64)
    with pytest.raises(HarnessError, match="HTTP_BINDING_REQUIRED"):
        async with run._protocol(binding, "streamable-http", "private", "batch", tmp_path):
            pytest.fail("unbound candidate gateway was admitted")


async def test_deployed_http_uses_owned_byte_gateway_and_per_request_bearer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from scripts.selftest import run

    binding = SimpleNamespace(candidate_source=None, runner_container_id="a" * 64)
    deadline = datetime.now(UTC) + timedelta(seconds=30)
    calls = []
    client = object()

    @asynccontextmanager
    async def gateway(actual, directory, output, *, deadline):
        calls.append((actual, directory, output, deadline))
        yield SimpleNamespace(url="http://127.0.0.1:43001/mcp")

    @asynccontextmanager
    async def protocol(**kwargs):
        calls.append(kwargs)
        yield client

    monkeypatch.setattr(run, "container_http_gateway", gateway)
    monkeypatch.setattr(run, "http_protocol", protocol)
    async with run._protocol(
        binding,
        "streamable-http",
        "synthetic-private-token",
        "batch",
        tmp_path,
        stack_directory=tmp_path / "owned",
        deadline=deadline,
    ) as active:
        assert active is client
    assert calls == [
        (binding, tmp_path / "owned", tmp_path, deadline),
        {
            "url": "http://127.0.0.1:43001/mcp",
            "token": "synthetic-private-token",
            "batch_key": "batch",
            "output_dir": tmp_path,
        },
    ]
