#!/usr/bin/env python3
"""Run the S7 dataset, mapping, and control-node acceptance flow."""

from __future__ import annotations

import json
import secrets
from typing import Any

from smoke_s4 import APIClient, SmokeConfig, _change_password, _create_api
from smoke_s5 import _wait_for_completion


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
        {"name": f"S7 Smoke {secrets.token_hex(5)}", "description": "S7 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": "Compose Mock", "base_url": config.target_url},
        token=token,
    )
    artifact = client.multipart(
        f"/projects/{project_id}/files",
        field="file",
        filename="users.json",
        content=json.dumps(
            [
                {"username": "enabled-user", "enabled": True},
                {"username": "disabled-user", "enabled": False},
            ]
        ).encode(),
        content_type="application/json",
        token=token,
    )
    source_api = _create_api(
        client,
        token,
        project_id,
        name="数据行回显",
        method="POST",
        path="/echo",
        body_kind="json",
        body={"username": "{{username}}", "enabled": "{{enabled}}"},
    )
    target_api = _create_api(
        client,
        token,
        project_id,
        name="映射结果回显",
        method="POST",
        path="/echo",
        body_kind="json",
        body={"username": ""},
    )
    workflow = client.json(
        "POST",
        f"/projects/{project_id}/workflows",
        {
            "name": "数据集控制节点流程",
            "description": "S7 dataset mapping acceptance",
            "definition": _definition(
                str(artifact["id"]),
                str(source_api["definition"]["id"]),
                str(target_api["definition"]["id"]),
            ),
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
    _assert_dataset_execution(client, token, project_id, detail)
    return {"project_id": project_id, "execution_id": str(started["id"])}


def _assert_dataset_execution(
    client: APIClient,
    token: str,
    project_id: str,
    detail: dict[str, Any],
) -> None:
    execution = detail["execution"]
    children = detail["children"]
    if execution["status"] != "passed" or len(children) != 2:
        raise RuntimeError(f"dataset parent aggregation failed: {detail}")
    if execution["context"]["dataset_summary"] != {
        "total": 2,
        "passed": 2,
        "failed": 0,
        "cancelled": 0,
    }:
        raise RuntimeError("dataset summary is inconsistent")

    condition_values: set[str] = set()
    for row_index, child in enumerate(children):
        if (
            child["dataset_row_index"] != row_index
            or child["parent_execution_id"] != execution["id"]
        ):
            raise RuntimeError("dataset child identity is inconsistent")
        child_detail = client.json(
            "GET",
            f"/projects/{project_id}/workflow-executions/{child['id']}",
            token=token,
        )
        nodes = {node["node_id"]: node for node in child_detail["nodes"]}
        branch_states = sorted([nodes["true-delay"]["status"], nodes["false-delay"]["status"]])
        if branch_states != ["passed", "skipped"] or nodes["end"]["status"] != "passed":
            raise RuntimeError("condition branch did not preserve join semantics")
        if nodes["target"]["output"]["input_mappings"][0]["target_key"] != "username":
            raise RuntimeError("field mapping trace is missing")
        condition_values.add(str(nodes["condition"]["output"]["actual"]))
        variable_source = child_detail["execution"]["context"]["variable_sources"]["username"]
        if variable_source["scope"] != "dataset":
            raise RuntimeError("dataset variable provenance is missing")
    if condition_values != {"true", "false"}:
        raise RuntimeError("both condition branches were not exercised")

    history = client.json(
        "GET",
        f"/projects/{project_id}/workflow-executions?page=1&page_size=100",
        token=token,
    )
    if any(item["parent_execution_id"] is not None for item in history["items"]):
        raise RuntimeError("child executions leaked into top-level history")


def _definition(artifact_id: str, source_api_id: str, target_api_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "variables": {},
        "nodes": [
            _node("start", "start", "开始", 0),
            _node("dataset", "dataset", "用户数据", 180, {"artifact_id": artifact_id}),
            _node("source", "api", "数据行回显", 360, {"api_definition_id": source_api_id}),
            _node(
                "extract",
                "extract",
                "提取用户名",
                540,
                {
                    "source_node_id": "source",
                    "expression": "body.username",
                    "variable": "selected_username",
                },
            ),
            _node("target", "api", "映射用户名", 720, {"api_definition_id": target_api_id}),
            _node(
                "assert",
                "assert",
                "校验状态",
                900,
                {
                    "source_node_id": "target",
                    "expression": "status_code",
                    "operator": "equals",
                    "expected": 200,
                },
            ),
            _node(
                "condition",
                "condition",
                "判断启用",
                1080,
                {
                    "source_node_id": "source",
                    "expression": "body.enabled",
                    "operator": "equals",
                    "expected": "true",
                },
            ),
            _node("true-delay", "delay", "启用分支", 1260, {"seconds": 0}, y=20),
            _node("false-delay", "delay", "停用分支", 1260, {"seconds": 0}, y=160),
            _node("end", "end", "结束", 1440),
        ],
        "edges": [
            _edge("start", "dataset"),
            _edge("dataset", "source"),
            _edge("source", "extract"),
            _edge(
                "extract",
                "target",
                mappings=[
                    {
                        "source": {"node_id": "extract", "path": "value"},
                        "target": {"node_id": "target", "location": "body", "key": "username"},
                    }
                ],
            ),
            _edge("target", "assert"),
            _edge("assert", "condition"),
            _edge("condition", "true-delay", condition="true"),
            _edge("condition", "false-delay", condition="false"),
            _edge("true-delay", "end"),
            _edge("false-delay", "end"),
        ],
        "settings": {"fail_fast": True, "concurrency": 20, "default_timeout_seconds": 30},
    }


def _node(
    node_id: str,
    node_type: str,
    name: str,
    x: int,
    config: dict[str, Any] | None = None,
    *,
    y: int = 90,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "name": name,
        "position": {"x": x, "y": y},
        "config": config or {},
    }


def _edge(
    source: str,
    target: str,
    *,
    condition: str | None = None,
    mappings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{source}-{target}",
        "source": source,
        "target": target,
        "condition": condition,
        "mappings": mappings or [],
    }


if __name__ == "__main__":
    main()
