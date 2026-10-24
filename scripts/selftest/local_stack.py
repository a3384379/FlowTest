"""Create and remove only an explicitly owned, isolated A/B/Mock local stack."""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import Field
from scripts.selftest.bootstrap_journal import bootstrap_lock
from scripts.selftest.contracts import Contract, canonical_digest
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    object_value,
    objects_value,
    read_json,
    write_json,
)

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy/selftest/compose.yaml"


class StackBinding(Contract):
    schema_version: Literal["flowtest-selftest-binding-v1"] = "flowtest-selftest-binding-v1"
    project_name: str = Field(pattern=r"^flowtest-selftest-[0-9a-f]{12}$")
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    runtime_profile: Literal["full", "compact", "standalone"] = "standalone"
    runner_url: str
    target_url: str
    observer_url: str
    target_internal_url: Literal["http://target:8000"] = "http://target:8000"
    fixture_internal_url: Literal["http://mock-target:8080"] = "http://mock-target:8080"
    private_subnet: str
    candidate_image: str
    candidate_image_digest: str
    fixture_image: str
    fixture_image_digest: str
    source_digest: str
    candidate_source: str | None = None
    dependency_digest: str
    runner_container_id: str
    target_container_id: str
    observer_container_id: str
    runner_volume: str
    target_volume: str


class StackOwnership(Contract):
    project_name: str = Field(pattern=r"^flowtest-selftest-[0-9a-f]{12}$")
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")


class BuildReceipt(Contract):
    source_digest: str
    candidate_source: str | None = None
    dependency_digest: str
    candidate_image_digest: str
    fixture_image_digest: str


def _docker(arguments: list[str], *, timeout: int = 60, log_path: Path | None = None) -> str:
    executable = shutil.which("docker")
    if executable is None:
        raise HarnessError("SELFTEST_DOCKER_UNAVAILABLE")
    result = subprocess.run(  # noqa: S603 -- fixed docker binary and argument array
        [executable, *arguments], check=False, text=True, capture_output=True, timeout=timeout
    )
    if log_path is not None:
        log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        # Compose build output contains no generated environment, but never print inspect env.
        raise HarnessError(f"SELFTEST_DOCKER_COMMAND_FAILED:{arguments[0]}:{result.returncode}")
    return result.stdout.strip()


def _compose(
    project: str,
    env_path: Path,
    arguments: list[str],
    *,
    timeout: int = 60,
    log_path: Path | None = None,
) -> str:
    return _docker(
        [
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(env_path),
            "--file",
            str(COMPOSE),
            *arguments,
        ],
        timeout=timeout,
        log_path=log_path,
    )


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def source_digest(candidate_source: Path | None = None) -> str:
    root = candidate_source or ROOT
    directories = (root / "backend/app", root / "backend/migrations", root / "mock-target/app")
    inputs = tuple(
        root / name
        for name in (
            "backend/pyproject.toml",
            "backend/uv.lock",
            "backend/alembic.ini",
            "mock-target/pyproject.toml",
            "mock-target/uv.lock",
        )
    )
    if any(
        path.is_symlink()
        for path in (root / "backend", root / "mock-target", *directories, *inputs)
    ) or any(path.is_symlink() for base in directories for path in base.rglob("*")):
        raise HarnessError("SELFTEST_CANDIDATE_SYMLINK_FORBIDDEN")
    files = sorted((*inputs, *(path for base in directories for path in base.rglob("*.py"))))
    return canonical_digest(
        {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
        }
    )


