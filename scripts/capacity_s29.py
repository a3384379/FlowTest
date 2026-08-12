#!/usr/bin/env python3
"""Verify 5000 durable Runner tasks and a 500-workflow multi-Worker sample."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any, cast
from uuid import UUID

import httpx
from smoke_s4 import APIClient, SmokeConfig, _change_password
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.workflows import WorkflowExecution

RUNNER_SERVICES = ("runner-agent-a", "runner-agent-b")


@dataclass(frozen=True, slots=True)
class S29CapacityConfig:
    queued_tasks: int
    workflow_sample: int
    api_concurrency: int
    timeout_seconds: float
    database_url: str

    @classmethod
    def from_environment(cls) -> S29CapacityConfig:
        config = cls(
            queued_tasks=int(os.getenv("FLOWTEST_S29_QUEUED_TASKS", "5000")),
            workflow_sample=int(os.getenv("FLOWTEST_S29_WORKFLOW_SAMPLE", "500")),
            api_concurrency=int(os.getenv("FLOWTEST_S29_API_CONCURRENCY", "50")),
            timeout_seconds=float(os.getenv("FLOWTEST_S29_TIMEOUT_SECONDS", "900")),
            database_url=os.getenv(
                "FLOWTEST_S29_DATABASE_URL",
                "postgresql+asyncpg://flowtest:flowtest@localhost:5432/flowtest",
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.queued_tasks != 5000:
            raise ValueError("S29 release capacity gate requires exactly 5000 queued tasks")
        if not 300 <= self.workflow_sample <= 500:
            raise ValueError("S29 workflow sample must be between 300 and 500")
        if not 1 <= self.api_concurrency <= 100:
            raise ValueError("S29 API concurrency must be between 1 and 100")
        if self.timeout_seconds <= 0:
            raise ValueError("S29 timeout must be positive")


@dataclass(frozen=True, slots=True)
class CapacityFixture:
    project_id: str
    environment_id: str
    workflow_id: str
    service_tokens: tuple[str, ...]
    runner_a: dict[str, Any]
    runner_b: dict[str, Any]
    runner_environment: dict[str, str]


@dataclass(frozen=True, slots=True)
class S29CapacityResult:
    queued_tasks: int
    unique_queued_executions: int
    encrypted_plans: int
    workflow_sample: int
    passed_workflows: int
    completed_tasks: int
    unique_terminal_executions: int
    terminal_node_records: int
    duplicate_node_records: int
    active_leases: int
    artifact_collisions: int
    workers_used: int
    submission_p95_seconds: float
    duration_seconds: float


def main() -> None:
    smoke = SmokeConfig.from_environment()
    capacity = S29CapacityConfig.from_environment()
    client = APIClient(smoke.api_url)
    login = client.json("POST", "/auth/login", {"email": smoke.email, "password": smoke.password})
    token = str(login["access_token"])
    active_password = smoke.password
    password_changed = bool(cast(dict[str, Any], login["user"])["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-S29-Capacity-{secrets.token_urlsafe(18)}"
        _change_password(client, token, smoke.password, active_password)
    started_at = perf_counter()
    try:
        fixture = _prepare_fixture(client, token, capacity)
        _compose("stop", *RUNNER_SERVICES)
        execution_ids, p95_seconds = asyncio.run(_submit_queue(smoke.api_url, fixture, capacity))
        queue_evidence = asyncio.run(
            _verify_and_prune_queue(
                capacity.database_url,
                project_id=fixture.project_id,
                execution_ids=execution_ids,
                keep=capacity.workflow_sample,
                expected=capacity.queued_tasks,
            )
        )
        _compose(
            "up",
            "-d",
            "--force-recreate",
            *RUNNER_SERVICES,
            environment=fixture.runner_environment,
        )
        terminal = asyncio.run(
            _wait_for_terminal_sample(
                capacity.database_url,
                project_id=fixture.project_id,
                expected=capacity.workflow_sample,
                timeout_seconds=capacity.timeout_seconds,
            )
        )
        result = S29CapacityResult(
            queued_tasks=capacity.queued_tasks,
            unique_queued_executions=int(queue_evidence["unique_executions"]),
            encrypted_plans=int(queue_evidence["encrypted_plans"]),
            workflow_sample=capacity.workflow_sample,
            passed_workflows=int(terminal["passed_workflows"]),
            completed_tasks=int(terminal["completed_tasks"]),
            unique_terminal_executions=int(terminal["unique_terminal_executions"]),
            terminal_node_records=int(terminal["terminal_node_records"]),
            duplicate_node_records=int(terminal["duplicate_node_records"]),
            active_leases=int(terminal["active_leases"]),
            artifact_collisions=int(terminal["artifact_collisions"]),
            workers_used=int(terminal["workers_used"]),
            submission_p95_seconds=round(p95_seconds, 6),
            duration_seconds=round(perf_counter() - started_at, 3),
        )
        _validate_result(result)
        print(json.dumps({**asdict(result), "project_id": fixture.project_id}, sort_keys=True))
    finally:
        if password_changed:
            _change_password(client, token, active_password, smoke.password)
        client.json("POST", "/auth/logout", token=token)


def _prepare_fixture(client: APIClient, token: str, capacity: S29CapacityConfig) -> CapacityFixture:
    nonce = secrets.token_hex(5)
    pool = client.json(
        "POST",
        "/execution-fabric/pools",
        {
            "name": f"S29 Capacity {nonce}",
            "runner_type": "general",
            "runtime": "docker",
            "network_zone": "compose-capacity",
            "labels": ["capacity"],
            "capabilities": ["flow.workflow"],
            "max_concurrency": 500,
            "lease_timeout_seconds": 30,
            "heartbeat_timeout_seconds": 90,
        },
        token=token,
    )
    runner_concurrency = (capacity.workflow_sample + 1) // 2
    runner_a = _register_runner(
        client, token, str(pool["id"]), f"s29-capacity-a-{nonce}", runner_concurrency
    )
    runner_b = _register_runner(
        client, token, str(pool["id"]), f"s29-capacity-b-{nonce}", runner_concurrency
    )
    project = client.json(
        "POST",
        "/projects",
        {
            "name": f"S29 Capacity {nonce}",
            "description": "5000 queue / 500 workflow gate",
        },
        token=token,
    )
    project_id = str(project["id"])
    client.json(
        "PUT",
        f"/projects/{project_id}/capacity-policy",
        {
            "execution_concurrency_limit": capacity.workflow_sample,
            "queued_run_limit": capacity.queued_tasks,
        },
        token=token,
    )
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": "S29 Capacity Runtime", "base_url": "http://mock-target:8080"},
        token=token,
    )
    workflow = client.json(
        "POST",
        f"/projects/{project_id}/workflows",
        {
            "name": "S29 高并发空载流程",
            "description": "固定计划, 仅验证调度与唯一终态",
            "definition": _workflow_definition(),
        },
        token=token,
    )
    workflow_id = str(workflow["id"])
    client.json("POST", f"/projects/{project_id}/workflows/{workflow_id}/versions", token=token)
    producer_count = (capacity.queued_tasks + 499) // 500
    service_tokens = tuple(
        str(
            client.json(
                "POST",
                f"/projects/{project_id}/service-tokens",
                {"name": f"S29 Queue Producer {index}", "scopes": ["execute:workflow"]},
                token=token,
            )["token"]
        )
        for index in range(producer_count)
    )
    runner_environment = os.environ.copy()
    runner_environment.update(
        {
            "FLOWTEST_RUNNER_A_TOKEN": str(runner_a["token"]),
            "FLOWTEST_RUNNER_B_TOKEN": str(runner_b["token"]),
            "FLOWTEST_RUNNER_A_INSTANCE_ID": f"s29-capacity-a-{nonce}",
            "FLOWTEST_RUNNER_B_INSTANCE_ID": f"s29-capacity-b-{nonce}",
            "FLOWTEST_RUNNER_CONCURRENCY": str(runner_concurrency),
            "FLOWTEST_RUNNER_LABELS": "capacity",
        }
    )
    return CapacityFixture(
        project_id=project_id,
        environment_id=str(environment["id"]),
        workflow_id=workflow_id,
        service_tokens=service_tokens,
        runner_a=runner_a,
        runner_b=runner_b,
        runner_environment=runner_environment,
    )


def _register_runner(
    client: APIClient,
    token: str,
    pool_id: str,
    instance_id: str,
    max_concurrency: int,
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
            "instance_id": f"{instance_id}-identity",
            "runtime": "docker",
            "agent_version": "3.0.0-beta.3",
            "architecture": "arm64",
            "labels": ["capacity"],
            "capabilities": ["flow.workflow"],
            "max_concurrency": max_concurrency,
        },
        token=str(registration["token"]),
    )


def _workflow_definition() -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "name": "开始",
                "position": {"x": 0, "y": 100},
                "config": {},
            },
            {
                "id": "end",
                "type": "end",
                "name": "结束",
                "position": {"x": 220, "y": 100},
                "config": {},
            },
        ],
        "edges": [{"id": "start-end", "source": "start", "target": "end"}],
        "settings": {
            "fail_fast": True,
            "concurrency": 2,
            "default_timeout_seconds": 30,
        },
    }


async def _submit_queue(
    api_url: str, fixture: CapacityFixture, capacity: S29CapacityConfig
) -> tuple[list[str], float]:
    semaphore = asyncio.Semaphore(capacity.api_concurrency)
    nonce = secrets.token_hex(8)
    latencies: list[float] = []
    limits = httpx.Limits(
        max_connections=capacity.api_concurrency,
        max_keepalive_connections=capacity.api_concurrency,
    )
    async with httpx.AsyncClient(
        base_url=api_url,
        timeout=httpx.Timeout(capacity.timeout_seconds, connect=10),
        limits=limits,
    ) as client:

        async def submit(index: int) -> str:
            async with semaphore:
                started_at = perf_counter()
                response = await client.post(
                    f"/ci/projects/{fixture.project_id}/workflows/{fixture.workflow_id}/executions",
                    json={"environment_id": fixture.environment_id},
                    headers={
                        "Authorization": (
                            f"Bearer {fixture.service_tokens[index % len(fixture.service_tokens)]}"
                        ),
                        "Idempotency-Key": f"s29-capacity-{nonce}-{index}",
                    },
                )
                response.raise_for_status()
                latencies.append(perf_counter() - started_at)
                return str(cast(dict[str, Any], response.json())["id"])

        execution_ids = list(
            await asyncio.gather(*(submit(index) for index in range(capacity.queued_tasks)))
        )
    if len(set(execution_ids)) != capacity.queued_tasks:
        raise RuntimeError("S29 queue submissions did not receive unique execution IDs")
    return execution_ids, _percentile_95(latencies)


async def _verify_and_prune_queue(
    database_url: str,
    *,
    project_id: str,
    execution_ids: list[str],
    keep: int,
    expected: int,
) -> Mapping[str, Any]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            evidence = await _queue_evidence(session, project_id)
            if any(
                int(evidence[key]) != expected
                for key in ("queued_tasks", "unique_executions", "encrypted_plans")
            ):
                raise RuntimeError(f"S29 persisted queue evidence is incomplete: {evidence}")
            keep_ids = [UUID(value) for value in execution_ids[:keep]]
            await session.execute(
                delete(WorkflowExecution).where(
                    WorkflowExecution.project_id == UUID(project_id),
                    WorkflowExecution.id.not_in(keep_ids),
                )
            )
            await session.commit()
            remaining = await _queue_evidence(session, project_id)
            if int(remaining["queued_tasks"]) != keep:
                raise RuntimeError(f"S29 capacity sample prune is inconsistent: {remaining}")
            return evidence
    finally:
        await engine.dispose()


async def _queue_evidence(session: AsyncSession, project_id: str) -> Mapping[str, Any]:
    result = await session.execute(
        text(
            "SELECT COUNT(*) AS queued_tasks, "
            "COUNT(DISTINCT rt.execution_id) AS unique_executions, "
            "COUNT(we.run_payload_ciphertext) AS encrypted_plans "
            "FROM runner_tasks rt "
            "JOIN workflow_executions we ON we.id = rt.execution_id "
            "WHERE rt.project_id = :project_id AND rt.status = 'queued'"
        ),
        {"project_id": project_id},
    )
    return cast(Mapping[str, Any], result.mappings().one())


async def _wait_for_terminal_sample(
    database_url: str, *, project_id: str, expected: int, timeout_seconds: float
) -> Mapping[str, Any]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    deadline = perf_counter() + timeout_seconds
    try:
        while perf_counter() < deadline:
            async with sessions() as session:
                task_counts = await _status_counts(session, "runner_tasks", project_id)
                if int(task_counts.get("failed", 0)):
                    raise RuntimeError(f"S29 capacity Runner tasks failed: {task_counts}")
                if int(task_counts.get("completed", 0)) == expected:
                    return await _terminal_evidence(session, project_id)
            await asyncio.sleep(0.5)
    finally:
        await engine.dispose()
    raise TimeoutError(f"S29 capacity sample did not complete within {timeout_seconds}s")


async def _status_counts(session: AsyncSession, table_name: str, project_id: str) -> dict[str, int]:
    statements = {
        "runner_tasks": text(
            "SELECT status, COUNT(*) AS count FROM runner_tasks "
            "WHERE project_id = :project_id GROUP BY status"
        ),
        "workflow_executions": text(
            "SELECT status, COUNT(*) AS count FROM workflow_executions "
            "WHERE project_id = :project_id GROUP BY status"
        ),
    }
    statement = statements.get(table_name)
    if statement is None:
        raise ValueError("unsupported capacity status table")
    result = await session.execute(
        statement,
        {"project_id": project_id},
    )
    return {str(row["status"]): int(row["count"]) for row in result.mappings()}


async def _terminal_evidence(session: AsyncSession, project_id: str) -> Mapping[str, Any]:
    workflow_counts = await _status_counts(session, "workflow_executions", project_id)
    if set(workflow_counts) != {"passed"}:
        raise RuntimeError(f"S29 capacity workflows are not uniquely terminal: {workflow_counts}")
    node_result = await session.execute(
        text(
            "SELECT COUNT(*) AS total, "
            "COUNT(DISTINCT (wn.workflow_execution_id, wn.node_id)) AS unique_nodes "
            "FROM workflow_node_executions wn "
            "JOIN workflow_executions we ON we.id = wn.workflow_execution_id "
            "WHERE we.project_id = :project_id"
        ),
        {"project_id": project_id},
    )
    nodes = cast(Mapping[str, Any], node_result.mappings().one())
    runner_result = await session.execute(
        text(
            "SELECT COUNT(DISTINCT selected_runner_id) AS workers_used, "
            "COUNT(DISTINCT execution_id) AS unique_terminal_executions, "
            "COUNT(*) AS completed_tasks "
            "FROM runner_tasks WHERE project_id = :project_id AND status = 'completed'"
        ),
        {"project_id": project_id},
    )
    runners = cast(Mapping[str, Any], runner_result.mappings().one())
    lease_result = await session.execute(
        text(
            "SELECT COUNT(*) FILTER (WHERE rl.status = 'active') AS active_leases "
            "FROM runner_leases rl JOIN runner_tasks rt ON rt.id = rl.task_id "
            "WHERE rt.project_id = :project_id"
        ),
        {"project_id": project_id},
    )
    leases = cast(Mapping[str, Any], lease_result.mappings().one())
    artifact_count = int(
        await session.scalar(
            text("SELECT COUNT(*) FROM artifacts WHERE project_id = :project_id"),
            {"project_id": project_id},
        )
        or 0
    )
    total_nodes = int(nodes["total"])
    unique_nodes = int(nodes["unique_nodes"])
    return {
        "passed_workflows": int(workflow_counts["passed"]),
        "completed_tasks": int(runners["completed_tasks"]),
        "unique_terminal_executions": int(runners["unique_terminal_executions"]),
        "terminal_node_records": total_nodes,
        "duplicate_node_records": total_nodes - unique_nodes,
        "active_leases": int(leases["active_leases"]),
        "artifact_collisions": artifact_count,
        "workers_used": int(runners["workers_used"]),
    }


def _validate_result(result: S29CapacityResult) -> None:
    expected_nodes = result.workflow_sample * 2
    valid = (
        result.unique_queued_executions == result.queued_tasks
        and result.encrypted_plans == result.queued_tasks
        and result.passed_workflows == result.workflow_sample
        and result.completed_tasks == result.workflow_sample
        and result.unique_terminal_executions == result.workflow_sample
        and result.terminal_node_records == expected_nodes
        and result.duplicate_node_records == 0
        and result.active_leases == 0
        and result.artifact_collisions == 0
        and result.workers_used == 2
    )
    if not valid:
        raise RuntimeError(f"S29 capacity gate failed: {asdict(result)}")


def _percentile_95(values: list[float]) -> float:
    if not values:
        raise ValueError("S29 capacity latency sample is empty")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(len(ordered) * 0.95) - 1))
    return ordered[index]


def _compose(*arguments: str, environment: dict[str, str] | None = None) -> None:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker executable is required for the S29 capacity gate")
    subprocess.run(  # noqa: S603 -- executable and arguments are locally allowlisted.
        [docker, "compose", "--profile", "runner-fabric", *arguments],
        check=True,
        env=environment,
    )


if __name__ == "__main__":
    main()
