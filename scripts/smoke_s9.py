#!/usr/bin/env python3
"""Run the S9 report, HTML export, trend, and signed notification acceptance flow."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from smoke_s4 import APIClient, SmokeConfig, _change_password
from smoke_s5 import _create_api, _create_workflow, _wait_for_completion


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
        {"name": f"S9 Smoke {secrets.token_hex(5)}", "description": "S9 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": "Compose Mock", "base_url": config.target_url},
        token=token,
    )
    api = _create_api(client, token, project_id, "预期失败接口", "/failure")
    workflow = _create_workflow(
        client,
        token,
        project_id,
        "报告失败分类流程",
        str(api["definition"]["id"]),
    )
    workflow_id = str(workflow["id"])
    client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/versions",
        token=token,
    )
    configured = client.json(
        "POST",
        f"/projects/{project_id}/notification-webhooks",
        {
            "name": "Compose 通知接收器",
            "url": f"{config.target_url}/notifications/flowtest",
            "events": ["workflow.completed"],
        },
        token=token,
    )
    secret = str(configured["secret"])
    started = client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/executions",
        {"environment_id": str(environment["id"])},
        token=token,
    )
    execution_id = str(started["id"])
    completed = _wait_for_completion(client, token, project_id, execution_id)
    if completed["execution"]["status"] != "failed":
        raise RuntimeError("expected reporting workflow to fail")
    notification = _wait_for_notification(execution_id)
    _verify_signature(notification, secret)
    artifact_id = _verify_reports(client, token, project_id, execution_id)
    _verify_html(config, token, project_id, artifact_id)
    _verify_delivery(client, token, project_id, execution_id)
    return {
        "project_id": project_id,
        "execution_id": execution_id,
        "artifact_id": artifact_id,
    }


def _verify_reports(
    client: APIClient,
    token: str,
    project_id: str,
    execution_id: str,
) -> str:
    listed = client.json(
        "GET",
        f"/projects/{project_id}/reports/executions?status=failed",
        token=token,
    )
    summary = next(item for item in listed["items"] if item["id"] == execution_id)
    if summary["failure_category"] != "http_server" or summary["failed_nodes"] != 1:
        raise RuntimeError(f"report failure classification is incorrect: {summary}")
    detail = client.json(
        "GET",
        f"/projects/{project_id}/reports/executions/{execution_id}",
        token=token,
    )
    api_step = next(node for node in detail["nodes"] if node["node_type"] == "api")
    if api_step["response"]["status_code"] != 500:
        raise RuntimeError("step report response was not retained")
    trend = client.json("GET", f"/projects/{project_id}/reports/trends?days=7", token=token)
    if trend["points"][-1]["failed"] < 1:
        raise RuntimeError("report trend did not aggregate the failed execution")
    exported = client.json(
        "POST",
        f"/projects/{project_id}/reports/executions/{execution_id}/exports/html",
        token=token,
    )
    if exported["purpose"] != "report" or not exported["filename"].endswith(".html"):
        raise RuntimeError("HTML report artifact metadata is invalid")
    return str(exported["id"])


def _wait_for_notification(execution_id: str) -> dict[str, Any]:
    public_target = os.getenv("FLOWTEST_SMOKE_TARGET_PUBLIC_URL", "http://localhost:8080")
    for _attempt in range(100):
        try:
            with urlopen(f"{public_target}/notifications/last", timeout=5) as response:
                notification = cast(dict[str, Any], json.loads(response.read()))
        except HTTPError as error:
            if error.code == 404:
                time.sleep(0.05)
                continue
            raise
        if notification.get("body", {}).get("resource_id") == execution_id:
            return notification
        time.sleep(0.05)
    raise RuntimeError("signed workflow notification was not delivered")


def _verify_signature(notification: dict[str, Any], secret: str) -> None:
    timestamp = str(notification["timestamp"])
    body = json.dumps(notification["body"], sort_keys=True, separators=(",", ":")).encode()
    expected = (
        "sha256="
        + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    )
    if notification["event"] != "workflow.completed" or not hmac.compare_digest(
        str(notification["signature"]), expected
    ):
        raise RuntimeError("notification signature verification failed")


def _verify_html(
    config: SmokeConfig,
    token: str,
    project_id: str,
    artifact_id: str,
) -> None:
    request = Request(
        f"{config.api_url}/projects/{project_id}/files/{artifact_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urlopen(request, timeout=10) as response:
        content = response.read().decode()
    if "FlowTest 测试报告" not in content or "failed" not in content:
        raise RuntimeError("downloaded HTML report is incomplete")


def _verify_delivery(client: APIClient, token: str, project_id: str, execution_id: str) -> None:
    deliveries = client.json("GET", f"/projects/{project_id}/notification-deliveries", token=token)
    delivery = next(item for item in deliveries["items"] if item["resource_id"] == execution_id)
    if delivery["status"] != "delivered" or delivery["response_status"] != 204:
        raise RuntimeError(f"notification delivery history is incomplete: {delivery}")


if __name__ == "__main__":
    main()
