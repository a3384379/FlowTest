#!/usr/bin/env python3
"""Run the S25 declarative performance, baseline, artifact, and gate acceptance flow."""

from __future__ import annotations

import json
import secrets
import time
from typing import Any, cast

from smoke_s4 import APIClient, SmokeConfig, _allow_compose_target, _change_password


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json("POST", "/auth/login", {"email": config.email, "password": config.password})
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(cast(dict[str, Any], login["user"])["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-S25-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    try:
        result = _run_acceptance(client, config, token)
        print(json.dumps({"status": "passed", **result}))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


def _run_acceptance(client: APIClient, config: SmokeConfig, token: str) -> dict[str, str]:
    features = client.json("GET", "/v3/features", token=token)
    if not features.get("performance_lab"):
        raise RuntimeError("S25 performance feature is not enabled")
    project = client.json(
        "POST",
        "/projects",
        {"name": f"S25 Performance {secrets.token_hex(5)}", "description": "S25 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    _allow_compose_target(client, token, project_id, config.target_url)
    _create_gate(client, token, project_id)
    scenario = client.json(
        "POST",
        f"/projects/{project_id}/performance-scenarios",
        {
            "name": "Mock 健康检查性能基线",
            "description": "平台编译的短时 Compose 验收场景",
            "definition": _definition(f"{config.target_url.rstrip('/')}/health"),
        },
        token=token,
    )
    scenario_id = str(scenario["id"])
    if scenario["status"] != "draft" or scenario["target_type"] != "rest":
        raise RuntimeError("S25 scenario was not created as a REST draft")
    published = client.json(
        "POST",
        f"/projects/{project_id}/performance-scenarios/{scenario_id}/publish",
        token=token,
    )
    if published["status"] != "published" or not published["compiled_sha256"]:
        raise RuntimeError("S25 scenario was not compiled into an immutable release")

    first = _run_and_wait(client, token, project_id, scenario_id)
    if first["status"] != "passed":
        raise RuntimeError(f"S25 first performance run failed: {first}")
    if not first["threshold_results"] or not first["raw_metrics_artifact_id"]:
        raise RuntimeError("S25 threshold evidence or MinIO raw metrics artifact is missing")
    if first["gate_evaluations"][0]["status"] != "passed":
        raise RuntimeError("S25 performance result did not enter the Quality Gate")

    second = _run_and_wait(client, token, project_id, scenario_id)
    if second["status"] != "passed" or second["baseline_run_id"] != first["id"]:
        raise RuntimeError("S25 regression run did not pin the previous successful baseline")
    return {
        "project_id": project_id,
        "scenario_id": scenario_id,
        "first_run_id": str(first["id"]),
        "second_run_id": str(second["id"]),
    }


def _definition(url: str) -> dict[str, Any]:
    return {
        "executor": "constant_vus",
        "steps": [
            {
                "name": "健康检查",
                "method": "GET",
                "url": url,
                "headers": {"Accept": "application/json"},
                "body": None,
                "expected_statuses": [200],
                "pause_seconds": 0,
            }
        ],
        "thresholds": [
            {
                "metric": "http_req_duration",
                "aggregation": "p(95)",
                "operator": "<",
                "value": 5000,
                "abort_on_fail": False,
                "delay_abort_seconds": 0,
            },
            {
                "metric": "http_req_failed",
                "aggregation": "rate",
                "operator": "<=",
                "value": 0,
                "abort_on_fail": False,
                "delay_abort_seconds": 0,
            },
        ],
        "vus": 1,
        "duration_seconds": 1,
        "start_vus": None,
        "stages": [],
        "graceful_stop_seconds": 1,
    }


def _create_gate(client: APIClient, token: str, project_id: str) -> None:
    client.json(
        "POST",
        f"/projects/{project_id}/quality-gates",
        {
            "name": "S25 Performance Gate",
            "min_pass_rate": 0,
            "max_failed": 100,
            "max_flaky": 100,
            "max_duration_regression_percent": 1000,
            "require_no_breaking_changes": False,
        },
        token=token,
    )


def _run_and_wait(
    client: APIClient,
    token: str,
    project_id: str,
    scenario_id: str,
) -> dict[str, Any]:
    queued = client.json(
        "POST",
        f"/projects/{project_id}/performance-scenarios/{scenario_id}/runs",
        token=token,
    )
    run_id = str(queued["id"])
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        detail = client.json(
            "GET",
            f"/projects/{project_id}/performance-runs/{run_id}",
            token=token,
        )
        if detail["status"] in {"passed", "failed", "cancelled"}:
            return detail
        time.sleep(1)
    raise RuntimeError(f"S25 performance run {run_id} did not finish in 120 seconds")


if __name__ == "__main__":
    main()