def _candidate_source(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    root = Path(value).resolve(strict=True)
    if any(character in str(root) for character in "\r\n$#\"'"):
        raise HarnessError("SELFTEST_CANDIDATE_SOURCE_INVALID")
    if not all((root / name).is_dir() for name in ("backend/app", "mock-target/app")):
        raise HarnessError("SELFTEST_CANDIDATE_SOURCE_INVALID")
    return root


def _source_identity(root: Path | None) -> str:
    return source_digest() if root is None else source_digest(root)


def _new_environment(
    runtime_image: str, name: str, nonce: str, *, target_access_token_minutes: int = 15
) -> dict[str, str]:
    if type(target_access_token_minutes) is not int or not 1 <= target_access_token_minutes <= 60:
        raise HarnessError("SELFTEST_TARGET_AUTH_POLICY_INVALID")
    ports: set[int] = set()
    while len(ports) < 3:
        ports.add(_free_port())
    runner, target, observer = sorted(ports)
    return {
        "FLOWTEST_SELFTEST_RUNTIME_IMAGE": runtime_image,
        "FLOWTEST_SELFTEST_STACK_NONCE": nonce,
        "FLOWTEST_SELFTEST_CANDIDATE_IMAGE": f"{name}-candidate:local",
        "FLOWTEST_SELFTEST_FIXTURE_IMAGE": f"{name}-fixture:local",
        "FLOWTEST_SELFTEST_RUNNER_PORT": str(runner),
        "FLOWTEST_SELFTEST_TARGET_PORT": str(target),
        "FLOWTEST_SELFTEST_OBSERVER_PORT": str(observer),
        "FLOWTEST_SELFTEST_SUBNET": available_private_subnet(),
        "FLOWTEST_SELFTEST_RUNNER_KEY": secrets.token_urlsafe(48),
        "FLOWTEST_SELFTEST_TARGET_KEY": secrets.token_urlsafe(48),
        "FLOWTEST_SELFTEST_RUNNER_ENCRYPTION_KEY": base64.urlsafe_b64encode(
            os.urandom(32)
        ).decode(),
        "FLOWTEST_SELFTEST_TARGET_ENCRYPTION_KEY": base64.urlsafe_b64encode(
            os.urandom(32)
        ).decode(),
        "FLOWTEST_SELFTEST_RUNNER_PASSWORD": secrets.token_urlsafe(24),
        "FLOWTEST_SELFTEST_TARGET_PASSWORD": secrets.token_urlsafe(24),
        "FLOWTEST_SELFTEST_TARGET_ACCESS_TOKEN_MINUTES": str(target_access_token_minutes),
        "FLOWTEST_SELFTEST_OBSERVER_TOKEN": secrets.token_urlsafe(32),
    }


def choose_private_subnet(occupied: tuple[ipaddress.IPv4Network, ...]) -> str:
    for block in (ipaddress.ip_network("172.16.0.0/12"), ipaddress.ip_network("10.240.0.0/12")):
        for candidate in block.subnets(new_prefix=24):
            if not any(candidate.overlaps(existing) for existing in occupied):
                return str(candidate)
    raise HarnessError("SELFTEST_DOCKER_PRIVATE_SUBNET_UNAVAILABLE")


def available_private_subnet() -> str:
    ids = _docker(["network", "ls", "--quiet"]).splitlines()
    if len(ids) > 4096:
        raise HarnessError("SELFTEST_DOCKER_NETWORK_INVENTORY_TOO_LARGE")
    occupied: list[ipaddress.IPv4Network] = []
    for network_id in ids:
        raw = json.loads(
            _docker(["network", "inspect", network_id, "--format", "{{json .IPAM.Config}}"])
        )
        for config in objects_value(raw or []):
            subnet = config.get("Subnet")
            if isinstance(subnet, str):
                network = ipaddress.ip_network(subnet, strict=False)
                if isinstance(network, ipaddress.IPv4Network):
                    occupied.append(network)
    return choose_private_subnet(tuple(occupied))


def private_environment(directory: Path) -> dict[str, str]:
    path = directory / "private.env"
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise HarnessError("SELFTEST_PRIVATE_ENV_PERMISSIONS")
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if line)


def verify_binding(binding: StackBinding, directory: Path) -> None:
    """Re-read Docker identities before any privileged HTTP request or mutation."""
    private = _verify_binding_identity(binding, directory)
    if binding.runtime_profile == "standalone":
        _verify_assets(binding, private)
    else:
        from scripts.selftest.profile_stack import verify_profile_binding

        verify_profile_binding(binding, directory, private)


