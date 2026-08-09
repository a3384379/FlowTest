#!/usr/bin/env python3
"""Run the S11 V1.0 operational and end-to-end acceptance flow."""

from __future__ import annotations

import json
import secrets
from typing import Any
from urllib.request import urlopen

from smoke_s4 import APIClient, SmokeConfig, _allow_compose_target, _change_password, _create_api
from smoke_s5 import _wait_for_completion
from smoke_s6 import _assert_parallel, _parallel_definition


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
        {"name": f"S11 V1 Pilot {secrets.token_hex(5)}", "description": "V1.0 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    _allow_compose_target(client, token, project_id, config.target_url)
    retention = client.json(
        "PUT",
        f"/projects/{project_id}/retention-policy",
        {"retention_days": 90},
        token=token,
    )
    if retention["retention_days"] != 90 or retention["maximum_days"] < 90:
        raise RuntimeError("project retention policy is inconsistent")
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": "V1 Mock Business", "base_url": config.target_url},
        token=token,
    )
    environment_id = str(environment["id"])

    successful_id = _verify_business_chain(client, token, project_id, environment_id)
    retry_id = _verify_failed_retry(client, token, project_id, environment_id)
    timeout_id = _verify_timeout(client, token, project_id, environment_id)
    cancelled_id = _verify_cancellation(client, token, project_id, environment_id)
    parallel_id = _verify_parallel(client, token, project_id, environment_id)
    _verify_viewer_permissions(client, config, token, project_id, successful_id)
    _verify_metrics(config)
    cleanup = client.json("POST", "/maintenance/retention-cleanup", token=token)
    if cleanup["projects_scanned"] < 1 or cleanup["storage_failures"] != 0:
        raise RuntimeError(f"retention cleanup did not complete safely: {cleanup}")
    return {
        "project_id": project_id,
        "successful_execution_id": successful_id,
        "retry_execution_id": retry_id,
        "timeout_execution_id": timeout_id,
        "cancelled_execution_id": cancelled_id,
        "parallel_execution_id": parallel_id,
    }


def _verify_business_chain(
    client: APIClient,
    token: str,
    project_id: str,
    environment_id: str,
) -> str:
    login_api = _create_api(
        client,
        token,
        project_id,
        name="业务登录",
        method="POST",
        path="/auth/login",
        body_kind="json",
        body={"username": "tester", "password": "flowtest"},
    )
    user_api = _create_api(
        client,
        token,
        project_id,
        name="查询当前用户",
        method="GET",
        path="/users/me",
    )
    order_api = _create_api(
        client,
        token,
        project_id,
        name="创建订单",
        method="POST",
        path="/orders",
        body_kind="json",
        body={"product": "FlowTest V1", "amount": 1},
    )
    definition = _business_definition(
        login_id=str(login_api["definition"]["id"]),
        user_id=str(user_api["definition"]["id"]),
        order_id=str(order_api["definition"]["id"]),
    )
    workflow_id = _create_and_publish(client, token, project_id, "V1 登录下单流程", definition)
    detail = _run_workflow(client, token, project_id, workflow_id, environment_id)
    if detail["execution"]["status"] != "passed":
        raise RuntimeError(f"V1 business workflow failed: {detail}")
    nodes = {node["node_id"]: node for node in detail["nodes"]}
    if nodes["user"]["output"]["body"]["data"]["id"] != "user-001":
        raise RuntimeError("current-user response was not mapped through the login token")
    if nodes["order"]["output"]["body"]["data"]["product"] != "FlowTest V1":
        raise RuntimeError("order response is incomplete")
    serialized = json.dumps(detail)
    if "mock-token" in serialized or nodes["extract"]["output"]["value"] != "***":
        raise RuntimeError("runtime authentication token leaked into execution history")
    execution_id = str(detail["execution"]["id"])
    report = client.json(
        "GET",
        f"/projects/{project_id}/reports/executions/{execution_id}",
        token=token,
    )
    report_nodes = {node["node_id"]: node for node in report["nodes"]}
    if report["summary"]["status"] != "passed" or not {"login", "user", "order"} <= set(
        report_nodes
    ):
        raise RuntimeError("business report cannot be drilled down to every API step")
    if "mock-token" in json.dumps(report):
        raise RuntimeError("runtime authentication token leaked into the report")
    return execution_id


