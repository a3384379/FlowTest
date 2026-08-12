#!/usr/bin/env python3
"""Run the S26 signed environment template and restart-safe cleanup acceptance flow."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import time
from typing import Any, cast

from smoke_s4 import APIClient, SmokeConfig, _change_password

FIXTURE_IMAGE = (
    "nginxinc/nginx-unprivileged:1.31.3-alpine3.24@sha256:"
    "334d92979f15aaecd5dd50af5105e1230e2bb70765d45b1e2f964e7c5eda81c3"
)


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json("POST", "/auth/login", {"email": config.email, "password": config.password})
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(cast(dict[str, Any], login["user"])["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-S26-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    try:
        result = _run_acceptance(client, token)
        print(json.dumps({"status": "passed", **result}))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


def _run_acceptance(client: APIClient, token: str) -> dict[str, str]:
    _require_environment_feature(client, token)
    project = client.json(
        "POST",
        "/projects",
        {
            "name": f"S26 Environment {secrets.token_hex(5)}",
            "description": "S26 acceptance",
        },
        token=token,
    )
    project_id = str(project["id"])
    template, version = _create_versioned_template(client, token)

    idempotency_key = f"s26-{secrets.token_hex(12)}"
    instance = _queue(client, token, project_id, str(version["id"]), idempotency_key)
    repeated = _queue(client, token, project_id, str(version["id"]), idempotency_key)
    if repeated["id"] != instance["id"]:
        raise RuntimeError("S26 provision idempotency key created a duplicate instance")
    ready = _wait_for_status(
        client,
        token,
        project_id,
        str(instance["id"]),
        {"ready", "failed", "cancelled", "expired"},
    )
    if ready["status"] != "ready":
        raise RuntimeError(f"S26 environment did not become ready: {ready}")
    if not ready["endpoints"] or ready["seed_evidence"][0]["status_code"] != 200:
        raise RuntimeError("S26 health check or predefined Seed evidence is missing")

    _cleanup_instance(client, token, project_id, str(instance["id"]))
    return {
        "project_id": project_id,
        "template_id": str(template["template_id"]),
        "template_version_id": str(version["id"]),
        "instance_id": str(instance["id"]),
    }


def _require_environment_feature(client: APIClient, token: str) -> None:
    features = client.json("GET", "/v3/features", token=token)
    if not features.get("environment_lab"):
        raise RuntimeError("S26 environment feature is not enabled")


def _create_versioned_template(
    client: APIClient, token: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    template = client.json(
        "POST",
        "/environment-templates",
        {
            "template_key": f"acceptance.web-{secrets.token_hex(5)}",
            "display_name": "S26 受控 Web 环境",
            "description": "真实 DinD Environment Runner 验收",
            "manifest": _manifest(),
        },
        token=token,
    )
    if template["signature_algorithm"] != "hmac-sha256-v1":
        raise RuntimeError("S26 environment template was not platform signed")
    version = client.json(
        "POST",
        f"/environment-templates/{template['template_id']}/versions",
        {"manifest": {**_manifest(), "default_ttl_seconds": 180}},
        token=token,
    )
    if version["version"] != 2 or version["manifest_sha256"] == template["manifest_sha256"]:
        raise RuntimeError("S26 immutable template version was not created")
    return template, version


def _cleanup_instance(client: APIClient, token: str, project_id: str, instance_id: str) -> None:
    restart_worker = os.getenv("FLOWTEST_S26_RESTART_WORKER", "0") == "1"
    if restart_worker:
        _compose("stop", "worker-environment")
    try:
        client.json(
            "POST",
            f"/projects/{project_id}/environment-instances/{instance_id}/cleanup",
            token=token,
        )
    finally:
        if restart_worker:
            _compose("start", "worker-environment")
    cleaned = _wait_for_cleanup(client, token, project_id, instance_id)
    if cleaned["cleanup_status"] != "completed":
        raise RuntimeError(f"S26 cleanup did not complete after Runner restart: {cleaned}")
    repeated_cleanup = client.json(
        "POST",
        f"/projects/{project_id}/environment-instances/{instance_id}/cleanup",
        token=token,
    )
    if repeated_cleanup["cleanup_status"] != "completed":
        raise RuntimeError("S26 repeated cleanup was not idempotent")


def _queue(
    client: APIClient,
    token: str,
    project_id: str,
    template_version_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    return client.json(
        "POST",
        f"/projects/{project_id}/environment-instances",
        {"template_version_id": template_version_id, "ttl_seconds": 180},
        token=token,
        extra_headers={"Idempotency-Key": idempotency_key},
    )


def _wait_for_status(
    client: APIClient,
    token: str,
    project_id: str,
    instance_id: str,
    terminal: set[str],
) -> dict[str, Any]:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        detail = client.json(
            "GET",
            f"/projects/{project_id}/environment-instances/{instance_id}",
            token=token,
        )
        if detail["status"] in terminal:
            return detail
        time.sleep(1)
    raise RuntimeError(f"S26 environment {instance_id} did not finish in 180 seconds")


def _wait_for_cleanup(
    client: APIClient, token: str, project_id: str, instance_id: str
) -> dict[str, Any]:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        detail = client.json(
            "GET",
            f"/projects/{project_id}/environment-instances/{instance_id}",
            token=token,
        )
        if detail["cleanup_status"] == "completed":
            return detail
        if detail["cleanup_status"] == "failed":
            raise RuntimeError(f"S26 cleanup failed: {detail}")
        time.sleep(1)
    raise RuntimeError(f"S26 environment {instance_id} was not cleaned in 180 seconds")


def _compose(operation: str, service: str) -> None:
    if operation not in {"start", "stop"} or service != "worker-environment":
        raise ValueError("unsupported Compose smoke operation")
    docker_binary = shutil.which("docker")
    if docker_binary is None:
        raise RuntimeError("docker executable was not found")
    subprocess.run(  # noqa: S603 -- executable and every argument are locally allowlisted.
        [docker_binary, "compose", operation, service],
        check=True,
        timeout=120,
    )


def _manifest() -> dict[str, Any]:
    return {
        "services": [
            {
                "name": "web",
                "image": FIXTURE_IMAGE,
                "internal_port": 8080,
                "environment": [{"name": "NGINX_PORT", "value": "8080"}],
                "depends_on": [],
                "health_check": {
                    "kind": "http",
                    "path": "/",
                    "expected_status": 200,
                    "interval_seconds": 1,
                    "timeout_seconds": 2,
                    "maximum_attempts": 60,
                },
                "cpu_millicores": 250,
                "memory_megabytes": 128,
                "pids_limit": 64,
                "user_id": 101,
                "group_id": 101,
                "read_only_root_filesystem": True,
                "drop_all_capabilities": True,
                "no_new_privileges": True,
            }
        ],
        "seeds": [{"profile": "http_get_v1", "service": "web", "path": "/"}],
        "default_ttl_seconds": 120,
        "maximum_ttl_seconds": 300,
    }


if __name__ == "__main__":
    main()