def _verify_assets(binding: StackBinding, private: dict[str, str]) -> None:
    mock_id = _docker(
        [
            "ps",
            "--quiet",
            "--no-trunc",
            "--filter",
            f"label=com.docker.compose.project={binding.project_name}",
            "--filter",
            "label=com.docker.compose.service=mock-target",
        ]
    )
    if not mock_id or "\n" in mock_id:
        raise HarnessError("SELFTEST_FIXTURE_CONTAINER_MISSING")
    roles = (
        ("runner", binding.runner_container_id, binding.candidate_image_digest, binding.runner_url),
        ("target", binding.target_container_id, binding.candidate_image_digest, binding.target_url),
        (
            "observer",
            binding.observer_container_id,
            binding.fixture_image_digest,
            binding.observer_url,
        ),
        ("mock-target", mock_id, binding.fixture_image_digest, None),
    )
    ports: set[int] = set()
    for role, container_id, digest, url in roles:
        inspection = object_value(
            json.loads(_docker(["inspect", container_id, "--format", "{{json .}}"]))
        )
        _verify_container(binding, role, inspection, digest, url)
        _verify_private_configuration(role, inspection, private)
        if url is None:
            continue
        port = urlsplit(url).port
        if port is None or port in ports:
            raise HarnessError("SELFTEST_BINDING_PORT_CONFLICT")
        ports.add(port)
    _verify_network(binding, "execution", mock_id)
    _verify_network(binding, "management", mock_id)
    for role in ("runner", "target", "observer"):
        _verify_network(binding, f"{role}-control", mock_id)
    for volume in (
        binding.runner_volume,
        binding.target_volume,
        f"{binding.project_name}_fixture-journal",
    ):
        actual = object_value(
            json.loads(_docker(["volume", "inspect", volume, "--format", "{{json .}}"]))
        )
        _verify_labels(binding, object_value(actual["Labels"]))


def _verify_binding_identity(
    binding: StackBinding, directory: Path, *, check_current_source: bool = True
) -> dict[str, str]:
    ownership = read_json(directory / "ownership.json")
    if ownership != {"project_name": binding.project_name, "nonce": binding.nonce}:
        raise HarnessError("SELFTEST_BINDING_OWNERSHIP_MISMATCH")
    private = private_environment(directory)
    from scripts.selftest.target_auth_policy import validate_target_auth_policy

    validate_target_auth_policy(directory, binding.project_name, binding.nonce, private)
    if private.get("FLOWTEST_SELFTEST_STACK_NONCE") != binding.nonce:
        raise HarnessError("SELFTEST_BINDING_NONCE_MISMATCH")
    if any(
        private[f"FLOWTEST_SELFTEST_RUNNER_{suffix}"]
        == private[f"FLOWTEST_SELFTEST_TARGET_{suffix}"]
        for suffix in ("KEY", "ENCRYPTION_KEY", "PASSWORD")
    ):
        raise HarnessError("SELFTEST_A_B_CREDENTIAL_ISOLATION_REQUIRED")
    if (
        binding.runner_container_id == binding.target_container_id
        or binding.runner_volume == binding.target_volume
    ):
        raise HarnessError("SELFTEST_A_B_ISOLATION_REQUIRED")
    candidate = _candidate_source(binding.candidate_source)
    if private.get("FLOWTEST_SELFTEST_BUILD_ROOT") != binding.candidate_source:
        raise HarnessError("SELFTEST_BINDING_SOURCE_CONTEXT_MISMATCH")
    if check_current_source and (
        binding.source_digest != _source_identity(candidate)
        or binding.dependency_digest
        != hashlib.sha256(((candidate or ROOT) / "backend/uv.lock").read_bytes()).hexdigest()
    ):
        raise HarnessError("SELFTEST_BINDING_BUILD_DRIFT")
    subnet = ipaddress.ip_network(binding.private_subnet, strict=True)
    if subnet.version != 4 or not subnet.is_private or subnet.prefixlen != 24:
        raise HarnessError("SELFTEST_BINDING_NETWORK_INVALID")
    return private


def _verify_labels(binding: StackBinding, labels: JsonObject) -> None:
    if (
        labels.get("com.docker.compose.project") != binding.project_name
        or labels.get("dev.flowtest.selftest.nonce") != binding.nonce
    ):
        raise HarnessError("SELFTEST_RESOURCE_OWNERSHIP_MISMATCH")


