#!/usr/bin/env python3
"""Run the S30 failure intelligence and AI draft change-set acceptance flow."""

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
        active_password = f"FlowTest-S30-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    try:
        result = _run_acceptance(client, token)
        print(json.dumps({"status": "passed", **result}, sort_keys=True))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


def _run_acceptance(client: APIClient, token: str) -> dict[str, str]:
    features = client.json("GET", "/v3/features", token=token)
    required = ("impact_engine", "quality_intelligence")
    if not all(features.get(feature) for feature in required):
        raise RuntimeError(f"S30 required features are not enabled: {features}")
    project = client.json(
        "POST",
        "/projects",
        {
            "name": f"S30 Intelligence {secrets.token_hex(5)}",
            "description": "S30 acceptance",
        },
        token=token,
    )
    project_id = str(project["id"])
    ai_status = client.json("GET", f"/ai/status?project_id={project_id}", token=token)
    if ai_status["enabled"] is not True or not ai_status["model"]:
        raise RuntimeError(f"S30 AI feature is not enabled: {ai_status}")
    impact = _create_impact(client, token, project_id)
    risk = client.json(
        "POST",
        f"/projects/{project_id}/release-risks",
        {"impact_run_id": impact["id"], "title": "S30 Compose RC", "window_days": 7},
        token=token,
    )
    _verify_risk(risk)
    change_set = client.json(
        "POST",
        "/ai/change-sets",
        {
            "project_id": project_id,
            "impact_run_id": impact["id"],
            "release_risk_id": risk["id"],
            "title": "S30 Compose Draft Change Set",
        },
        token=token,
    )
    detail = _wait_for_change_set(client, token, str(change_set["id"]))
    items = cast(list[dict[str, Any]], detail["items"])
    if detail["status"] != "draft" or len(items) != 1 or items[0]["review_status"] != "pending":
        raise RuntimeError(f"S30 change set was not held for item review: {detail}")
    workflows_before = _workflows(client, token, project_id)
    if workflows_before["total"] != 0:
        raise RuntimeError("AI change set created a Workflow before item acceptance")
    suggestions = cast(
        list[dict[str, Any]],
        client.json("GET", f"/ai/jobs/{change_set['ai_job_id']}/suggestions", token=token),
    )
    _verify_direct_review_is_blocked(client, token, str(suggestions[0]["id"]))
    item = items[0]
    accepted = client.json(
        "POST",
        f"/ai/change-sets/{change_set['id']}/items/{item['id']}/accept",
        {"content": item["proposed_content"], "note": "Compose 逐项人工确认"},
        token=token,
    )
    if accepted["materialized_resource_type"] != "workflow":
        raise RuntimeError(f"S30 accepted item did not create a Workflow draft: {accepted}")
    workflows_after = _workflows(client, token, project_id)
    workflow_items = cast(list[dict[str, Any]], workflows_after["items"])
    if workflows_after["total"] != 1 or workflow_items[0]["current_version"] is not None:
        raise RuntimeError("S30 accepted item was not materialized as one unpublished draft")
    return {
        "project_id": project_id,
        "impact_run_id": str(impact["id"]),
        "release_risk_id": str(risk["id"]),
        "change_set_id": str(change_set["id"]),
        "workflow_id": str(accepted["materialized_resource_id"]),
    }


def _create_impact(client: APIClient, token: str, project_id: str) -> dict[str, Any]:
    return client.json(
        "POST",
        f"/projects/{project_id}/impact/runs",
        {
            "title": "S30 Compose Impact",
            "source_ref": "compose/s30",
            "git_diff": (
                "diff --git a/backend/orders.py b/backend/orders.py\n"
                "--- a/backend/orders.py\n+++ b/backend/orders.py\n"
                "@@ -1 +1 @@\n-old\n+new\n"
            ),
        },
        token=token,
    )


def _verify_risk(risk: dict[str, Any]) -> None:
    factor_score = sum(float(item["score"]) for item in cast(list[dict[str, Any]], risk["factors"]))
    if factor_score != float(risk["score"]):
        raise RuntimeError(f"S30 release risk factors are not explainable: {risk}")
    if not risk["fingerprint"] or "impact" not in risk["evidence_snapshot"]:
        raise RuntimeError(f"S30 release risk did not persist its evidence snapshot: {risk}")


def _verify_direct_review_is_blocked(client: APIClient, token: str, suggestion_id: str) -> None:
    try:
        client.json(
            "POST",
            f"/ai/suggestions/{suggestion_id}/accept",
            {"note": "must use change-set review"},
            token=token,
        )
    except RuntimeError as error:
        if "409" in str(error) and "AI_CHANGE_SET_REVIEW_REQUIRED" in str(error):
            return
        raise
    raise RuntimeError("S30 change-set suggestion bypassed item-level review")


def _wait_for_change_set(client: APIClient, token: str, change_set_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        detail = client.json("GET", f"/ai/change-sets/{change_set_id}", token=token)
        if detail["status"] in {"draft", "failed"}:
            return detail
        time.sleep(0.25)
    raise TimeoutError(f"S30 change set did not finish generating: {change_set_id}")


def _workflows(client: APIClient, token: str, project_id: str) -> dict[str, Any]:
    return client.json("GET", f"/projects/{project_id}/workflows?page=1&page_size=100", token=token)


if __name__ == "__main__":
    main()
