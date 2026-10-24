"""Bounded O transport: legacy collector reads map to a claimed task's public routes."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

import httpx
from pydantic import JsonValue
from scripts.selftest.io import HarnessError, JsonObject, PublicAPI
from scripts.selftest.product_agent_client import agent_root

from app.schemas.self_tests import AgentTaskResponse


def _query(query: str, *, control: bool) -> None:
    pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True)
    allowed = {"page", "page_size", "node_id", "kind"} if control else {"page", "page_size"}
    if len(pairs) != len(dict(pairs)) or not {key for key, _ in pairs} <= allowed:
        raise HarnessError("SELFTEST_TASK_EVIDENCE_QUERY_FORBIDDEN")
    for key, value in pairs:
        if key in {"page", "page_size"} and (
            not value.isdecimal() or not 1 <= int(value) <= (100 if key == "page_size" else 1000)
        ):
            raise HarnessError("SELFTEST_TASK_EVIDENCE_PAGE_INVALID")


def scoped_evidence_path(task: AgentTaskResponse, path: str) -> str:
    parsed = urlsplit(path)
    prefix = f"/ci/projects/{task.project_id}/"
    if parsed.scheme or parsed.netloc or parsed.fragment or not parsed.path.startswith(prefix):
        raise HarnessError("SELFTEST_TASK_EVIDENCE_PATH_FORBIDDEN")
    suffix = parsed.path.removeprefix(prefix)
    plan = re.fullmatch(r"test-plan-runs/([0-9a-f-]{36})", suffix)
    execution = re.fullmatch(
        r"workflow-executions/([0-9a-f-]{36})/evidence(/control-records|/synthetic-names)?", suffix
    )
    if plan is not None:
        if task.batch is None or UUID(plan[1]) not in task.batch.plan_run_ids:
            raise HarnessError("SELFTEST_TASK_EVIDENCE_RUN_NOT_IN_BATCH")
        _query(parsed.query, control=False)
        target = suffix
    elif execution is not None:
        UUID(execution[1])
        _query(parsed.query, control=execution[2] == "/control-records")
        if execution[2] != "/control-records" and parsed.query:
            raise HarnessError("SELFTEST_TASK_EVIDENCE_QUERY_FORBIDDEN")
        target = f"workflow-executions/{execution[1]}{execution[2] or ''}"
    else:
        raise HarnessError("SELFTEST_TASK_EVIDENCE_PATH_FORBIDDEN")
    root = f"{agent_root(task.project_id)}/runs/{task.task_id}/evidence"
    return f"{root}/{target}" + (f"?{parsed.query}" if parsed.query else "")


class TaskEvidenceReader(PublicAPI):
    def __init__(
        self,
        base_url: str,
        token: str,
        task: AgentTaskResponse,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if (
            task.task_kind != "observation"
            or task.batch is None
            or task.project_id != task.batch.project_id
            or task.task_id != task.batch.id
            or task.batch.phase != "collecting"
            or not task.batch.plan_run_ids
        ):
            raise HarnessError("SELFTEST_TASK_EVIDENCE_CLAIM_REQUIRED")
        super().__init__(base_url, token, transport=transport)
        self._task = task
        self._deadline = task.batch.deadline
        self._remaining_requests = min(500, task.budget.max_requests)

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        return {
            **super()._headers(idempotency_key),
            "X-SelfTest-Lease-Token": self._task.lease_token,
            "X-SelfTest-Nonce": self._task.nonce,
        }

    async def request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        idempotency_key: str | None = None,
        allow_status: tuple[int, ...] = (),
    ) -> JsonValue:
        if method != "GET" or payload is not None or idempotency_key or allow_status:
            raise HarnessError("SELFTEST_TASK_EVIDENCE_READONLY")
        if self._remaining_requests <= 0 or datetime.now(UTC) >= self._deadline:
            raise HarnessError("SELFTEST_TASK_EVIDENCE_BUDGET_EXHAUSTED")
        target = scoped_evidence_path(self._task, path)
        self._remaining_requests -= 1
        remaining = (self._deadline - datetime.now(UTC)).total_seconds()
        async with asyncio.timeout(remaining):
            return await super().request("GET", target)

    async def upload_synthetic(self, path: str, filename: str, content: bytes) -> JsonObject:
        raise HarnessError("SELFTEST_TASK_EVIDENCE_READONLY")

    async def read_synthetic(self, path: str) -> bytes:
        raise HarnessError("SELFTEST_TASK_EVIDENCE_PATH_FORBIDDEN")
