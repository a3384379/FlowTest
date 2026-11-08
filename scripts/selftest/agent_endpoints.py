"""Revalidate agent endpoints without loading deployment secrets or candidate Python."""

from __future__ import annotations

import hashlib
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit

from scripts.selftest.io import HarnessError, JsonObject, object_value, read_json
from scripts.selftest.local_stack import (
    ROOT,
    BuildReceipt,
    StackBinding,
    _docker,
    _verify_container,
    _verify_labels,
    _verify_published_port,
    source_digest,
)
from scripts.selftest.profile_stack import Profile, _command, _networks, _verify_mounts

# The Docker daemon selects only these public fields. Secret environment values
# never cross the process boundary; this is a fixed field projection, not redaction.
PUBLIC_INSPECTION = (
    '{{$profile := ""}}{{$depth := ""}}{{range .Config.Env}}{{if eq (index '
    '(split . "=") 0) "FLOWTEST_RUNTIME_PROFILE"}}{{$profile = .}}{{end}}{{'
    'if eq (index (split . "=") 0) "FLOWTEST_SELFTEST_FIXTURE_RUN_DEPTH"}}{'
    '{$depth = .}}{{end}}{{end}}{"Id":{{json .Id}},"Image":{{json .Image}},'
    '"Config":{"Labels":{"com.docker.compose.project":{{json (index .Config'
    '.Labels "com.docker.compose.project")}},"com.docker.compose.service":{'
    '{json (index .Config.Labels "com.docker.compose.service")}},"dev.flowt'
    'est.selftest.nonce":{{json (index .Config.Labels "dev.flowtest.selftes'
    't.nonce")}}},"Cmd":{{json .Config.Cmd}}},"State":{"Running":{{json .St'
    'ate.Running}}},"Mounts":{{json .Mounts}},"NetworkSettings":{"Networks"'
    ':{{json .NetworkSettings.Networks}},"Ports":{{json .NetworkSettings.Po'
    'rts}}},"runtime_profile":{{json $profile}},"fixture_run_depth":{{json '
    "$depth}}}"
)


def _identity(binding: StackBinding, directory: Path) -> None:
    if read_json(directory / "ownership.json") != {
        "project_name": binding.project_name,
        "nonce": binding.nonce,
    }:
        raise HarnessError("SELFTEST_BINDING_OWNERSHIP_MISMATCH")
    receipt = BuildReceipt.model_validate(read_json(directory / "build-receipt.json"))
    if any(getattr(receipt, name) != getattr(binding, name) for name in type(receipt).model_fields):
        raise HarnessError("SELFTEST_AGENT_BUILD_RECEIPT_MISMATCH")
    candidate = Path(binding.candidate_source) if binding.candidate_source else ROOT
    if (
        binding.source_digest != source_digest(candidate)
        or binding.dependency_digest
        != hashlib.sha256((candidate / "backend/uv.lock").read_bytes()).hexdigest()
    ):
        raise HarnessError("SELFTEST_BINDING_BUILD_DRIFT")
    network = ipaddress.ip_network(binding.private_subnet, strict=True)
    if network.version != 4 or not network.is_private or network.prefixlen != 24:
        raise HarnessError("SELFTEST_BINDING_NETWORK_INVALID")
    ports = {
        urlsplit(url).port for url in (binding.runner_url, binding.target_url, binding.observer_url)
    }
    if (
        len(ports) != 3
        or None in ports
        or binding.runner_container_id == binding.target_container_id
        or binding.runner_volume == binding.target_volume
    ):
        raise HarnessError("SELFTEST_A_B_ISOLATION_REQUIRED")


def _inspection(identifier: str) -> JsonObject:
    view = object_value(json.loads(_docker(["inspect", identifier, "--format", PUBLIC_INSPECTION])))
    if "Env" in object_value(view["Config"]):
        raise HarnessError("SELFTEST_AGENT_SECRET_PROJECTION_FORBIDDEN")
    return view


def _profile_container(
    binding: StackBinding,
    role: str,
    view: JsonObject,
    image: str,
    url: str | None,
) -> None:
    config = object_value(view["Config"])
    labels = object_value(config["Labels"])
    _verify_labels(binding, labels)
    if labels.get("com.docker.compose.service") != role or view.get("Image") != image:
        raise HarnessError("SELFTEST_CONTAINER_BUILD_MISMATCH")
    if object_value(view["State"]).get("Running") is not True:
        raise HarnessError("SELFTEST_CONTAINER_NOT_RUNNING")
    networks = object_value(object_value(view["NetworkSettings"])["Networks"])
    if set(networks) != {f"{binding.project_name}_{name}" for name in _networks(role)}:
        raise HarnessError("SELFTEST_PROFILE_NETWORK_MISMATCH")
    _verify_mounts(binding, role, view)
    if url is not None:
        _verify_published_port(view, url, "8081/tcp" if role == "observer" else "8000/tcp")


def _public_configuration(binding: StackBinding, role: str, view: JsonObject) -> None:
    if role not in {"runner", "target"}:
        return
    expected_depth = "1" if role == "target" else "0"
    if (
        view.get("runtime_profile") != f"FLOWTEST_RUNTIME_PROFILE={binding.runtime_profile}"
        or view.get("fixture_run_depth") != f"FLOWTEST_SELFTEST_FIXTURE_RUN_DEPTH={expected_depth}"
    ):
        raise HarnessError("SELFTEST_AGENT_PUBLIC_CONFIGURATION_MISMATCH")
    profile: Profile = "full" if binding.runtime_profile == "full" else "compact"
    if object_value(view["Config"]).get("Cmd") != list(_command(role, profile) or ()):
        raise HarnessError("SELFTEST_AGENT_API_COMMAND_MISMATCH")


def verify_agent_endpoints(binding: StackBinding, directory: Path) -> None:
    """Check public source/ownership/network/port identities before loading role credentials.

    Full deployment configuration and dependency topology are established by setup;
    this role check does not inspect secret keys, private.env, or dependency payloads.
    """
    _identity(binding, directory)
    mock = _docker(
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
    if not mock or "\n" in mock:
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
        ("mock-target", mock, binding.fixture_image_digest, None),
    )
    for role, identifier, image, url in roles:
        view = _inspection(identifier)
        if view.get("Id") != identifier:
            raise HarnessError("SELFTEST_AGENT_CONTAINER_IDENTITY_MISMATCH")
        if binding.runtime_profile == "standalone":
            _verify_container(binding, role, view, image, url)
        else:
            _profile_container(binding, role, view, image, url)
        _public_configuration(binding, role, view)