def _verify_container(
    binding: StackBinding,
    role: str,
    inspection: JsonObject,
    image: str,
    url: str | None,
    *,
    allow_missing_control: bool = False,
) -> None:
    config = object_value(inspection["Config"])
    labels = object_value(config["Labels"])
    _verify_labels(binding, labels)
    if labels.get("com.docker.compose.service") != role or inspection.get("Image") != image:
        raise HarnessError("SELFTEST_CONTAINER_BUILD_MISMATCH")
    if object_value(inspection["State"]).get("Running") is not True:
        raise HarnessError("SELFTEST_CONTAINER_NOT_RUNNING")
    network = "management" if role == "observer" else "execution"
    networks = object_value(object_value(inspection["NetworkSettings"])["Networks"])
    required = {f"{binding.project_name}_{network}"}
    expected = required | (
        {f"{binding.project_name}_{role}-control"} if role != "mock-target" else set()
    )
    matched = (
        required <= set(networks) <= expected
        if allow_missing_control
        else set(networks) == expected
    )
    if not matched:
        raise HarnessError("SELFTEST_CONTAINER_NETWORK_MISMATCH")
    mounts = objects_value(inspection["Mounts"])
    volume = {"runner": binding.runner_volume, "target": binding.target_volume}.get(
        role, f"{binding.project_name}_fixture-journal"
    )
    destination = "/journal" if role in {"observer", "mock-target"} else "/data"
    if len(mounts) != 1 or (
        mounts[0].get("Type"),
        mounts[0].get("Name"),
        mounts[0].get("Destination"),
    ) != ("volume", volume, destination):
        raise HarnessError("SELFTEST_CONTAINER_STORAGE_MISMATCH")
    if url is not None:
        _verify_published_port(inspection, url, "8081/tcp" if role == "observer" else "8000/tcp")


def _verify_published_port(inspection: JsonObject, url: str, container_port: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
    ):
        raise HarnessError("SELFTEST_BINDING_URL_INVALID")
    ports = object_value(object_value(inspection["NetworkSettings"])["Ports"])
    published = objects_value(ports.get(container_port))
    if (
        len(published) != 1
        or published[0].get("HostIp") != "127.0.0.1"
        or published[0].get("HostPort") != str(parsed.port)
    ):
        raise HarnessError("SELFTEST_BINDING_PORT_MISMATCH")


def _verify_target_binding_configuration(
    environment: dict[str, str], private: dict[str, str]
) -> None:
    if (
        "FLOWTEST_SELFTEST_TARGET_BINDINGS" in private
        and environment.get("FLOWTEST_SELFTEST_BINDINGS", "[]")
        != private["FLOWTEST_SELFTEST_TARGET_BINDINGS"]
    ):
        raise HarnessError("SELFTEST_PRODUCT_TARGET_CONFIGURATION_MISMATCH")


def _verify_private_configuration(
    role: str, inspection: JsonObject, private: dict[str, str]
) -> None:
    values = object_value(inspection["Config"])["Env"]
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise HarnessError("SELFTEST_CONTAINER_CONFIGURATION_INVALID")
    environment = dict(str(item).split("=", 1) for item in values if "=" in str(item))
    if role == "target":
        from scripts.selftest.target_auth_policy import verify_target_token_environment

        verify_target_token_environment(environment, private)
        _verify_target_binding_configuration(environment, private)
    if role in {"runner", "target"}:
        key = role.upper()
        expected = {
            "FLOWTEST_SECRET_KEY": private[f"FLOWTEST_SELFTEST_{key}_KEY"],
            "FLOWTEST_DATA_ENCRYPTION_KEY": private[f"FLOWTEST_SELFTEST_{key}_ENCRYPTION_KEY"],
            "FLOWTEST_SELFTEST_FIXTURE_RUN_DEPTH": "1" if role == "target" else "0",
        }
        if any(environment.get(name) != value for name, value in expected.items()):
            raise HarnessError("SELFTEST_CONTAINER_KEY_BINDING_MISMATCH")
        if "FLOWTEST_SELFTEST_OBSERVER_TOKEN" in environment:
            raise HarnessError("SELFTEST_OBSERVER_CREDENTIAL_EXPOSED")
    if role == "runner":
        for name in ("BINDINGS", "PRINCIPALS", "EXTRA_TEMPLATES", "PROBE_GRANTS"):
            setting = f"FLOWTEST_SELFTEST_{name}"
            if environment.get(setting, "[]") != private.get(setting, "[]"):
                raise HarnessError("SELFTEST_PRODUCT_CONFIGURATION_MISMATCH")
    if (
        role == "observer"
        and environment.get("FLOWTEST_SELFTEST_OBSERVER_TOKEN")
        != private["FLOWTEST_SELFTEST_OBSERVER_TOKEN"]
    ):
        raise HarnessError("SELFTEST_OBSERVER_CREDENTIAL_MISMATCH")


