#!/usr/bin/env python3
"""Run the S22 Capability SDK compatibility and snapshot acceptance flow."""

from __future__ import annotations

import json
import secrets
from typing import Any, cast

from smoke_s4 import APIClient, SmokeConfig, _change_password
from smoke_s5 import _wait_for_completion


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json("POST", "/auth/login", {"email": config.email, "password": config.password})
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(cast(dict[str, Any], login["user"])["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-S22-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    try:
        result = _run_acceptance(client, config, token)
        print(json.dumps({"status": "passed", **result}))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


def _run_acceptance(client: APIClient, config: SmokeConfig, token: str) -> dict[str, str]:
    flags = client.json("GET", "/v3/features", token=token)
    if (
        not flags.get("capability_sdk")
        or flags.get("plugin_registry")
        or flags.get("runner_fabric")
    ):
        raise RuntimeError(f"unexpected S22 feature boundary: {flags}")
    capabilities = client.json("GET", "/capabilities?page=1&page_size=100", token=token)
    if capabilities["total"] < 12:
        raise RuntimeError("V2 built-in nodes were not fully adapted to Capability manifests")
    keys = {(item["id"], item["version"]) for item in capabilities["items"]}
    if ("flow.delay", "2.0.0") not in keys or ("http.request", "2.0.0") not in keys:
        raise RuntimeError("required built-in Capability versions are missing")

    project = client.json(
        "POST",
        "/projects",
        {"name": f"S22 Capability {secrets.token_hex(5)}", "description": "S22 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": "Compose Mock", "base_url": config.target_url},
        token=token,
    )
    workflow = client.json(
        "POST",
        f"/projects/{project_id}/workflows",
        {
            "name": "S22 V2 V3 混合流程",
            "description": "Legacy Start/End 与显式 Capability Delay 混合执行",
            "definition": _mixed_definition(),
        },
        token=token,
    )
    workflow_id = str(workflow["id"])
    client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/versions",
        token=token,
    )
    started = client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/executions",
        {"environment_id": str(environment["id"])},
        token=token,
    )
    detail = _wait_for_completion(client, token, project_id, str(started["id"]))
    if detail["execution"]["status"] != "passed":
        raise RuntimeError(f"mixed Capability Workflow failed: {detail}")
    snapshot = detail["execution"]["snapshot"]["capabilities"]
    if snapshot["wait"]["capability_id"] != "flow.delay" or snapshot["wait"]["source"] != "v3":
        raise RuntimeError("explicit Capability was not pinned in the execution snapshot")
    if snapshot["start"]["source"] != "legacy" or len(snapshot["wait"]["schema_hash"]) != 64:
        raise RuntimeError("Legacy Adapter or Capability Schema hash was not fixed")
    wait_node = next(item for item in detail["nodes"] if item["node_id"] == "wait")
    if wait_node["result"]["status"] != "passed" or wait_node["node_type"] != "capability":
        raise RuntimeError("unified NodeResult was not persisted for the Capability node")
    return {
        "project_id": project_id,
        "workflow_id": workflow_id,
        "execution_id": str(started["id"]),
    }


def _mixed_definition() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "variables": {},
        "nodes": [
            _legacy_node("start", "start", "开始", 0),
            {
                "id": "wait",
                "type": "capability",
                "name": "能力等待",
                "position": {"x": 240, "y": 80},
                "config": {},
                "capability_id": "flow.delay",
                "capability_version": "2.0.0",
                "configuration": {"seconds": 0},
                "bindings": [],
            },
            _legacy_node("end", "end", "结束", 480),
        ],
        "edges": [
            {"id": "start-wait", "source": "start", "target": "wait"},
            {"id": "wait-end", "source": "wait", "target": "end"},
        ],
        "settings": {"fail_fast": True, "concurrency": 20, "default_timeout_seconds": 30},
    }


def _legacy_node(node_id: str, node_type: str, name: str, x: int) -> dict[str, object]:
    return {
        "id": node_id,
        "type": node_type,
        "name": name,
        "position": {"x": x, "y": 80},
        "config": {},
    }


if __name__ == "__main__":
    main()
