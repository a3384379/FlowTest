#!/usr/bin/env python3
"""Run the S10 governance, import merge, SSRF, audit, and idempotency acceptance flow."""

from __future__ import annotations

import json
import secrets
from typing import Any

from smoke_s4 import APIClient, SmokeConfig, _allow_compose_target, _change_password


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json("POST", "/auth/login", {"email": config.email, "password": config.password})
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(login["user"]["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-Smoke-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    try:
        result = _run_acceptance(client, config, token)
        print(json.dumps({"status": "passed", **result}))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


def _run_acceptance(client: APIClient, config: SmokeConfig, token: str) -> dict[str, str]:
    project = client.json(
        "POST",
        "/projects",
        {"name": f"S10 Smoke {secrets.token_hex(5)}", "description": "S10 governance"},
        token=token,
    )
    project_id = str(project["id"])
    _allow_compose_target(client, token, project_id, config.target_url)
    permissions = client.json("GET", f"/projects/{project_id}/permissions", token=token)
    if permissions["effective_role"] != "system_admin" or len(permissions["capabilities"]) != 6:
        raise RuntimeError("system administrator capability matrix is incomplete")

    active_definition_id = _verify_selective_import(client, token, project_id)
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": "Compose Mock", "base_url": config.target_url},
        token=token,
    )
    execution_id = _verify_idempotency(
        client,
        token,
        project_id,
        active_definition_id,
        str(environment["id"]),
    )
    _verify_ssrf_and_secret_readback(client, token, project_id)
    audit = client.json(
        "GET",
        f"/projects/{project_id}/audit-logs?page=1&page_size=100",
        token=token,
    )
    actions = {item["action"] for item in audit["items"]}
    required = {
        "project.security_policy_updated",
        "api.import_previewed",
        "api.import_merged",
        "api.execution_started",
    }
    if not required <= actions:
        raise RuntimeError(f"audit actions are incomplete: {sorted(required - actions)}")
    return {"project_id": project_id, "execution_id": execution_id}


def _verify_selective_import(client: APIClient, token: str, project_id: str) -> str:
    original = _openapi(
        {
            "/health": {"get": {"summary": "Health"}},
            "/old": {"get": {"summary": "Old"}},
        }
    )
    first = _preview(client, token, project_id, original)
    initial_keys = [item["import_key"] for item in first["results"]]
    client.json(
        "POST",
        f"/projects/{project_id}/imports/{first['id']}/merge",
        {"selected_keys": initial_keys},
        token=token,
    )

    changed = _openapi(
        {
            "/health": {"get": {"summary": "Health v2"}},
            "/new": {"get": {"summary": "New"}},
        }
    )
    diff = _preview(client, token, project_id, changed)
    selected = [
        item["import_key"] for item in diff["results"] if item["change"] in {"added", "changed"}
    ]
    client.json(
        "POST",
        f"/projects/{project_id}/imports/{diff['id']}/merge",
        {"selected_keys": selected},
        token=token,
    )
    if client.json("GET", f"/projects/{project_id}/apis?page_size=100", token=token)["total"] != 3:
        raise RuntimeError("unselected deletion was applied")

    deletion_preview = _preview(client, token, project_id, changed)
    deleted = next(item for item in deletion_preview["results"] if item["change"] == "deleted")
    client.json(
        "POST",
        f"/projects/{project_id}/imports/{deletion_preview['id']}/merge",
        {"selected_keys": [deleted["import_key"]]},
        token=token,
    )
    definitions = client.json("GET", f"/projects/{project_id}/apis?page_size=100", token=token)
    if definitions["total"] != 2:
        raise RuntimeError("explicit import deletion was not deactivated")
    health = next(item for item in definitions["items"] if item["name"] == "Health v2")
    return str(health["id"])


def _verify_idempotency(
    client: APIClient,
    token: str,
    project_id: str,
    definition_id: str,
    environment_id: str,
) -> str:
    path = f"/projects/{project_id}/apis/{definition_id}/execute"
    headers = {"Idempotency-Key": f"s10-{secrets.token_hex(12)}"}
    payload: dict[str, Any] = {"environment_id": environment_id}
    first = client.json("POST", path, payload, token=token, extra_headers=headers)
    replayed = client.json("POST", path, payload, token=token, extra_headers=headers)
    if first["execution"]["id"] != replayed["execution"]["id"]:
        raise RuntimeError("idempotent execution created a duplicate")
    try:
        client.json(
            "POST",
            path,
            {"environment_id": environment_id, "timeout_seconds": 5},
            token=token,
            extra_headers=headers,
        )
    except RuntimeError as error:
        if "IDEMPOTENCY_KEY_REUSED" not in str(error):
            raise
    else:
        raise RuntimeError("idempotency key reuse with a different payload was accepted")
    return str(first["execution"]["id"])


def _verify_ssrf_and_secret_readback(client: APIClient, token: str, project_id: str) -> None:
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": "Metadata", "base_url": "http://169.254.169.254"},
        token=token,
    )
    definition = client.json(
        "POST",
        f"/projects/{project_id}/apis",
        {"name": "Metadata", "request": {"method": "GET", "path": "/latest/meta-data"}},
        token=token,
    )
    try:
        client.json(
            "POST",
            f"/projects/{project_id}/apis/{definition['definition']['id']}/execute",
            {"environment_id": environment["id"]},
            token=token,
        )
    except RuntimeError as error:
        if "OUTBOUND_REQUEST_BLOCKED" not in str(error):
            raise
    else:
        raise RuntimeError("metadata SSRF request was accepted")

    client.json(
        "PUT",
        f"/projects/{project_id}/secrets",
        {"name": "S10_TOKEN", "value": "must-never-read-back"},
        token=token,
    )
    listed = client.json("GET", f"/projects/{project_id}/secrets", token=token)
    serialized = json.dumps(listed)
    if "must-never-read-back" in serialized or "ciphertext" in serialized:
        raise RuntimeError("secret value leaked through metadata endpoint")


def _preview(client: APIClient, token: str, project_id: str, content: bytes) -> dict[str, Any]:
    return client.multipart(
        f"/projects/{project_id}/imports/preview",
        field="document",
        filename="s10-openapi.json",
        content=content,
        content_type="application/json",
        fields={"source_type": "auto"},
        token=token,
    )


def _openapi(paths: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "S10", "version": "1.0.0"},
            "paths": paths,
        }
    ).encode()


if __name__ == "__main__":
    main()
