#!/usr/bin/env python3
"""Run the S21 redacted AI queue and human review acceptance flow."""

from __future__ import annotations

import json
import secrets
import time
from typing import Any, cast

from smoke_s4 import APIClient, SmokeConfig, _change_password


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json("POST", "/auth/login", {"email": config.email, "password": config.password})
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(cast(dict[str, Any], login["user"])["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-S21-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    try:
        result = _run_acceptance(client, token)
        print(json.dumps({"status": "passed", **result}))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


def _run_acceptance(client: APIClient, token: str) -> dict[str, str]:
    project = client.json(
        "POST",
        "/projects",
        {"name": f"S21 AI {secrets.token_hex(5)}", "description": "S21 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    status_response = client.json("GET", f"/ai/status?project_id={project_id}", token=token)
    if status_response["enabled"] is not True or not status_response["model"]:
        raise RuntimeError("AI feature is not enabled for the S21 acceptance stack")
    client.json(
        "PUT",
        f"/ai/projects/{project_id}/settings",
        {"sample_sharing_enabled": True},
        token=token,
    )
    job = client.json(
        "POST",
        "/ai/jobs",
        {
            "project_id": project_id,
            "job_type": "workflow_draft",
            "schema_document": {"openapi": "3.1.0", "paths": {}},
            "metadata": {
                "Authorization": "Bearer must-not-reach-ai",
                "operation": "GET /users",
            },
            "sample": {"password": "sample-must-not-reach-ai", "safe": "visible"},
        },
        token=token,
    )
    completed = _wait_for_job(client, token, str(job["id"]))
    if completed["status"] != "completed" or completed["token_usage"]["total_tokens"] != 30:
        raise RuntimeError(f"AI job did not complete safely: {completed}")
    workflows_before = client.json(
        "GET", f"/projects/{project_id}/workflows?page=1&page_size=100", token=token
    )
    if workflows_before["total"] != 0:
        raise RuntimeError("AI created a Workflow before human acceptance")
    suggestions = cast(
        list[dict[str, Any]],
        client.json("GET", f"/ai/jobs/{job['id']}/suggestions", token=token),
    )
    if len(suggestions) != 1 or suggestions[0]["review_status"] != "pending":
        raise RuntimeError("AI suggestion was not held for review")
    accepted = client.json(
        "POST",
        f"/ai/suggestions/{suggestions[0]['id']}/accept",
        {"note": "Compose 人工确认"},
        token=token,
    )
    if accepted["accepted_resource_type"] != "workflow" or not accepted["accepted_resource_id"]:
        raise RuntimeError("accepted AI suggestion did not create a Workflow draft")
    workflows_after = client.json(
        "GET", f"/projects/{project_id}/workflows?page=1&page_size=100", token=token
    )
    workflow_items = cast(list[dict[str, Any]], workflows_after["items"])
    if workflows_after["total"] != 1 or workflow_items[0]["current_version"] is not None:
        raise RuntimeError("accepted AI Workflow was not created as an unpublished draft")
    return {
        "project_id": project_id,
        "ai_job_id": str(job["id"]),
        "workflow_id": str(accepted["accepted_resource_id"]),
    }


def _wait_for_job(client: APIClient, token: str, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.json("GET", f"/ai/jobs/{job_id}", token=token)
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.25)
    raise RuntimeError(f"AI job did not reach a terminal state: {job_id}")


if __name__ == "__main__":
    main()