def _verify_network(binding: StackBinding, name: str, mock_id: str) -> None:
    network = object_value(
        json.loads(
            _docker(
                ["network", "inspect", f"{binding.project_name}_{name}", "--format", "{{json .}}"]
            )
        )
    )
    labels = object_value(network["Labels"])
    control = name.endswith("-control")
    if labels.get("com.docker.compose.project") != binding.project_name or network.get(
        "Internal"
    ) is not (not control):
        raise HarnessError("SELFTEST_NETWORK_OWNERSHIP_MISMATCH")
    if name == "execution":
        configured = objects_value(object_value(network["IPAM"])["Config"])
        if not configured or configured[0].get("Subnet") != binding.private_subnet:
            raise HarnessError("SELFTEST_NETWORK_SUBNET_MISMATCH")
    if control:
        role = name.removesuffix("-control")
        expected_ids = {getattr(binding, f"{role}_container_id")}
    elif name == "management":
        expected_ids = {binding.observer_container_id}
    else:
        expected_ids = {binding.runner_container_id, binding.target_container_id, mock_id}
    if set(object_value(network.get("Containers", {}))) != expected_ids:
        raise HarnessError("SELFTEST_NETWORK_MEMBERSHIP_MISMATCH")


def start(
    directory: Path,
    runtime_image: str,
    *,
    candidate_source: Path | None = None,
    target_access_token_minutes: int = 15,
) -> StackBinding:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (directory / "private.env").exists() or (directory / "stack.json").exists():
        raise HarnessError("SELFTEST_STACK_DIRECTORY_ALREADY_USED")
    # Require an existing local runtime; this command never silently chooses a daily stack.
    _docker(["image", "inspect", runtime_image, "--format", "{{.Id}}"])
    project = f"flowtest-selftest-{secrets.token_hex(6)}"
    nonce = uuid4().hex
    environment = _new_environment(
        runtime_image, project, nonce, target_access_token_minutes=target_access_token_minutes
    )
    candidate = _candidate_source(candidate_source)
    if candidate is not None:
        environment["FLOWTEST_SELFTEST_BUILD_ROOT"] = str(candidate)
        environment["FLOWTEST_SELFTEST_BUILD_RECIPE"] = str(ROOT / "deploy/selftest/Dockerfile")
    env_path = directory / "private.env"
    descriptor = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write("".join(f"{key}={value}\n" for key, value in environment.items()))
    write_json(directory / "ownership.json", {"project_name": project, "nonce": nonce})
    _build_images(project, env_path, environment, directory / "build.log")
    _compose(
        project,
        env_path,
        ["up", "--detach", "--wait", "--wait-timeout", "120"],
        timeout=180,
        log_path=directory / "start.log",
    )
    binding = _binding(project, nonce, environment, env_path)
    from scripts.selftest.target_auth_policy import freeze_target_auth_policy

    freeze_target_auth_policy(directory, project, nonce, environment)
    verify_binding(binding, directory)
    write_json(directory / "stack.json", binding)
    return binding


def _build_images(
    project: str, env_path: Path, environment: dict[str, str], log_path: Path
) -> BuildReceipt:
    candidate = _candidate_source(environment.get("FLOWTEST_SELFTEST_BUILD_ROOT"))
    source_before = _source_identity(candidate)
    _compose(project, env_path, ["build", "runner", "mock-target"], timeout=600, log_path=log_path)
    if _source_identity(candidate) != source_before:
        raise HarnessError("SELFTEST_SOURCE_CHANGED_DURING_BUILD")
    receipt = BuildReceipt(
        source_digest=source_before,
        candidate_source=str(candidate) if candidate else None,
        dependency_digest=hashlib.sha256(
            ((candidate or ROOT) / "backend/uv.lock").read_bytes()
        ).hexdigest(),
        candidate_image_digest=_docker(
            [
                "image",
                "inspect",
                environment["FLOWTEST_SELFTEST_CANDIDATE_IMAGE"],
                "--format",
                "{{.Id}}",
            ]
        ),
        fixture_image_digest=_docker(
            [
                "image",
                "inspect",
                environment["FLOWTEST_SELFTEST_FIXTURE_IMAGE"],
                "--format",
                "{{.Id}}",
            ]
        ),
    )
    write_json(env_path.parent / "build-receipt.json", receipt)
    return receipt


