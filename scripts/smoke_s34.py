#!/usr/bin/env python3
"""Verify bidirectional asset compatibility between Full and Compact profiles."""

from __future__ import annotations

import argparse
import json
import secrets
from typing import Any

from smoke_s4 import APIClient, SmokeConfig, _change_password
from smoke_s32 import ARTIFACT_CONTENT, _run_acceptance


def _runtime_contract(profile: str) -> dict[str, Any]:
    if profile == "compact":
        return {
            "profile": "compact",
            "worker_topology": "consolidated",
            "unavailable_features": ["performance_lab", "environment_lab"],
        }
    return {
        "profile": "full",
        "worker_topology": "isolated",
        "unavailable_features": [],
    }


def _authenticate(config: SmokeConfig) -> tuple[APIClient, str, str, bool]:
    client = APIClient(config.api_url)
    login = client.json("POST", "/auth/login", {"email": config.email, "password": config.password})
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(login["user"]["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-S34-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    return client, token, active_password, password_changed


def _verify_existing_assets(
    client: APIClient,
    token: str,
    *,
    project_id: str,
    artifact_id: str,
    execution_id: str,
) -> None:
    content = client.download(f"/projects/{project_id}/files/{artifact_id}", token=token)
    if content != ARTIFACT_CONTENT:
        raise RuntimeError("profile switch changed Artifact content")
    execution = client.json(
        "GET",
        f"/projects/{project_id}/workflow-executions/{execution_id}",
        token=token,
    )
    if execution["execution"]["status"] != "passed":
        raise RuntimeError("profile switch changed Workflow execution state")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "verify"))
    parser.add_argument("--profile", choices=("full", "compact"), required=True)
    parser.add_argument("--project-id")
    parser.add_argument("--artifact-id")
    parser.add_argument("--execution-id")
    args = parser.parse_args()
    if args.action == "verify" and not all((args.project_id, args.artifact_id, args.execution_id)):
        parser.error("verify requires project, artifact, and execution IDs")

    config = SmokeConfig.from_environment()
    client, token, active_password, password_changed = _authenticate(config)
    try:
        runtime_contract = _runtime_contract(args.profile)
        runtime = client.json("GET", "/runtime-profile")
        if runtime != runtime_contract:
            raise RuntimeError(f"unexpected runtime contract: {runtime}")
        if args.action == "create":
            result = _run_acceptance(
                client,
                config,
                token,
                expected_runtime=runtime_contract,
            )
        else:
            _verify_existing_assets(
                client,
                token,
                project_id=str(args.project_id),
                artifact_id=str(args.artifact_id),
                execution_id=str(args.execution_id),
            )
            result = {
                "project_id": str(args.project_id),
                "artifact_id": str(args.artifact_id),
                "workflow_execution_id": str(args.execution_id),
            }
        print(json.dumps({"status": "passed", "profile": args.profile, **result}))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


if __name__ == "__main__":
    main()