def _verify_failed_retry(
    client: APIClient, token: str, project_id: str, environment_id: str
) -> str:
    api = _create_api(client, token, project_id, name="重试失败", method="GET", path="/failure")
    execution = _run_single_api_workflow(
        client,
        token,
        project_id,
        environment_id,
        name="V1 失败重试",
        api_id=str(api["definition"]["id"]),
        config={"max_retries": 1, "retry_on": ["network_error", "5xx"]},
    )
    node = next(item for item in execution["nodes"] if item["node_id"] == "api")
    if execution["execution"]["status"] != "failed" or node["attempts"] != 2:
        raise RuntimeError("5xx retry acceptance failed")
    return str(execution["execution"]["id"])


def _verify_timeout(client: APIClient, token: str, project_id: str, environment_id: str) -> str:
    api = _create_api(
        client, token, project_id, name="超时目标", method="GET", path="/slow?seconds=2"
    )
    execution = _run_single_api_workflow(
        client,
        token,
        project_id,
        environment_id,
        name="V1 超时流程",
        api_id=str(api["definition"]["id"]),
        config={"timeout_seconds": 1, "max_retries": 0},
    )
    node = next(item for item in execution["nodes"] if item["node_id"] == "api")
    if node["error_code"] != "NODE_TIMEOUT":
        raise RuntimeError(f"workflow timeout classification is incorrect: {node}")
    report = client.json(
        "GET",
        f"/projects/{project_id}/reports/executions/{execution['execution']['id']}",
        token=token,
    )
    if report["summary"]["failure_category"] != "timeout":
        raise RuntimeError("report did not retain timeout classification")
    return str(execution["execution"]["id"])


def _verify_cancellation(
    client: APIClient, token: str, project_id: str, environment_id: str
) -> str:
    api = _create_api(
        client, token, project_id, name="取消目标", method="GET", path="/slow?seconds=5"
    )
    workflow_id = _create_and_publish(
        client,
        token,
        project_id,
        "V1 取消流程",
        _single_api_definition(str(api["definition"]["id"]), {}),
    )
    started = client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/executions",
        {"environment_id": environment_id},
        token=token,
    )
    client.json(
        "POST",
        f"/projects/{project_id}/workflow-executions/{started['id']}/cancel",
        token=token,
    )
    detail = _wait_for_completion(client, token, project_id, str(started["id"]))
    if detail["execution"]["status"] != "cancelled":
        raise RuntimeError("workflow cancellation acceptance failed")
    return str(started["id"])


def _verify_parallel(client: APIClient, token: str, project_id: str, environment_id: str) -> str:
    api_ids = {
        "a": _get_api_id(
            _create_api(client, token, project_id, name="并行准备", method="GET", path="/health")
        ),
        "b": _get_api_id(
            _create_api(
                client,
                token,
                project_id,
                name="并行 B",
                method="GET",
                path="/slow?seconds=0.6",
            )
        ),
        "c": _get_api_id(
            _create_api(
                client,
                token,
                project_id,
                name="并行 C",
                method="GET",
                path="/slow?seconds=0.6",
            )
        ),
        "d": _get_api_id(
            _create_api(client, token, project_id, name="并行汇合", method="GET", path="/health")
        ),
    }
    workflow_id = _create_and_publish(
        client,
        token,
        project_id,
        "V1 并行流程",
        _parallel_definition(api_ids),
    )
    detail = _run_workflow(client, token, project_id, workflow_id, environment_id)
    _assert_parallel(detail)
    return str(detail["execution"]["id"])


def _verify_viewer_permissions(
    client: APIClient,
    config: SmokeConfig,
    token: str,
    project_id: str,
    execution_id: str,
) -> None:
    viewer_email = f"v1-viewer-{secrets.token_hex(5)}@flowtest.dev"
    initial_password = f"V1-Viewer-{secrets.token_urlsafe(12)}"
    viewer = client.json(
        "POST",
        "/users",
        {
            "email": viewer_email,
            "display_name": "V1 Viewer",
            "password": initial_password,
            "is_system_admin": False,
        },
        token=token,
    )
    client.json(
        "PUT",
        f"/projects/{project_id}/members/{viewer['id']}",
        {"user_id": viewer["id"], "role": "viewer"},
        token=token,
    )
    viewer_client = APIClient(config.api_url)
    login = viewer_client.json(
        "POST", "/auth/login", {"email": viewer_email, "password": initial_password}
    )
    viewer_token = str(login["access_token"])
    if login["user"]["requires_password_change"]:
        _change_password(
            viewer_client,
            viewer_token,
            initial_password,
            f"V1-Changed-{secrets.token_urlsafe(12)}",
        )
    viewer_client.json(
        "GET",
        f"/projects/{project_id}/reports/executions/{execution_id}",
        token=viewer_token,
    )
    try:
        viewer_client.json(
            "PATCH",
            f"/projects/{project_id}",
            {"description": "forbidden"},
            token=viewer_token,
        )
    except RuntimeError as error:
        if "403" not in str(error):
            raise
    else:
        raise RuntimeError("Viewer unexpectedly modified the project")
    viewer_client.json("POST", "/auth/logout", token=viewer_token)


