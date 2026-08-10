#!/usr/bin/env python3
"""Measure end-to-end capacity with real persisted Workflow executions."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any, cast

import httpx
from smoke_s4 import APIClient, SmokeConfig, _allow_compose_target, _change_password
from smoke_s5 import _create_api


@dataclass(frozen=True, slots=True)
class WorkflowCapacityConfig:
    requests: int
    concurrency: int
    p95_limit_seconds: float
    completion_timeout_seconds: float

    @classmethod
    def from_environment(cls) -> WorkflowCapacityConfig:
        config = cls(
            requests=int(os.getenv("FLOWTEST_CAPACITY_WORKFLOW_REQUESTS", "100")),
            concurrency=int(os.getenv("FLOWTEST_CAPACITY_WORKFLOW_CONCURRENCY", "100")),
            p95_limit_seconds=float(os.getenv("FLOWTEST_CAPACITY_WORKFLOW_P95_SECONDS", "10")),
            completion_timeout_seconds=float(
                os.getenv("FLOWTEST_CAPACITY_WORKFLOW_TIMEOUT_SECONDS", "120")
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.requests < 1 or not 1 <= self.concurrency <= self.requests:
            raise ValueError("requests and concurrency must define a positive bounded workload")
        if self.p95_limit_seconds <= 0 or self.completion_timeout_seconds <= 0:
            raise ValueError("capacity time limits must be positive")


@dataclass(frozen=True, slots=True)
class WorkflowCapacityResult:
    requests: int
    concurrency: int
    passed: int
    failed: int
    duration_seconds: float
    throughput_per_second: float
    p95_execution_seconds: float


@dataclass(frozen=True, slots=True)
class CapacityFixture:
    project_id: str
    environment_id: str
    workflow_id: str
    service_tokens: tuple[str, ...]


async def run_capacity(
    *,
    api_url: str,
    token: str,
    fixture: CapacityFixture,
    config: WorkflowCapacityConfig,
) -> WorkflowCapacityResult:
    semaphore = asyncio.Semaphore(config.concurrency)
    run_nonce = secrets.token_hex(8)
    latencies: list[float] = []

    async with httpx.AsyncClient(
        base_url=api_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    ) as client:

        async def execute(index: int) -> bool:
            async with semaphore:
                started_at = perf_counter()
                service_token = fixture.service_tokens[index % len(fixture.service_tokens)]
                response = await client.post(
                    f"/ci/projects/{fixture.project_id}/workflows/{fixture.workflow_id}/executions",
                    json={"environment_id": fixture.environment_id},
                    headers={
                        "Authorization": f"Bearer {service_token}",
                        "Idempotency-Key": f"capacity-{run_nonce}-{index}",
                    },
                )
                response.raise_for_status()
                execution_id = str(cast(dict[str, Any], response.json())["id"])
                passed = await _wait_for_execution(
                    client,
                    project_id=fixture.project_id,
                    execution_id=execution_id,
                    timeout_seconds=config.completion_timeout_seconds,
                )
                latencies.append(perf_counter() - started_at)
                return passed

        started_at = perf_counter()
        outcomes = await asyncio.gather(*(execute(index) for index in range(config.requests)))
        duration = perf_counter() - started_at

    passed = sum(outcomes)
    failed = config.requests - passed
    return WorkflowCapacityResult(
        requests=config.requests,
        concurrency=config.concurrency,
        passed=passed,
        failed=failed,
        duration_seconds=round(duration, 6),
        throughput_per_second=round(config.requests / duration, 2),
        p95_execution_seconds=round(_percentile_95(latencies), 6),
    )


async def _wait_for_execution(
    client: httpx.AsyncClient,
    *,
    project_id: str,
    execution_id: str,
    timeout_seconds: float,
) -> bool:
    deadline = perf_counter() + timeout_seconds
    while perf_counter() < deadline:
        response = await client.get(f"/projects/{project_id}/workflow-executions/{execution_id}")
        response.raise_for_status()
        payload = cast(dict[str, Any], response.json())
        status = str(cast(dict[str, Any], payload["execution"])["status"])
        if status != "running":
            return status == "passed"
        await asyncio.sleep(0.1)
    raise TimeoutError(f"workflow execution {execution_id} did not complete")


def _percentile_95(values: list[float]) -> float:
    if not values:
        raise ValueError("at least one latency is required")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(len(ordered) * 0.95) - 1))
    return ordered[index]


def _prepare_fixture(
    client: APIClient,
    smoke: SmokeConfig,
    token: str,
    *,
    request_count: int,
) -> CapacityFixture:
    project = client.json(
        "POST",
        "/projects",
        {
            "name": f"S12 Capacity {secrets.token_hex(5)}",
            "description": "Real Workflow capacity baseline",
        },
        token=token,
    )
    project_id = str(project["id"])
    client.json(
        "PUT",
        f"/projects/{project_id}/capacity-policy",
        {"execution_concurrency_limit": 100, "queued_run_limit": 1000},
        token=token,
    )
    _allow_compose_target(client, token, project_id, smoke.target_url)
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": "Capacity Mock", "base_url": smoke.target_url},
        token=token,
    )
    api = _create_api(client, token, project_id, "Capacity health", "/health")
    api_id = str(cast(dict[str, Any], api["definition"])["id"])
    workflow = client.json(
        "POST",
        f"/projects/{project_id}/workflows",
        {"name": "S12 真实容量流程", "definition": _workflow_definition(api_id)},
        token=token,
    )
    workflow_id = str(workflow["id"])
    client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/versions",
        token=token,
    )
    producer_count = max(4, (request_count + 24) // 25)
    service_tokens = tuple(
        str(
            client.json(
                "POST",
                f"/projects/{project_id}/service-tokens",
                {"name": f"Workflow Producer {index}", "scopes": ["execute:workflow"]},
                token=token,
            )["token"]
        )
        for index in range(producer_count)
    )
    return CapacityFixture(
        project_id=project_id,
        environment_id=str(environment["id"]),
        workflow_id=workflow_id,
        service_tokens=service_tokens,
    )


def _workflow_definition(api_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "nodes": [
            _node("start", "start", "开始", 0),
            _node("request", "api", "真实 HTTP 请求", 220, api_id=api_id),
            _node("end", "end", "结束", 440),
        ],
        "edges": [
            {"id": "start-request", "source": "start", "target": "request"},
            {"id": "request-end", "source": "request", "target": "end"},
        ],
        "settings": {"fail_fast": True, "concurrency": 5, "default_timeout_seconds": 30},
    }


def _node(
    node_id: str,
    node_type: str,
    name: str,
    x: int,
    *,
    api_id: str | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if api_id:
        config = {
            "api_definition_id": api_id,
            "max_retries": 0,
            "retry_on": ["network_error", "5xx"],
        }
    return {
        "id": node_id,
        "type": node_type,
        "name": name,
        "position": {"x": x, "y": 100},
        "config": config,
    }


def main() -> None:
    smoke = SmokeConfig.from_environment()
    capacity = WorkflowCapacityConfig.from_environment()
    client = APIClient(smoke.api_url)
    login = client.json("POST", "/auth/login", {"email": smoke.email, "password": smoke.password})
    token = str(login["access_token"])
    active_password = smoke.password
    password_changed = bool(cast(dict[str, Any], login["user"])["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-Capacity-{secrets.token_urlsafe(18)}"
        _change_password(client, token, smoke.password, active_password)
    try:
        fixture = _prepare_fixture(client, smoke, token, request_count=capacity.requests)
        result = asyncio.run(
            run_capacity(
                api_url=smoke.api_url,
                token=token,
                fixture=fixture,
                config=capacity,
            )
        )
        print(json.dumps({**asdict(result), "project_id": fixture.project_id}, sort_keys=True))
        if result.failed or result.p95_execution_seconds > capacity.p95_limit_seconds:
            raise RuntimeError(
                "workflow capacity gate failed: "
                f"failed={result.failed}, p95={result.p95_execution_seconds:.3f}s"
            )
    finally:
        if password_changed:
            _change_password(client, token, active_password, smoke.password)
        client.json("POST", "/auth/logout", token=token)


if __name__ == "__main__":
    main()
