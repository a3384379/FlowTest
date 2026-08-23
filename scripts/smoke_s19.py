#!/usr/bin/env python3
"""Run the S19 scheduling, Flaky, quality-gate, and JUnit acceptance flow."""

from __future__ import annotations

import json
import secrets
from typing import Any, cast

from smoke_s4 import APIClient, SmokeConfig, _allow_compose_target, _change_password
from smoke_s5 import _create_api, _create_workflow
from smoke_s8 import _wait_for_plan_run


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json("POST", "/auth/login", {"email": config.email, "password": config.password})
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(cast(dict[str, Any], login["user"])["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-S19-{secrets.token_urlsafe(18)}"
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
        {"name": f"S19 Quality {secrets.token_hex(5)}", "description": "S19 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    client.json(
        "PUT",
        f"/projects/{project_id}/capacity-policy",
        {"execution_concurrency_limit": 100, "queued_run_limit": 1200},
        token=token,
    )
    _allow_compose_target(client, token, project_id, config.target_url)
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {
            "name": "S19 Mock",
            "base_url": f"{config.target_url.rstrip('/')}/s19-first-run-failure",
        },
        token=token,
    )
    environment_id = str(environment["id"])
    api = _create_api(client, token, project_id, "S19 Flaky API", "/health")
    api_id = str(cast(dict[str, Any], api["definition"])["id"])
    workflow = _create_workflow(client, token, project_id, "S19 Flaky Workflow", api_id)
    workflow_id = str(workflow["id"])
    client.json("POST", f"/projects/{project_id}/workflows/{workflow_id}/versions", token=token)
    gate = client.json(
        "POST",
        f"/projects/{project_id}/quality-gates",
        {
            "name": "S19 CI Gate",
            "min_pass_rate": 50,
            "max_failed": 1,
            "max_flaky": 0,
            "max_duration_regression_percent": 1000,
            "require_no_breaking_changes": False,
        },
        token=token,
    )
    plan = client.json(
        "POST",
        f"/projects/{project_id}/test-plans",
        {
            "name": "S19 Cron Plan",
            "schedule_cron": "0 9 * * 1-5",
            "schedule_timezone": "Asia/Shanghai",
            "queue_priority": 8,
            "items": [{"workflow_id": workflow_id, "environment_id": environment_id}],
        },
        token=token,
    )
    if plan["queue_priority"] != 8 or not plan["next_run_at"]:
        raise RuntimeError("cron/timezone/priority schedule was not persisted")
    failed = _run_plan(client, token, project_id, str(plan["id"]))
    if failed["run"]["status"] != "failed":
        raise RuntimeError("first quality baseline should fail")
    client.json(
        "PATCH",
        f"/projects/{project_id}/environments/{environment_id}",
        {"base_url": config.target_url},
        token=token,
    )
    passed = _run_plan(client, token, project_id, str(plan["id"]))
    if passed["run"]["status"] != "passed":
        raise RuntimeError("second quality run should pass")
    run_id = str(passed["run"]["id"])
    quality = client.json(
        "GET", f"/projects/{project_id}/test-plan-runs/{run_id}/quality", token=token
    )
    if not quality["baseline_run_id"] or quality["summary"]["flaky"] != 1:
        raise RuntimeError("baseline comparison and deterministic Flaky evidence are incomplete")
    if quality["evaluations"][0]["status"] != "failed":
        raise RuntimeError("quality gate did not reject the Flaky regression")
    records = client.json("GET", f"/projects/{project_id}/flaky-tests", token=token)
    record = cast(dict[str, Any], records["items"][0])
    if float(record["flaky_score"]) <= 0:
        raise RuntimeError("Flaky score was not calculated")
    client.json(
        "PUT",
        f"/projects/{project_id}/flaky-tests/{record['id']}/quarantine",
        {"quarantined": True},
        token=token,
    )
    isolated = _run_plan(client, token, project_id, str(plan["id"]))
    if isolated["items"][0]["status"] != "quarantined":
        raise RuntimeError("quarantined asset was still executed")
    junit = client.download(
        f"/projects/{project_id}/test-plan-runs/{isolated['run']['id']}/junit.xml",
        token=token,
    )
    if b"<testsuite" not in junit or b"<skipped" not in junit:
        raise RuntimeError("JUnit export did not preserve quarantine evidence")
    service_token = client.json(
        "POST",
        f"/projects/{project_id}/service-tokens",
        {"name": "S19 Quality CI", "scopes": ["execute:test-plan"]},
        token=token,
    )
    ci_gate = client.json(
        "GET",
        f"/ci/projects/{project_id}/test-plan-runs/{run_id}/quality-gate"
        f"?quality_gate_id={gate['id']}",
        token=str(service_token["token"]),
    )
    if ci_gate["status"] != "failed":
        raise RuntimeError("CI quality gate result changed from the persisted evaluation")
    return {"project_id": project_id, "test_plan_run_id": run_id, "gate_id": str(gate["id"])}


def _run_plan(client: APIClient, token: str, project_id: str, plan_id: str) -> dict[str, Any]:
    queued = client.json("POST", f"/projects/{project_id}/test-plans/{plan_id}/runs", token=token)
    if queued["queue_name"] != "general" or queued["queue_priority"] != 8:
        raise RuntimeError("test plan was dispatched to the wrong queue or priority")
    return _wait_for_plan_run(client, token, project_id, str(queued["id"]))


if __name__ == "__main__":
    main()
