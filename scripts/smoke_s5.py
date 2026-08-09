#!/usr/bin/env python3
"""Run the S5 immutable workflow, retry, snapshot, and cancellation acceptance flow."""

from __future__ import annotations

import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from smoke_s4 import APIClient, SmokeConfig, _change_password


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
        {"name": f"S5 Smoke {secrets.token_hex(5)}", "description": "S5 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": "Compose Mock", "base_url": config.target_url},
        token=token,
    )
    environment_id = str(environment["id"])
    passed_execution = _verify_snapshot(client, token, project_id, environment_id)
    _verify_retry(client, token, project_id, environment_id)
    cancelled_execution = _verify_cancellation(
        client,
        config,
        token,
        project_id,
        environment_id,
    )
    return {
        "project_id": project_id,
        "passed_execution_id": str(passed_execution["execution"]["id"]),
        "cancelled_execution_id": str(cancelled_execution["execution"]["id"]),
    }


def _verify_snapshot(
    client: APIClient,
    token: str,
    project_id: str,
    environment_id: str,
) -> dict[str, Any]:
    api = _create_api(client, token, project_id, "健康检查", "/health")
    api_id = str(api["definition"]["id"])
    workflow = _create_workflow(client, token, project_id, "快照流程", api_id)
    workflow_id = str(workflow["id"])
    published = client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/versions",
        token=token,
    )
    if published["version"] != 1:
        raise RuntimeError("first immutable workflow version was not v1")
    result = client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/executions",
        {"environment_id": environment_id},
        token=token,
    )
    if result["execution"]["status"] != "passed":
        raise RuntimeError(f"workflow execution failed: {result}")
    snapshot = result["execution"]["snapshot"]
    if snapshot["workflow"]["version"] != 1 or snapshot["apis"]["api"]["version"] != 1:
        raise RuntimeError("workflow or API version was not captured in snapshot")

    client.json(
        "POST",
        f"/projects/{project_id}/apis/{api_id}/versions",
        _api_request("/failure"),
        token=token,
    )
    history = client.json(
        "GET",
        f"/projects/{project_id}/workflow-executions/{result['execution']['id']}",
        token=token,
    )
    historical_api = history["execution"]["snapshot"]["apis"]["api"]
    if historical_api["version"] != 1 or not historical_api["prepared_request"]["url"].endswith(
        "/health"
    ):
        raise RuntimeError("historical execution snapshot changed after API update")
    return result


def _verify_retry(
    client: APIClient,
    token: str,
    project_id: str,
    environment_id: str,
) -> None:
    api = _create_api(client, token, project_id, "失败接口", "/failure")
    workflow = _create_workflow(
        client,
        token,
        project_id,
        "重试流程",
        str(api["definition"]["id"]),
        max_retries=1,
    )
    workflow_id = str(workflow["id"])
    client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/versions",
        token=token,
    )
    result = client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/executions",
        {"environment_id": environment_id},
        token=token,
    )
    api_node = next(node for node in result["nodes"] if node["node_id"] == "api")
    if result["execution"]["status"] != "failed" or api_node["attempts"] != 2:
        raise RuntimeError("5xx workflow retry policy was not applied")


def _verify_cancellation(
    client: APIClient,
    config: SmokeConfig,
    token: str,
    project_id: str,
    environment_id: str,
) -> dict[str, Any]:
    api = _create_api(client, token, project_id, "慢接口", "/slow?seconds=5")
    workflow = _create_workflow(
        client,
        token,
        project_id,
        "取消流程",
        str(api["definition"]["id"]),
    )
    workflow_id = str(workflow["id"])
    client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/versions",
        token=token,
    )
    execution_client = APIClient(config.api_url)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            execution_client.json,
            "POST",
            f"/projects/{project_id}/workflows/{workflow_id}/executions",
            {"environment_id": environment_id},
            token=token,
        )
        execution_id = _wait_for_execution(client, token, project_id, workflow_id)
        requested = client.json(
            "POST",
            f"/projects/{project_id}/workflow-executions/{execution_id}/cancel",
            token=token,
        )
        if requested["cancel_requested_at"] is None:
            raise RuntimeError("workflow cancellation request was not persisted")
        result = future.result(timeout=3)
    if result["execution"]["status"] != "cancelled":
        raise RuntimeError("running workflow was not cancelled")
    return result


def _wait_for_execution(
    client: APIClient,
    token: str,
    project_id: str,
    workflow_id: str,
) -> str:
    for _attempt in range(80):
        page = client.json(
            "GET",
            f"/projects/{project_id}/workflow-executions?page=1&page_size=20",
            token=token,
        )
        matching = [item for item in page["items"] if item["workflow_id"] == workflow_id]
        if matching:
            return str(matching[0]["id"])
        time.sleep(0.05)
    raise RuntimeError("running workflow did not appear in execution history")


def _create_api(
    client: APIClient,
    token: str,
    project_id: str,
    name: str,
    path: str,
) -> dict[str, Any]:
    return client.json(
        "POST",
        f"/projects/{project_id}/apis",
        {"name": name, "description": "S5 smoke", "request": _api_request(path)},
        token=token,
    )


def _api_request(path: str) -> dict[str, Any]:
    return {
        "method": "GET",
        "path": path,
        "query_parameters": [],
        "headers": {},
        "body_kind": "none",
        "body": None,
        "auth": {"kind": "none", "values": {}},
    }


def _create_workflow(
    client: APIClient,
    token: str,
    project_id: str,
    name: str,
    api_id: str,
    *,
    max_retries: int = 0,
) -> dict[str, Any]:
    definition = {
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "name": "开始",
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "api",
                "type": "api",
                "name": "接口请求",
                "position": {"x": 100, "y": 0},
                "config": {"api_definition_id": api_id, "max_retries": max_retries},
            },
            {
                "id": "end",
                "type": "end",
                "name": "结束",
                "position": {"x": 200, "y": 0},
            },
        ],
        "edges": [
            {"id": "start-api", "source": "start", "target": "api"},
            {"id": "api-end", "source": "api", "target": "end"},
        ],
    }
    return client.json(
        "POST",
        f"/projects/{project_id}/workflows",
        {"name": name, "description": "S5 smoke", "definition": definition},
        token=token,
    )


if __name__ == "__main__":
    main()