def _verify_metrics(config: SmokeConfig) -> None:
    with urlopen(f"{config.api_url}/metrics", timeout=10) as response:
        content = response.read().decode()
    required = {"flowtest_info", "flowtest_http_requests_total", "flowtest_execution_records"}
    if not all(metric in content for metric in required):
        raise RuntimeError("Prometheus metrics endpoint is incomplete")


def _run_single_api_workflow(
    client: APIClient,
    token: str,
    project_id: str,
    environment_id: str,
    *,
    name: str,
    api_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    workflow_id = _create_and_publish(
        client,
        token,
        project_id,
        name,
        _single_api_definition(api_id, config),
    )
    return _run_workflow(client, token, project_id, workflow_id, environment_id)


def _run_workflow(
    client: APIClient,
    token: str,
    project_id: str,
    workflow_id: str,
    environment_id: str,
) -> dict[str, Any]:
    started = client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/executions",
        {"environment_id": environment_id},
        token=token,
        extra_headers={"Idempotency-Key": f"s11-{secrets.token_hex(12)}"},
    )
    return _wait_for_completion(client, token, project_id, str(started["id"]))


def _create_and_publish(
    client: APIClient,
    token: str,
    project_id: str,
    name: str,
    definition: dict[str, Any],
) -> str:
    workflow = client.json(
        "POST",
        f"/projects/{project_id}/workflows",
        {"name": name, "description": "S11 V1.0 acceptance", "definition": definition},
        token=token,
    )
    workflow_id = str(workflow["id"])
    client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/versions",
        token=token,
    )
    return workflow_id


def _single_api_definition(api_id: str, overrides: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "nodes": [
            _node("start", "start", "开始", 0),
            _node("api", "api", "接口请求", 200, {"api_definition_id": api_id, **overrides}),
            _node("end", "end", "结束", 400),
        ],
        "edges": [_edge("start", "api"), _edge("api", "end")],
        "settings": {"fail_fast": True, "concurrency": 20, "default_timeout_seconds": 30},
    }


def _business_definition(*, login_id: str, user_id: str, order_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "nodes": [
            _node("start", "start", "开始", 0),
            _node("login", "api", "登录", 180, {"api_definition_id": login_id}),
            _node(
                "extract",
                "extract",
                "提取令牌",
                360,
                {"source_node_id": "login", "expression": "body.data.token", "variable": "token"},
            ),
            _node("user", "api", "查询用户", 540, {"api_definition_id": user_id}, y=20),
            _node("order", "api", "创建订单", 540, {"api_definition_id": order_id}, y=180),
            _node(
                "assert-user",
                "assert",
                "校验用户",
                720,
                {
                    "source_node_id": "user",
                    "expression": "body.data.id",
                    "operator": "equals",
                    "expected": "user-001",
                },
                y=20,
            ),
            _node(
                "assert-order",
                "assert",
                "校验订单",
                720,
                {
                    "source_node_id": "order",
                    "expression": "body.data.product",
                    "operator": "equals",
                    "expected": "FlowTest V1",
                },
                y=180,
            ),
            _node("end", "end", "结束", 900, y=100),
        ],
        "edges": [
            _edge("start", "login"),
            _edge("login", "extract"),
            _auth_edge("extract", "user"),
            _auth_edge("extract", "order"),
            _edge("user", "assert-user"),
            _edge("order", "assert-order"),
            _edge("assert-user", "end"),
            _edge("assert-order", "end"),
        ],
        "settings": {"fail_fast": True, "concurrency": 20, "default_timeout_seconds": 30},
    }


def _auth_edge(source: str, target: str) -> dict[str, Any]:
    return _edge(
        source,
        target,
        mappings=[
            {
                "source": {"node_id": source, "path": "value"},
                "transform": {"kind": "template", "template": "Bearer {{value}}"},
                "target": {"node_id": target, "location": "header", "key": "Authorization"},
            }
        ],
    )


def _node(
    node_id: str,
    node_type: str,
    name: str,
    x: int,
    config: dict[str, Any] | None = None,
    *,
    y: int = 100,
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
    mappings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{source}-{target}",
        "source": source,
        "target": target,
        "mappings": mappings or [],
    }


def _get_api_id(result: dict[str, Any]) -> str:
    return str(result["definition"]["id"])


if __name__ == "__main__":
    main()