def refresh(directory: Path) -> StackBinding:
    """Rebuild and recreate an owned installed stack, preserving its data and evidence."""
    ownership = StackOwnership.model_validate(read_json(directory / "ownership.json"))
    with bootstrap_lock(directory, ownership.nonce):
        binding = StackBinding.model_validate(read_json(directory / "stack.json"))
        private = _verify_binding_identity(binding, directory, check_current_source=False)
        _verify_assets(binding, private)
        receipt = BuildReceipt.model_validate(read_json(directory / "build-receipt.json"))
        if any(
            getattr(receipt, key) != getattr(binding, key) for key in type(receipt).model_fields
        ):
            raise HarnessError("SELFTEST_REFRESH_BUILD_RECEIPT_MISMATCH")
        attempt = _next_resume_attempt(directory)
        write_json(
            directory / f"resume-{attempt}.json",
            {
                "project_name": ownership.project_name,
                "nonce": ownership.nonce,
                "action": "refresh_owned_images",
                "previous_binding": binding.model_dump(mode="json"),
            },
        )
        _build_images(
            ownership.project_name,
            directory / "private.env",
            private,
            directory / f"build-resume-{attempt}.log",
        )
        _compose(
            ownership.project_name,
            directory / "private.env",
            ["up", "--detach", "--force-recreate", "--wait", "--wait-timeout", "120"],
            timeout=180,
            log_path=directory / f"start-resume-{attempt}.log",
        )
        updated = _binding(
            ownership.project_name, ownership.nonce, private, directory / "private.env"
        )
        verify_binding(updated, directory)
        write_json(directory / "stack.json", updated)
        return updated


def resume(directory: Path, *, recreate_owned_containers: bool = False) -> StackBinding:
    """Resume an owned pre-container failure, preserving each earlier attempt log."""
    ownership = StackOwnership.model_validate(read_json(directory / "ownership.json"))
    with bootstrap_lock(directory, ownership.nonce):
        return _resume_owned(directory, ownership, recreate_owned_containers)


def _resume_owned(
    directory: Path, ownership: StackOwnership, recreate_owned_containers: bool
) -> StackBinding:
    private = private_environment(directory)
    if private.get("FLOWTEST_SELFTEST_STACK_NONCE") != ownership.nonce:
        raise HarnessError("SELFTEST_BINDING_NONCE_MISMATCH")
    if (directory / "stack.json").exists():
        binding = StackBinding.model_validate(read_json(directory / "stack.json"))
        verify_binding(binding, directory)
        return binding
    containers = _docker(
        [
            "ps",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            f"label=com.docker.compose.project={ownership.project_name}",
        ]
    )
    if containers:
        if recreate_owned_containers and not (directory / "installation.json").exists():
            return _recreate_owned_containers(directory, ownership, private, containers)
        raise HarnessError("SELFTEST_PARTIAL_STACK_NEEDS_REVIEW")
    _remove_empty_owned_networks(ownership)
    previous = private["FLOWTEST_SELFTEST_SUBNET"]
    private["FLOWTEST_SELFTEST_SUBNET"] = available_private_subnet()
    attempt = _next_resume_attempt(directory)
    write_json(
        directory / f"resume-{attempt}.json",
        {
            "project_name": ownership.project_name,
            "nonce": ownership.nonce,
            "previous_subnet": previous,
            "selected_subnet": private["FLOWTEST_SELFTEST_SUBNET"],
        },
    )
    _replace_private_environment(directory / "private.env", private)
    _build_images(
        ownership.project_name,
        directory / "private.env",
        private,
        directory / f"build-resume-{attempt}.log",
    )
    _compose(
        ownership.project_name,
        directory / "private.env",
        ["up", "--detach", "--wait", "--wait-timeout", "120"],
        timeout=180,
        log_path=directory / f"start-resume-{attempt}.log",
    )
    binding = _binding(ownership.project_name, ownership.nonce, private, directory / "private.env")
    verify_binding(binding, directory)
    write_json(directory / "stack.json", binding)
    return binding


