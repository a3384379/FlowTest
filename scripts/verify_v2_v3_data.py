#!/usr/bin/env python3
"""Verify that V2 assets remain executable across a V3 upgrade rehearsal."""

from __future__ import annotations

import argparse
import json
import secrets
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from smoke_s4 import APIClient, SmokeConfig

TERMINAL_STATUSES = {"passed", "failed", "cancelled", "timeout"}


@dataclass(slots=True)
class VerificationState:
    project_id: str
    successful_execution_id: str
    release_policy_id: str | None = None

    @classmethod
    def load(cls, path: Path) -> VerificationState:
        document = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            project_id=str(document["project_id"]),
            successful_execution_id=str(document["successful_execution_id"]),
            release_policy_id=(
                str(document["release_policy_id"])
                if document.get("release_policy_id") is not None
                else None
            ),
        )

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    initialize = subparsers.add_parser("initialize")
    initialize.add_argument("--smoke-output", type=Path, required=True)
    initialize.add_argument("--state", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--state", type=Path, required=True)
    verify.add_argument(
        "--phase",
        choices=("v3-upgrade", "v2-rollback", "v3-reupgrade"),
        required=True,
    )
    arguments = parser.parse_args()
    if arguments.action == "initialize":
        _initialize(arguments.smoke_output, arguments.state)
        return
    _verify(arguments.state, arguments.phase)


def _initialize(smoke_output: Path, state_path: Path) -> None:
    documents = [line for line in smoke_output.read_text(encoding="utf-8").splitlines() if line]
    if not documents:
        raise RuntimeError("V2 smoke output is empty")
    result = json.loads(documents[-1])
    if result.get("status") != "passed":
        raise RuntimeError("V2 smoke did not finish successfully")
    state = VerificationState(
        project_id=str(result["project_id"]),
        successful_execution_id=str(result["successful_execution_id"]),
    )
    state.save(state_path)
    print(json.dumps({"status": "initialized", "project_id": state.project_id}))


def _verify(state_path: Path, phase: str) -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json(
        "POST",
        "/auth/login",
        {"email": config.email, "password": config.password},
    )
    token = str(login["access_token"])
    state = VerificationState.load(state_path)
    try:
        workflow_id, environment_id = _verify_assets(client, token, state)
        execution_id = _execute(client, token, state.project_id, workflow_id, environment_id)
        _verify_execution(client, token, state.project_id, execution_id)
        if phase == "v3-upgrade":
            state.release_policy_id = _create_v3_marker(client, token, state.project_id)
            state.save(state_path)
        elif phase == "v3-reupgrade":
            _verify_v3_marker_was_rolled_back(client, token, state)
        print(
            json.dumps(
                {
                    "status": "passed",
                    "phase": phase,
                    "project_id": state.project_id,
                    "new_execution_id": execution_id,
                }
            )
        )
    finally:
        client.json("POST", "/auth/logout", token=token)


def _verify_assets(
    client: APIClient,
    token: str,
    state: VerificationState,
) -> tuple[str, str]:
    project = client.json("GET", f"/projects/{state.project_id}", token=token)
    if not str(project["name"]).startswith("S11 V1 Pilot"):
        raise RuntimeError("V2 project identity was not preserved")
    _require_named_item(
        client.json(
            "GET",
            f"/projects/{state.project_id}/apis?page=1&page_size=100",
            token=token,
        ),
        "业务登录",
        "API",
    )
    workflow = _require_named_item(
        client.json(
            "GET",
            f"/projects/{state.project_id}/workflows?page=1&page_size=100",
            token=token,
        ),
        "V1 登录下单流程",
        "workflow",
    )
    environment = _require_named_item(
        client.json("GET", f"/projects/{state.project_id}/environments", token=token),
        "V1 Mock Business",
        "environment",
    )
    _verify_execution(client, token, state.project_id, state.successful_execution_id)
    return str(workflow["id"]), str(environment["id"])


def _require_named_item(
    document: dict[str, Any] | list[dict[str, Any]],
    name: str,
    kind: str,
) -> dict[str, Any]:
    raw_items = document if isinstance(document, list) else document.get("items")
    if not isinstance(raw_items, list):
        raise TypeError(f"{kind} collection is invalid")
    for raw_item in raw_items:
        if isinstance(raw_item, dict) and raw_item.get("name") == name:
            return cast(dict[str, Any], raw_item)
    raise RuntimeError(f"V2 {kind} was not preserved: {name}")


def _execute(
    client: APIClient,
    token: str,
    project_id: str,
    workflow_id: str,
    environment_id: str,
) -> str:
    execution = client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/executions",
        {
            "environment_id": environment_id,
            "runtime_variables": {},
            "runtime_headers": {},
        },
        token=token,
        extra_headers={"Idempotency-Key": f"upgrade-{uuid.uuid4()}"},
    )
    return str(execution["id"])


def _verify_execution(
    client: APIClient,
    token: str,
    project_id: str,
    execution_id: str,
) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        execution = client.json(
            "GET",
            f"/projects/{project_id}/workflow-executions/{execution_id}",
            token=token,
        )
        status = str(execution["execution"]["status"])
        if status in TERMINAL_STATUSES:
            break
        time.sleep(1)
    else:
        raise RuntimeError(f"workflow execution did not finish: {execution_id}")
    if status != "passed":
        raise RuntimeError(
            f"workflow execution was not preserved as passed: {execution_id}={status}"
        )
    report = client.json(
        "GET",
        f"/projects/{project_id}/reports/executions/{execution_id}",
        token=token,
    )
    if report.get("summary", {}).get("status") != "passed":
        raise RuntimeError(f"workflow report was not preserved as passed: {execution_id}")


def _create_v3_marker(client: APIClient, token: str, project_id: str) -> str:
    policy = client.json(
        "POST",
        f"/projects/{project_id}/release-policies",
        {
            "name": f"V3 rollback marker {secrets.token_hex(4)}",
            "enabled": True,
            "quality_gate_id": None,
            "require_quality_gate": False,
            "require_contract_compatibility": False,
            "require_impact_evidence": False,
            "min_impact_coverage_percent": 80,
            "require_release_risk": False,
            "max_release_risk_score": 50,
            "require_performance_evidence": False,
            "require_runner_evidence": False,
        },
        token=token,
    )
    return str(policy["id"])


def _verify_v3_marker_was_rolled_back(
    client: APIClient,
    token: str,
    state: VerificationState,
) -> None:
    if state.release_policy_id is None:
        raise RuntimeError("V3 rollback marker was not recorded")
    policies = client.json(
        "GET",
        f"/projects/{state.project_id}/release-policies?page=1&page_size=100",
        token=token,
    )
    raw_items = policies if isinstance(policies, list) else policies.get("items")
    if not isinstance(raw_items, list):
        raise TypeError("release policy collection is invalid")
    if any(
        isinstance(item, dict) and str(item.get("id")) == state.release_policy_id
        for item in raw_items
    ):
        raise RuntimeError("V3-only release policy survived a destructive V3-to-V2 downgrade")


if __name__ == "__main__":
    main()
