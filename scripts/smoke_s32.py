#!/usr/bin/env python3
"""Run the Compact profile control-plane and consolidated-worker acceptance flow."""

from __future__ import annotations

import json
import secrets
from typing import Any

from smoke_s4 import APIClient, SmokeConfig, _allow_compose_target, _change_password
from smoke_s5 import _create_api, _create_workflow, _start_and_wait

ARTIFACT_CONTENT = b"FlowTest S32 Compact recovery evidence\n"
COMPACT_RUNTIME_CONTRACT: dict[str, Any] = {
    "profile": "compact",
    "worker_topology": "consolidated",
    "unavailable_features": ["performance_lab", "environment_lab"],
}


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json(
        "POST", "/auth/login", {"email": config.email, "password": config.password}
    )
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


def _run_acceptance(
    client: APIClient,
    config: SmokeConfig,
    token: str,
    *,
    expected_runtime: dict[str, Any] | None = None,
) -> dict[str, str]:
    runtime = client.json("GET", "/runtime-profile")
    runtime_contract = expected_runtime or COMPACT_RUNTIME_CONTRACT
    if runtime != runtime_contract:
        raise RuntimeError(f"unexpected runtime contract: {runtime}")

    project = client.json(
        "POST",
        "/projects",
        {
            "name": f"S32 Compact {secrets.token_hex(5)}",
            "description": "S32 acceptance",
        },
        token=token,
    )
    project_id = str(project["id"])
    _allow_compose_target(client, token, project_id, config.target_url)
    artifact = client.multipart(
        f"/projects/{project_id}/files",
        field="file",
        filename="s32-recovery-evidence.txt",
        content=ARTIFACT_CONTENT,
        content_type="text/plain",
        token=token,
    )
    if (
        client.download(f"/projects/{project_id}/files/{artifact['id']}", token=token)
        != ARTIFACT_CONTENT
    ):
        raise RuntimeError("Compact Artifact round trip failed")
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": "Compact Control Plane", "base_url": config.target_url},
        token=token,
    )
    api = _create_api(client, token, project_id, "Compact 就绪检查", "/live")
    workflow = _create_workflow(
        client,
        token,
        project_id,
        "Compact 合并 Worker 验收",
        str(api["definition"]["id"]),
    )
    workflow_id = str(workflow["id"])
    published = client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/versions",
        token=token,
    )
    result = _start_and_wait(
        client,
        token,
        project_id,
        workflow_id,
        str(environment["id"]),
    )
    if published["version"] != 1 or result["execution"]["status"] != "passed":
        raise RuntimeError(f"Compact workflow execution failed: {result}")
    api_node = next(node for node in result["nodes"] if node["node_id"] == "api")
    snapshot = result["execution"]["snapshot"]
    if api_node["status"] != "passed" or snapshot["workflow"]["version"] != 1:
        raise RuntimeError(
            "Compact consolidated Worker did not preserve the execution snapshot"
        )
    return {
        "project_id": project_id,
        "artifact_id": str(artifact["id"]),
        "workflow_execution_id": str(result["execution"]["id"]),
    }


if __name__ == "__main__":
    main()
