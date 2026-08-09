#!/usr/bin/env python3
"""Run the S8 worker, test-plan, CI token, webhook, and cancellation acceptance flow."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any, cast
from urllib.request import Request, urlopen

from smoke_s4 import APIClient, SmokeConfig, _allow_compose_target, _change_password
from smoke_s5 import _create_workflow, _wait_for_completion


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
        {"name": f"S8 Smoke {secrets.token_hex(5)}", "description": "S8 acceptance"},
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
    environment_id = str(environment["id"])
    fast_workflow_id = _published_workflow(
        client, token, project_id, name="Worker 健康流程", path="/health"
    )
    slow_workflow_id = _published_workflow(
        client, token, project_id, name="Worker 慢速流程", path="/slow?seconds=2"
    )
    plan = client.json(
        "POST",
        f"/projects/{project_id}/test-plans",
        {
            "name": "S8 批量回归",
            "description": "Worker and external trigger acceptance",
            "enabled": True,
            "schedule_interval_seconds": 60,
            "items": [
                {"workflow_id": fast_workflow_id, "environment_id": environment_id},
                {"workflow_id": slow_workflow_id, "environment_id": environment_id},
            ],
        },
        token=token,
    )
    if not plan.get("next_run_at") or len(plan["items"]) != 2:
        raise RuntimeError("scheduled batch test plan was not persisted")
    service_token = client.json(
        "POST",
        f"/projects/{project_id}/service-tokens",
        {
            "name": "S8 CI",
            "scopes": ["execute:workflow", "execute:test-plan"],
        },
        token=token,
    )
    ci_token = str(service_token["token"])
    direct = client.json(
        "POST",
        f"/ci/projects/{project_id}/workflows/{fast_workflow_id}/executions",
        {"environment_id": environment_id},
        token=ci_token,
    )
    direct_detail = _wait_for_completion(client, token, project_id, str(direct["id"]))
    if direct_detail["execution"]["status"] != "passed":
        raise RuntimeError("CI workflow did not execute in Celery Worker")

    queued = client.json(
        "POST",
        f"/ci/projects/{project_id}/test-plans/{plan['id']}/runs",
        token=ci_token,
    )
    completed = _wait_for_plan_run(client, token, project_id, str(queued["id"]))
    if completed["run"]["status"] != "passed":
        raise RuntimeError(f"batch plan did not pass: {completed}")
    if {item["status"] for item in completed["items"]} != {"passed"}:
        raise RuntimeError("batch plan items did not all pass")

    webhook_run = _trigger_webhook(
        config,
        plan_id=str(plan["id"]),
        webhook_secret=str(plan["webhook_secret"]),
    )
    client.json(
        "POST",
        f"/projects/{project_id}/test-plan-runs/{webhook_run['id']}/cancel",
        token=token,
    )
    cancelled = _wait_for_plan_run(client, token, project_id, str(webhook_run["id"]))
    if cancelled["run"]["status"] != "cancelled":
        raise RuntimeError(f"test plan cancellation did not propagate: {cancelled}")
    return {
        "project_id": project_id,
        "ci_execution_id": str(direct["id"]),
        "test_plan_run_id": str(queued["id"]),
        "cancelled_run_id": str(webhook_run["id"]),
    }


def _published_workflow(
    client: APIClient,
    token: str,
    project_id: str,
    *,
    name: str,
    path: str,
) -> str:
    api = client.json(
        "POST",
        f"/projects/{project_id}/apis",
        {
            "name": f"{name} API",
            "request": {"method": "GET", "path": path, "body_kind": "none"},
        },
        token=token,
    )
    workflow = _create_workflow(
        client,
        token,
        project_id,
        name,
        str(api["definition"]["id"]),
    )
    workflow_id = str(workflow["id"])
    client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/versions",
        token=token,
    )
    return workflow_id


def _wait_for_plan_run(
    client: APIClient,
    token: str,
    project_id: str,
    run_id: str,
) -> dict[str, Any]:
    for _attempt in range(300):
        detail = client.json(
            "GET",
            f"/projects/{project_id}/test-plan-runs/{run_id}",
            token=token,
        )
        if detail["run"]["status"] not in {"queued", "running"}:
            return detail
        time.sleep(0.1)
    raise RuntimeError("test plan run did not complete")


def _trigger_webhook(config: SmokeConfig, *, plan_id: str, webhook_secret: str) -> dict[str, Any]:
    body = b'{"source":"compose-smoke"}'
    timestamp = str(int(time.time()))
    message = timestamp.encode() + b"." + body
    signature = "sha256=" + hmac.new(webhook_secret.encode(), message, hashlib.sha256).hexdigest()
    request = Request(
        f"{config.api_url}/webhooks/test-plans/{plan_id}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-FlowTest-Timestamp": timestamp,
            "X-FlowTest-Signature": signature,
        },
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return cast(dict[str, Any], json.loads(response.read()))


if __name__ == "__main__":
    main()
