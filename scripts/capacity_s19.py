#!/usr/bin/env python3
"""Verify 1000 durable Test Plan tasks survive a drained multi-worker queue."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import subprocess
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any, cast

import httpx
from smoke_s4 import APIClient, SmokeConfig, _allow_compose_target, _change_password
from smoke_s5 import _create_api, _create_workflow

WORKER_SERVICES = ("worker", "worker-data", "worker-ai")


@dataclass(frozen=True, slots=True)
class QueueCapacityResult:
    queued_tasks: int
    unique_run_ids: int
    terminal_runs: int
    unique_execution_ids: int
    duplicate_terminal_states: int
    failures: int
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class QueueFixture:
    project_id: str
    plan_id: str
    access_token: str
    service_tokens: tuple[str, ...]


async def run_capacity(
    *, api_url: str, fixture: QueueFixture, task_count: int, timeout_seconds: float
) -> QueueCapacityResult:
    _compose("stop", *WORKER_SERVICES)
    started_at = perf_counter()
    try:
        run_ids = await _enqueue_runs(api_url, fixture, task_count)
        if len(set(run_ids)) != task_count:
            raise RuntimeError("queued tasks did not receive unique run identifiers")
        queued = await _list_project_runs(api_url, fixture)
        staged = [item for item in queued if str(item["id"]) in set(run_ids)]
        if len(staged) != task_count or {str(item["status"]) for item in staged} != {"queued"}:
            raise RuntimeError("drained queue did not persist every task in queued state")
    finally:
        _compose("start", *WORKER_SERVICES)
    terminal = await _wait_for_terminal_runs(
        api_url,
        fixture,
        expected_ids=set(run_ids),
        timeout_seconds=timeout_seconds,
    )
    details = await _load_run_details(api_url, fixture, run_ids)
    execution_ids = [
        str(item["workflow_execution_id"])
        for detail in details
        for item in cast(list[dict[str, Any]], detail["items"])
        if item["workflow_execution_id"] is not None
    ]
    failures = sum(str(item["status"]) != "passed" for item in terminal)
    duplicate_terminal_states = len(terminal) - len({str(item["id"]) for item in terminal})
    return QueueCapacityResult(
        queued_tasks=task_count,
        unique_run_ids=len(set(run_ids)),
        terminal_runs=len(terminal),
        unique_execution_ids=len(set(execution_ids)),
        duplicate_terminal_states=duplicate_terminal_states,
        failures=failures,
        duration_seconds=round(perf_counter() - started_at, 3),
    )


async def _enqueue_runs(api_url: str, fixture: QueueFixture, task_count: int) -> list[str]:
    semaphore = asyncio.Semaphore(50)
    nonce = secrets.token_hex(8)
    async with httpx.AsyncClient(base_url=api_url, timeout=30) as client:

        async def enqueue(index: int) -> str:
            token = fixture.service_tokens[index % len(fixture.service_tokens)]
            async with semaphore:
                response = await client.post(
                    f"/ci/projects/{fixture.project_id}/test-plans/{fixture.plan_id}/runs",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Idempotency-Key": f"s19-capacity-{nonce}-{index}",
                    },
                )
                response.raise_for_status()
                return str(cast(dict[str, Any], response.json())["id"])

        return list(await asyncio.gather(*(enqueue(index) for index in range(task_count))))


async def _wait_for_terminal_runs(
    api_url: str,
    fixture: QueueFixture,
    *,
    expected_ids: set[str],
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    deadline = perf_counter() + timeout_seconds
    while perf_counter() < deadline:
        runs = await _list_project_runs(api_url, fixture)
        selected = [item for item in runs if str(item["id"]) in expected_ids]
        if len(selected) == len(expected_ids) and all(
            str(item["status"]) not in {"queued", "running"} for item in selected
        ):
            return selected
        await asyncio.sleep(0.5)
    raise TimeoutError("queued S19 tasks did not reach terminal states")


async def _list_project_runs(api_url: str, fixture: QueueFixture) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {fixture.access_token}"}
    async with httpx.AsyncClient(base_url=api_url, headers=headers, timeout=30) as client:
        first = await client.get(
            f"/projects/{fixture.project_id}/test-plan-runs",
            params={"page": 1, "page_size": 100},
        )
        first.raise_for_status()
        payload = cast(dict[str, Any], first.json())
        total = int(payload["total"])
        items = list(cast(list[dict[str, Any]], payload["items"]))
        pages = (total + 99) // 100

        async def page(number: int) -> list[dict[str, Any]]:
            response = await client.get(
                f"/projects/{fixture.project_id}/test-plan-runs",
                params={"page": number, "page_size": 100},
            )
            response.raise_for_status()
            return list(cast(list[dict[str, Any]], response.json()["items"]))

        remaining = await asyncio.gather(*(page(number) for number in range(2, pages + 1)))
        return items + [item for group in remaining for item in group]


async def _load_run_details(
    api_url: str, fixture: QueueFixture, run_ids: list[str]
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(50)
    headers = {"Authorization": f"Bearer {fixture.access_token}"}
    async with httpx.AsyncClient(base_url=api_url, headers=headers, timeout=30) as client:

        async def load(run_id: str) -> dict[str, Any]:
            async with semaphore:
                response = await client.get(
                    f"/projects/{fixture.project_id}/test-plan-runs/{run_id}"
                )
                response.raise_for_status()
                return cast(dict[str, Any], response.json())

        return list(await asyncio.gather(*(load(run_id) for run_id in run_ids)))


def _prepare_fixture(
    client: APIClient,
    config: SmokeConfig,
    token: str,
    *,
    task_count: int,
) -> QueueFixture:
    project = client.json(
        "POST",
        "/projects",
        {"name": f"S19 Queue {secrets.token_hex(5)}", "description": "1000 durable tasks"},
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
        {"name": "Queue Target", "base_url": config.target_url},
        token=token,
    )
    api = _create_api(client, token, project_id, "Queue Health", "/health")
    api_id = str(cast(dict[str, Any], api["definition"])["id"])
    workflow = _create_workflow(client, token, project_id, "Queue Workflow", api_id)
    workflow_id = str(workflow["id"])
    client.json("POST", f"/projects/{project_id}/workflows/{workflow_id}/versions", token=token)
    plan = client.json(
        "POST",
        f"/projects/{project_id}/test-plans",
        {
            "name": "1000 Task Plan",
            "queue_priority": 9,
            "items": [
                {
                    "workflow_id": workflow_id,
                    "environment_id": str(environment["id"]),
                }
            ],
        },
        token=token,
    )
    producer_count = max(4, (task_count + 24) // 25)
    service_tokens = tuple(
        str(
            client.json(
                "POST",
                f"/projects/{project_id}/service-tokens",
                {"name": f"Queue Producer {index}", "scopes": ["execute:test-plan"]},
                token=token,
            )["token"]
        )
        for index in range(producer_count)
    )
    return QueueFixture(project_id, str(plan["id"]), token, service_tokens)


def _compose(action: str, *services: str) -> None:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker executable is required for the S19 queue capacity gate")
    subprocess.run([docker, "compose", action, *services], check=True)


def main() -> None:
    config = SmokeConfig.from_environment()
    task_count = int(os.getenv("FLOWTEST_S19_QUEUE_TASKS", "1000"))
    timeout_seconds = float(os.getenv("FLOWTEST_S19_QUEUE_TIMEOUT_SECONDS", "900"))
    if not 1 <= task_count <= 1200:
        raise ValueError("S19 queue task count must be between 1 and 1200")
    client = APIClient(config.api_url)
    login = client.json("POST", "/auth/login", {"email": config.email, "password": config.password})
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(cast(dict[str, Any], login["user"])["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-Capacity-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    try:
        fixture = _prepare_fixture(client, config, token, task_count=task_count)
        result = asyncio.run(
            run_capacity(
                api_url=config.api_url,
                fixture=fixture,
                task_count=task_count,
                timeout_seconds=timeout_seconds,
            )
        )
        print(json.dumps({**asdict(result), "project_id": fixture.project_id}, sort_keys=True))
        if (
            result.failures
            or result.duplicate_terminal_states
            or result.terminal_runs != task_count
            or result.unique_execution_ids != task_count
        ):
            raise RuntimeError(f"S19 durable queue capacity gate failed: {result}")
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


if __name__ == "__main__":
    main()
