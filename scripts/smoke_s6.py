#!/usr/bin/env python3
"""Run the S6 asynchronous parallel-workflow acceptance flow."""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any

from smoke_s4 import APIClient, SmokeConfig, _allow_compose_target, _change_password
from smoke_s5 import _create_api, _wait_for_completion


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
        {"name": f"S6 Smoke {secrets.token_hex(5)}", "description": "S6 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    _allow_compose_target(client, token, project_id, config.target_url)
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": "Compose Mock", "base_url": config.target_url},
        token=token,
    )
    api_ids = {
        "a": str(_create_api(client, token, project_id, "A 准备", "/health")["definition"]["id"]),
        "b": str(
            _create_api(client, token, project_id, "B 并行", "/slow?seconds=0.75")["definition"][
                "id"
            ]
        ),
        "c": str(
            _create_api(client, token, project_id, "C 并行", "/slow?seconds=0.75")["definition"][
                "id"
            ]
        ),
        "d": str(_create_api(client, token, project_id, "D 汇合", "/health")["definition"]["id"]),
    }
    workflow = client.json(
        "POST",
        f"/projects/{project_id}/workflows",
        {"name": "A-B/C-D 并行流程", "definition": _parallel_definition(api_ids)},
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
    if started["status"] != "running":
        raise RuntimeError("workflow start did not return a running execution")
    execution_id = str(started["id"])
    detail = _wait_for_completion(client, token, project_id, execution_id)
    _assert_parallel(detail)
    return {"project_id": project_id, "execution_id": execution_id}


def _assert_parallel(detail: dict[str, Any]) -> None:
    if detail["execution"]["status"] != "passed":
        raise RuntimeError(f"parallel workflow failed: {detail}")
    nodes = {node["node_id"]: node for node in detail["nodes"]}
    if set(nodes) != {"start", "a", "b", "c", "d", "end"}:
        raise RuntimeError("parallel workflow did not persist every node")
    if any(node["status"] != "passed" for node in nodes.values()):
        raise RuntimeError("parallel workflow contains a non-passed node")
    b_started = datetime.fromisoformat(str(nodes["b"]["started_at"]))
    b_completed = datetime.fromisoformat(str(nodes["b"]["completed_at"]))
    c_started = datetime.fromisoformat(str(nodes["c"]["started_at"]))
    c_completed = datetime.fromisoformat(str(nodes["c"]["completed_at"]))
    if max(b_started, c_started) >= min(b_completed, c_completed):
        raise RuntimeError("B and C did not overlap in time")


def _parallel_definition(api_ids: dict[str, str]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        _node("start", "start", "开始", 0, None),
        _node("a", "api", "A 准备", 220, api_ids["a"]),
        _node("b", "api", "B 并行", 440, api_ids["b"], y=0),
        _node("c", "api", "C 并行", 440, api_ids["c"], y=180),
        _node("d", "api", "D 汇合", 660, api_ids["d"]),
        _node("end", "end", "结束", 880, None),
    ]
    connections = [
        ("start", "a"),
        ("a", "b"),
        ("a", "c"),
        ("b", "d"),
        ("c", "d"),
        ("d", "end"),
    ]
    return {
        "schema_version": "1.0",
        "nodes": nodes,
        "edges": [
            {"id": f"{source}-{target}", "source": source, "target": target}
            for source, target in connections
        ],
        "settings": {"fail_fast": True, "concurrency": 20, "default_timeout_seconds": 30},
    }


def _node(
    node_id: str,
    node_type: str,
    name: str,
    x: int,
    api_id: str | None,
    *,
    y: int = 90,
) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if api_id is not None:
        config = {
            "api_definition_id": api_id,
            "max_retries": 0,
            "retry_on": ["network_error", "5xx"],
        }
    return {
        "id": node_id,
        "type": node_type,
        "name": name,
        "position": {"x": x, "y": y},
        "config": config,
    }


if __name__ == "__main__":
    main()
