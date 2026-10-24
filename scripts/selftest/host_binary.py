"""Bounded local executable identity check; --version does not start model work."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from pydantic import Field
from scripts.selftest.contracts import Contract, Sha256
from scripts.selftest.host_launch import HostDeployment
from scripts.selftest.io import HarnessError


class CLIIdentity(Contract):
    executable_digest: Sha256
    cli_version: str = Field(min_length=1, max_length=200)


async def inspect_binary(deployment: HostDeployment) -> CLIIdentity:
    path = deployment.cli_executable
    if not path.is_absolute() or not path.is_file() or path.stat().st_mode & 0o022:
        raise HarnessError("HOST_CLI_EXECUTABLE_UNSAFE")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    process = await asyncio.create_subprocess_exec(
        str(path),
        "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"LANG": "en_US.UTF-8"},
        limit=4096,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=2)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise HarnessError("HOST_CLI_VERSION_TIMEOUT") from None
    if process.returncode != 0 or stderr or len(stdout) > 200:
        raise HarnessError("HOST_CLI_VERSION_UNAVAILABLE")
    actual = stdout.decode().strip()
    if actual != deployment.cli_version:
        raise HarnessError("HOST_CLI_VERSION_CHANGED")
    return CLIIdentity(executable_digest=digest, cli_version=actual)


def check_frozen_binary(current: CLIIdentity, prior_path: Path) -> None:
    if prior_path.exists() and CLIIdentity.model_validate_json(prior_path.read_bytes()) != current:
        raise HarnessError("HOST_CLI_BINARY_CHANGED_BETWEEN_PHASES")
