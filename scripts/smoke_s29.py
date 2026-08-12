#!/usr/bin/env python3
"""Run the S29 Worker lease, fencing, recovery, and drain acceptance flow."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import time
from typing import Any, cast

from smoke_s4 import APIClient, SmokeConfig, _change_password

RUNNER_SERVICES = ("runner-agent-a", "runner-agent-b")


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json("POST", "/auth/login", {"email": config.email, "password": config.password})
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(cast(dict[str, Any], login["user"])["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-S29-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    try:
        result = _run_acceptance(client, token)
        print(json.dumps({"status": "passed", **result}, sort_keys=True))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


def _run_acceptance(client: APIClient, token: str) -> dict[str, Any]:
    features = client.json("GET", "/v3/features", token=token)
    if not features.get("runner_fabric"):
        raise RuntimeError(f"S29 runner fabric is not enabled: {features}")
    _compose("stop", *RUNNER_SERVICES)
    nonce = secrets.token_hex(5)
    pool = client.json(
        "POST",
        "/execution-fabric/pools",
        {
            "name": f"S29 Compose Recovery {nonce}",
            "runner_type": "general",
            "runtime": "docker",
            "network_zone": "compose",
            "labels": ["arm64"],
            "capabilities": ["flow.workflow"],
            "max_concurrency": 4,
            "lease_timeout_seconds": 10,
            "heartbeat_timeout_seconds": 15,
        },
        token=token,
    )
    runner_a = _register_runner(client, token, str(pool["id"]), f"s29-a-{nonce}")
    runner_b = _register_runner(client, token, str(pool["id"]), f"s29-b-{nonce}")
    runner_environment = _runner_environment(runner_a, runner_b, nonce=nonce, concurrency=2)
    _compose("up", "-d", "--force-recreate", "runner-agent-a", environment=runner_environment)

    project_id, environment_id, workflow_id = _create_fixture(client, token, nonce)
    execution = client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/executions",
        {"environment_id": environment_id},
        token=token,
    )
    execution_id = str(execution["id"])
    first_task = _wait_for_task(client, token, execution_id, status="leased", timeout_seconds=20)
    if str(first_task["selected_runner_id"]) != str(runner_a["runner_id"]):
        raise RuntimeError(f"S29 recovery fixture was not leased by Worker A: {first_task}")

    _compose("stop", "runner-agent-a")
    time.sleep(11)
    _compose("up", "-d", "--force-recreate", "runner-agent-b", environment=runner_environment)
    detail = _wait_for_execution(client, token, project_id, execution_id, timeout_seconds=90)
    task = _wait_for_task(client, token, execution_id, status="completed", timeout_seconds=10)
    if int(task["attempts"]) != 2 or int(task["fencing_token"]) != 2:
        raise RuntimeError(f"S29 failover did not advance the attempt and fence: {task}")
    if str(task["selected_runner_id"]) != str(runner_b["runner_id"]):
        raise RuntimeError(f"S29 failover was not completed by Worker B: {task}")
    _verify_terminal_detail(detail)
    _verify_lease_evidence(client, token, str(task["id"]))

    _compose("start", "runner-agent-a")
    _wait_for_runner_status(client, token, str(runner_a["runner_id"]), "online")
    drained = client.json(
        "POST",
        f"/execution-fabric/runners/{runner_b['runner_id']}/actions",
        {"action": "drain"},
        token=token,
    )
    if drained["status"] != "draining":
        raise RuntimeError(f"S29 Worker B did not enter drain: {drained}")
    overview = client.json("GET", "/execution-fabric/overview", token=token)
    if int(overview["active_leases"]) != 0 or int(overview["runners_draining"]) < 1:
        raise RuntimeError(f"S29 final execution fabric state is inconsistent: {overview}")
    return {
        "project_id": project_id,
        "execution_id": execution_id,
        "task_id": str(task["id"]),
        "attempts": int(task["attempts"]),
        "fencing_token": int(task["fencing_token"]),
        "node_terminal_count": len(cast(list[dict[str, Any]], detail["nodes"])),
    }


def _register_runner(
    client: APIClient, token: str, pool_id: str, instance_id: str
) -> dict[str, Any]:
    registration = client.json(
        "POST",
        f"/execution-fabric/pools/{pool_id}/registration-tokens",
        {"expires_in_seconds": 300},
        token=token,
    )
    return client.json(
        "POST",
        "/runner-control/register",
        {
            "name": instance_id,
            "instance_id": f"{instance_id}-compose-identity",
            "runtime": "docker",
            "agent_version": "3.0.0-beta.3",
            "architecture": "arm64",
            "labels": ["arm64"],
            "capabilities": ["flow.workflow"],
            "max_concurrency": 2,
        },
        token=str(registration["token"]),
    )


def _runner_environment(
    runner_a: dict[str, Any], runner_b: dict[str, Any], *, nonce: str, concurrency: int
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "FLOWTEST_RUNNER_A_TOKEN": str(runner_a["token"]),
            "FLOWTEST_RUNNER_B_TOKEN": str(runner_b["token"]),
            "FLOWTEST_RUNNER_A_INSTANCE_ID": f"s29-compose-a-{nonce}",
            "FLOWTEST_RUNNER_B_INSTANCE_ID": f"s29-compose-b-{nonce}",
            "FLOWTEST_RUNNER_CONCURRENCY": str(concurrency),
        }
    )
    return environment


def _create_fixture(client: APIClient, token: str, nonce: str) -> tuple[str, str, str]:
    project = client.json(
        "POST",
        "/projects",
        {"name": f"S29 Recovery {nonce}", "description": "Worker fencing acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    client.json(
        "PUT",
        f"/projects/{project_id}/capacity-policy",
        {"execution_concurrency_limit": 4, "queued_run_limit": 100},
        token=token,
    )
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": "S29 Controlled Runtime", "base_url": "http://mock-target:8080"},
        token=token,
    )
    workflow = client.json(
        "POST",
        f"/projects/{project_id}/workflows",
        {
            "name": "S29 Worker 故障转移流程",
            "description": "Worker A 中断后由 Worker B 接管",
            "definition": _delay_workflow_definition(),
        },
        token=token,
    )
    workflow_id = str(workflow["id"])
    client.json("POST", f"/projects/{project_id}/workflows/{workflow_id}/versions", token=token)
    return project_id, str(environment["id"]), workflow_id


def _delay_workflow_definition() -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "nodes": [
            _node("start", "start", "开始", 0, {}),
            _node("delay", "delay", "受控长任务", 220, {"seconds": 20}),
            _node("end", "end", "结束", 440, {}),
        ],
        "edges": [
            {"id": "start-delay", "source": "start", "target": "delay"},
            {"id": "delay-end", "source": "delay", "target": "end"},
        ],
        "settings": {
            "fail_fast": True,
            "concurrency": 2,
            "default_timeout_seconds": 30,
        },
    }


def _node(
    node_id: str, node_type: str, name: str, x: int, config: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "name": name,
        "position": {"x": x, "y": 100},
        "config": config,
    }


def _wait_for_task(
    client: APIClient,
    token: str,
    execution_id: str,
    *,
    status: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        tasks = cast(
            list[dict[str, Any]],
            client.json("GET", "/execution-fabric/tasks?limit=100", token=token)["items"],
        )
        selected = next((item for item in tasks if str(item["execution_id"]) == execution_id), None)
        if selected is not None and selected["status"] == status:
            return selected
        time.sleep(0.25)
    raise TimeoutError(f"S29 task {execution_id} did not reach {status}")


def _wait_for_execution(
    client: APIClient,
    token: str,
    project_id: str,
    execution_id: str,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        detail = client.json(
            "GET",
            f"/projects/{project_id}/workflow-executions/{execution_id}",
            token=token,
        )
        status = str(cast(dict[str, Any], detail["execution"])["status"])
        if status not in {"queued", "running"}:
            if status != "passed":
                raise RuntimeError(f"S29 recovered execution failed: {detail}")
            return detail
        time.sleep(0.5)
    raise TimeoutError(f"S29 execution {execution_id} did not complete")


def _verify_terminal_detail(detail: dict[str, Any]) -> None:
    items = cast(list[dict[str, Any]], detail["nodes"])
    node_ids = [str(item["node_id"]) for item in items]
    if len(items) != 3 or len(set(node_ids)) != 3:
        raise RuntimeError(f"S29 execution contains duplicate terminal nodes: {items}")
    if {str(item["status"]) for item in items} != {"passed"}:
        raise RuntimeError(f"S29 execution nodes are not uniquely passed: {items}")


def _verify_lease_evidence(client: APIClient, token: str, task_id: str) -> None:
    leases = cast(
        list[dict[str, Any]],
        client.json("GET", "/execution-fabric/leases?limit=100", token=token)["items"],
    )
    selected = [item for item in leases if str(item["task_id"]) == task_id]
    evidence = {(str(item["status"]), int(item["fencing_token"])) for item in selected}
    if evidence != {("expired", 1), ("completed", 2)}:
        raise RuntimeError(f"S29 lease evidence is incomplete: {selected}")


def _wait_for_runner_status(client: APIClient, token: str, runner_id: str, expected: str) -> None:
    for _attempt in range(80):
        pools = cast(
            list[dict[str, Any]],
            client.json("GET", "/execution-fabric/pools", token=token)["items"],
        )
        runners = [
            runner for pool in pools for runner in cast(list[dict[str, Any]], pool["runners"])
        ]
        selected = next((runner for runner in runners if str(runner["id"]) == runner_id), None)
        if selected is not None and selected["status"] == expected:
            return
        time.sleep(0.25)
    raise TimeoutError(f"S29 runner {runner_id} did not reach {expected}")


def _compose(*arguments: str, environment: dict[str, str] | None = None) -> None:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker executable is required for the S29 recovery gate")
    subprocess.run(  # noqa: S603 -- executable and arguments are locally allowlisted.
        [docker, "compose", "--profile", "runner-fabric", *arguments],
        check=True,
        env=environment,
    )


if __name__ == "__main__":
    main()