def _recreate_owned_containers(
    directory: Path, ownership: StackOwnership, private: dict[str, str], containers: str
) -> StackBinding:
    binding = _binding(ownership.project_name, ownership.nonce, private, directory / "private.env")
    expected_ids = {
        binding.runner_container_id,
        binding.target_container_id,
        binding.observer_container_id,
    }
    roles: set[str] = set()
    for container in containers.splitlines():
        inspection = object_value(
            json.loads(_docker(["inspect", container, "--format", "{{json .}}"]))
        )
        labels = object_value(object_value(inspection["Config"])["Labels"])
        role = labels.get("com.docker.compose.service")
        if role not in {"runner", "target", "observer", "mock-target"} or role in roles:
            raise HarnessError("SELFTEST_PARTIAL_CONTAINER_NEEDS_REVIEW")
        roles.add(str(role))
        image = (
            binding.fixture_image_digest
            if role in {"observer", "mock-target"}
            else binding.candidate_image_digest
        )
        _verify_container(binding, str(role), inspection, image, None, allow_missing_control=True)
        _verify_private_configuration(str(role), inspection, private)
    if roles != {"runner", "target", "observer", "mock-target"} or not expected_ids <= set(
        containers.splitlines()
    ):
        raise HarnessError("SELFTEST_PARTIAL_CONTAINER_NEEDS_REVIEW")
    attempt = _next_resume_attempt(directory)
    write_json(
        directory / f"resume-{attempt}.json",
        {
            "project_name": ownership.project_name,
            "nonce": ownership.nonce,
            "action": "recreate_owned_control_access",
        },
    )
    _compose(
        ownership.project_name,
        directory / "private.env",
        [
            "up",
            "--detach",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "120",
            "runner",
            "target",
            "observer",
        ],
        timeout=180,
        log_path=directory / f"start-resume-{attempt}.log",
    )
    binding = _binding(ownership.project_name, ownership.nonce, private, directory / "private.env")
    verify_binding(binding, directory)
    write_json(directory / "stack.json", binding)
    return binding


def _next_resume_attempt(directory: Path) -> int:
    for attempt in range(1, 1001):
        names = (
            f"resume-{attempt}.json",
            f"build-resume-{attempt}.log",
            f"start-resume-{attempt}.log",
        )
        if not any((directory / name).exists() for name in names):
            return attempt
    raise HarnessError("SELFTEST_RESUME_ATTEMPT_BUDGET_EXCEEDED")


def _replace_private_environment(path: Path, environment: dict[str, str]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_TRUNC)
    with os.fdopen(descriptor, "w") as output:
        output.write("".join(f"{key}={value}\n" for key, value in environment.items()))
        output.flush()
        os.fsync(output.fileno())


def _remove_empty_owned_networks(ownership: StackOwnership) -> None:
    networks = _docker(
        [
            "network",
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={ownership.project_name}",
        ]
    )
    for network_id in networks.splitlines():
        network = object_value(
            json.loads(_docker(["network", "inspect", network_id, "--format", "{{json .}}"]))
        )
        labels = object_value(network["Labels"])
        if (
            labels.get("com.docker.compose.project") != ownership.project_name
            or network.get("Name")
            not in {f"{ownership.project_name}_execution", f"{ownership.project_name}_management"}
            or network.get("Containers")
        ):
            raise HarnessError("SELFTEST_PARTIAL_NETWORK_NEEDS_REVIEW")
        _docker(["network", "rm", network_id])


def _binding(project: str, nonce: str, environment: dict[str, str], env_path: Path) -> StackBinding:
    ids = {
        role: _compose(project, env_path, ["ps", "--quiet", role])
        for role in ("runner", "target", "observer")
    }
    candidate = environment["FLOWTEST_SELFTEST_CANDIDATE_IMAGE"]
    fixture = environment["FLOWTEST_SELFTEST_FIXTURE_IMAGE"]
    receipt = BuildReceipt.model_validate(read_json(env_path.parent / "build-receipt.json"))
    if receipt.candidate_image_digest != _docker(
        ["image", "inspect", candidate, "--format", "{{.Id}}"]
    ):
        raise HarnessError("SELFTEST_CANDIDATE_IMAGE_CHANGED")
    if receipt.fixture_image_digest != _docker(
        ["image", "inspect", fixture, "--format", "{{.Id}}"]
    ):
        raise HarnessError("SELFTEST_FIXTURE_IMAGE_CHANGED")
    return StackBinding(
        project_name=project,
        nonce=nonce,
        runner_url=f"http://127.0.0.1:{environment['FLOWTEST_SELFTEST_RUNNER_PORT']}",
        target_url=f"http://127.0.0.1:{environment['FLOWTEST_SELFTEST_TARGET_PORT']}",
        observer_url=f"http://127.0.0.1:{environment['FLOWTEST_SELFTEST_OBSERVER_PORT']}",
        private_subnet=environment["FLOWTEST_SELFTEST_SUBNET"],
        candidate_image=candidate,
        candidate_image_digest=receipt.candidate_image_digest,
        fixture_image=fixture,
        fixture_image_digest=receipt.fixture_image_digest,
        source_digest=receipt.source_digest,
        candidate_source=receipt.candidate_source,
        dependency_digest=receipt.dependency_digest,
        runner_container_id=ids["runner"],
        target_container_id=ids["target"],
        observer_container_id=ids["observer"],
        runner_volume=f"{project}_runner-data",
        target_volume=f"{project}_target-data",
    )


