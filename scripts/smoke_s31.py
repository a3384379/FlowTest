#!/usr/bin/env python3
"""Run the S31 global search and immutable release decision acceptance flow."""

from __future__ import annotations

import json
import secrets
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
        active_password = f"FlowTest-S31-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    try:
        result = _run_acceptance(client, token)
        print(json.dumps({"status": "passed", **result}, sort_keys=True))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


def _run_acceptance(client: APIClient, token: str) -> dict[str, str]:
    marker = secrets.token_hex(5)
    project = client.json(
        "POST",
        "/projects",
        {"name": f"S31 Release {marker}", "description": "S31 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    permissive = client.json(
        "POST",
        f"/projects/{project_id}/release-policies",
        _policy(f"S31 Immutable {marker}", required=False),
        token=token,
    )
    passed = client.json(
        "POST",
        f"/projects/{project_id}/release-decisions",
        {"release_policy_id": permissive["id"], "candidate_ref": "v3.0.0-rc.compose"},
        token=token,
    )
    _verify_decision(passed, expected_status="pass")
    frozen_policy = passed["policy_snapshot"]
    fingerprint = str(passed["fingerprint"])
    client.json(
        "PUT",
        f"/projects/{project_id}/release-policies/{permissive['id']}",
        {**_policy(f"S31 Immutable {marker}", required=False), "max_release_risk_score": 1},
        token=token,
    )
    historical = client.json(
        "GET",
        f"/projects/{project_id}/release-decisions/{passed['id']}",
        token=token,
    )
    if historical["policy_snapshot"] != frozen_policy or historical["fingerprint"] != fingerprint:
        raise RuntimeError("S31 policy update changed an immutable release decision")
    quality_gate = client.json(
        "POST",
        f"/projects/{project_id}/quality-gates",
        {
            "name": f"S31 Strict Quality {marker}",
            "enabled": True,
            "min_pass_rate": 100,
            "max_failed": 0,
            "max_flaky": 0,
            "max_duration_regression_percent": 10,
            "require_no_breaking_changes": True,
        },
        token=token,
    )
    strict_payload = _policy(f"S31 Strict {marker}", required=True)
    strict_payload["quality_gate_id"] = quality_gate["id"]
    strict = client.json(
        "POST", f"/projects/{project_id}/release-policies", strict_payload, token=token
    )
    blocked = client.json(
        "POST",
        f"/projects/{project_id}/release-decisions",
        {"release_policy_id": strict["id"], "candidate_ref": "v3.0.0-rc.missing-evidence"},
        token=token,
    )
    _verify_decision(blocked, expected_status="block")
    search = client.json("GET", f"/search?q=S31%20Immutable%20{marker}", token=token)
    items = cast(list[dict[str, Any]], search["items"])
    if not any(item["resource_id"] == permissive["id"] for item in items):
        raise RuntimeError(f"S31 release policy was not returned by global search: {search}")
    _verify_decision_mutation_is_unavailable(client, token, project_id, str(passed["id"]))
    return {
        "project_id": project_id,
        "pass_decision_id": str(passed["id"]),
        "block_decision_id": str(blocked["id"]),
    }


def _policy(name: str, *, required: bool) -> dict[str, Any]:
    return {
        "name": name,
        "enabled": True,
        "quality_gate_id": None,
        "require_quality_gate": required,
        "require_contract_compatibility": required,
        "require_impact_evidence": required,
        "min_impact_coverage_percent": 80,
        "require_release_risk": required,
        "max_release_risk_score": 50,
        "require_performance_evidence": required,
        "require_runner_evidence": required,
    }


def _verify_decision(decision: dict[str, Any], *, expected_status: str) -> None:
    reasons = cast(list[dict[str, Any]], decision["reasons"])
    if decision["status"] != expected_status or len(reasons) != 6:
        raise RuntimeError(f"S31 release decision is incomplete: {decision}")
    if not decision["fingerprint"] or not decision["policy_snapshot"]:
        raise RuntimeError(f"S31 release decision did not freeze evidence: {decision}")
    blocked = [reason for reason in reasons if reason["status"] == "blocked"]
    if (expected_status == "block") != bool(blocked):
        raise RuntimeError(f"S31 release decision reasons do not explain its status: {decision}")


def _verify_decision_mutation_is_unavailable(
    client: APIClient, token: str, project_id: str, decision_id: str
) -> None:
    try:
        client.json(
            "PUT",
            f"/projects/{project_id}/release-decisions/{decision_id}",
            {"candidate_ref": "tampered"},
            token=token,
        )
    except RuntimeError as error:
        if "405" in str(error):
            return
        raise
    raise RuntimeError("S31 immutable release decision exposed a mutation endpoint")


if __name__ == "__main__":
    main()
