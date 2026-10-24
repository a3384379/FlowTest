"""Private operator configuration; no browser or task payload chooses executable/auth paths."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Literal

from pydantic import Field
from scripts.selftest.contracts import Contract, Sha256, canonical_digest
from scripts.selftest.host_launch import HostDeployment, VerifiedGrant, verify_authorization
from scripts.selftest.host_prompts import HostTask, read_skill
from scripts.selftest.io import HarnessError


class HostRuntimeConfig(Contract):
    host_id: str = Field(min_length=1, max_length=200)
    cli_executable: Path
    cli_version: str
    credential_home: Path
    workspace: Path
    relay_executable: Path
    relay_prefix_args: tuple[str, ...] = Field(default=(), max_length=3)
    skill_directory: Path
    task_file: Path
    authorization_file: Path
    approval_key_file: Path
    approval_algorithm: Literal["RS256", "EdDSA"]
    approval_issuer: str
    approval_audience: str
    allowed_authorization_digests: tuple[Sha256, ...] = Field(min_length=1, max_length=100)
    tool_isolation_attestation: Sha256
    provider_cap_verified: bool = False
    archived_authorization_files: tuple[Path, ...] = Field(default=(), max_length=20)


def private_file(path: Path) -> bytes:
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not path.is_file()
        or stat.S_IMODE(path.stat().st_mode) & 0o077
        or path.stat().st_size > 1048576
    ):
        raise HarnessError("HOST_PRIVATE_CONFIGURATION_BOUNDARY_INVALID")
    return path.read_bytes()


def load_config(path: Path) -> HostRuntimeConfig:
    return HostRuntimeConfig.model_validate_json(private_file(path))


def approved_grant(config: HostRuntimeConfig) -> VerifiedGrant:
    return verify_authorization(
        private_file(config.authorization_file).decode().strip(),
        public_key=private_file(config.approval_key_file).decode(),
        algorithm=config.approval_algorithm,
        issuer=config.approval_issuer,
        audience=config.approval_audience,
        allowed_digests=frozenset(config.allowed_authorization_digests),
    )


def approved_task(config: HostRuntimeConfig, grant: VerifiedGrant) -> HostTask:
    task = HostTask.model_validate_json(private_file(config.task_file))
    if canonical_digest(task.model_dump(mode="json")) != grant.authorization.task_digest:
        raise HarnessError("HOST_FROZEN_TASK_CHANGED")
    return task


def approved_runtime(
    config: HostRuntimeConfig, directory: Path
) -> tuple[VerifiedGrant, HostDeployment, HostTask]:
    grant = approved_grant(config)
    task = approved_task(config, grant)
    skill = read_skill(config.skill_directory)
    if (
        config.credential_home.is_symlink()
        or not config.credential_home.is_dir()
        or stat.S_IMODE(config.credential_home.stat().st_mode) & 0o077
    ):
        raise HarnessError("HOST_AUTH_HOME_MUST_BE_PRIVATE")
    if (
        not config.workspace.is_absolute()
        or config.workspace.is_symlink()
        or not config.workspace.is_dir()
        or stat.S_IMODE(config.workspace.stat().st_mode) & 0o077
        or any(config.workspace.iterdir())
    ):
        raise HarnessError("HOST_WORKSPACE_INVALID")
    # Authentication is provided separately by the operator. Daily credentials are never copied.
    deployment = HostDeployment(
        config.host_id,
        config.cli_executable,
        config.cli_version,
        config.credential_home,
        config.workspace,
        config.relay_executable,
        directory / "relay.sock",
        skill.digest,
        task.authorized_data_digest,
        canonical_digest(task.model_dump(mode="json")),
        config.tool_isolation_attestation,
        config.provider_cap_verified,
        grant.authorization.policy_digest,
        config.relay_prefix_args,
    )
    return grant, deployment, task