def stop(directory: Path) -> None:
    binding_path = directory / "stack.json"
    if binding_path.exists():
        binding = StackBinding.model_validate(read_json(binding_path))
        if binding.runtime_profile != "standalone":
            from scripts.selftest.profile_stack import stop as stop_profile

            stop_profile(directory)
            return
    ownership = StackOwnership.model_validate(read_json(directory / "ownership.json"))
    project, nonce = ownership.project_name, ownership.nonce
    containers = _docker(
        ["ps", "--all", "--quiet", "--filter", f"label=com.docker.compose.project={project}"]
    )
    for container in containers.splitlines():
        actual = _docker(
            [
                "inspect",
                container,
                "--format",
                '{{index .Config.Labels "dev.flowtest.selftest.nonce"}}',
            ]
        )
        if actual != nonce:
            raise HarnessError("SELFTEST_CONTAINER_OWNERSHIP_MISMATCH")
    volumes = _docker(
        ["volume", "ls", "--quiet", "--filter", f"label=com.docker.compose.project={project}"]
    )
    for volume in volumes.splitlines():
        actual = _docker(
            [
                "volume",
                "inspect",
                volume,
                "--format",
                '{{index .Labels "dev.flowtest.selftest.nonce"}}',
            ]
        )
        if actual != nonce:
            raise HarnessError("SELFTEST_VOLUME_OWNERSHIP_MISMATCH")
    if not (directory / "private.env").exists():
        if containers or volumes or not (directory / "cleanup.json").exists():
            raise HarnessError("SELFTEST_CLEANUP_STATE_NEEDS_REVIEW")
        _verify_removed(project)
        return
    private_environment(directory)
    _compose(
        project, directory / "private.env", ["down", "--volumes", "--timeout", "15"], timeout=90
    )
    _verify_removed(project)
    write_json(directory / "cleanup.json", {"project_name": project, "status": "completed"})
    (directory / "private.env").unlink()


def _verify_removed(project: str) -> None:
    commands = (
        ["ps", "--all", "--quiet"],
        ["volume", "ls", "--quiet"],
        ["network", "ls", "--quiet"],
    )
    for command in commands:
        if _docker([*command, "--filter", f"label=com.docker.compose.project={project}"]):
            raise HarnessError("SELFTEST_CLEANUP_RESOURCES_REMAIN")


def main() -> None:
    parser = argparse.ArgumentParser(description="启动或清理本轮隔离自测栈")
    parser.add_argument("action", choices=("start", "resume", "refresh", "stop"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--runtime-image")
    parser.add_argument("--candidate-source", type=Path)
    parser.add_argument("--recreate-owned-containers", action="store_true")
    parser.add_argument("--target-access-token-minutes", type=int, choices=range(1, 61), default=15)
    arguments = parser.parse_args()
    if arguments.action == "stop":
        stop(arguments.directory)
    elif arguments.action in {"resume", "refresh"}:
        binding = (
            refresh(arguments.directory)
            if arguments.action == "refresh"
            else resume(
                arguments.directory, recreate_owned_containers=arguments.recreate_owned_containers
            )
        )
        print(
            json.dumps(
                {
                    "project_name": binding.project_name,
                    "binding": str(arguments.directory / "stack.json"),
                }
            )
        )
    elif arguments.runtime_image:
        binding = start(
            arguments.directory,
            arguments.runtime_image,
            candidate_source=arguments.candidate_source,
            target_access_token_minutes=arguments.target_access_token_minutes,
        )
        print(
            json.dumps(
                {
                    "project_name": binding.project_name,
                    "binding": str(arguments.directory / "stack.json"),
                }
            )
        )
    else:
        parser.error("start 需要 --runtime-image, 必须为已存在的本地 FlowTest runtime")


if __name__ == "__main__":
    main()
