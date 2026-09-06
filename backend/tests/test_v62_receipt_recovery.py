"""Completed operation receipts survive mutable state, never revoked authorization."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from test_s58_failure_repair_api import failure_repair_api as failure_repair_api
from test_s59d_change_regression import _bound
from test_s60_continuous_mcp import _account, _counts, _repair

from app.core.config import settings
from app.core.errors import AppError
from app.models.change_regression import ChangeRegressionRun
from app.models.test_contexts import TestContext as ContextModel
from app.models.workflows import Workflow
from app.services.projects import ProjectService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "mutation"),
    [
        ("repair", "revision"),
        ("repair", "expired"),
        ("repair", "authorization"),
        ("maintenance", "revision"),
        ("maintenance", "expired"),
        ("maintenance", "frozen"),
        ("maintenance", "authorization"),
    ],
)
async def test_completed_receipt_recovery(
    failure_repair_api: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    mutation: str,
) -> None:
    fixture = failure_repair_api
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    _, token = await _account(fixture, ["mcp:flow:propose", "mcp:read"])
    payload = await _request(fixture, kind)
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "v62-receipt"}
    path = f"/api/v1/mcp/continuous/{kind}-proposals"
    created = await fixture["client"].post(path, headers=headers, json=payload)
    assert created.status_code == 200, created.text
    before = await _counts(fixture)
    await _mutate(fixture, payload, mutation)
    if mutation == "authorization":

        async def denied(*args: Any, **kwargs: Any) -> None:
            raise AppError(code="PROJECT_ACCESS_DENIED", message="项目访问已撤销", status_code=403)

        monkeypatch.setattr(ProjectService, "authorize", denied)
    repeated = await fixture["client"].post(path, headers=headers, json=payload)
    if mutation == "authorization":
        assert repeated.status_code == 403
        assert created.json()["change_set_id"] not in repeated.text
    else:
        assert repeated.status_code == 200, repeated.text
        assert repeated.json() == created.json()
        fresh = await fixture["client"].post(
            path, headers={**headers, "Idempotency-Key": "v62-new-operation"}, json=payload
        )
        assert fresh.status_code in {409, 422}, fresh.text
        _, other_token = await _account(fixture, ["mcp:flow:propose", "mcp:read"])
        other = await fixture["client"].post(
            path, headers={**headers, "Authorization": f"Bearer {other_token}"}, json=payload
        )
        assert other.status_code in {409, 422}, other.text
        assert created.json()["change_set_id"] not in other.text
        # A changed request cannot use the old receipt, even after state becomes stale.
        payload[kind]["rationale"] = "另一个请求"
        conflict = await fixture["client"].post(path, headers=headers, json=payload)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert await _counts(fixture) == before


async def _request(fixture: dict[str, Any], kind: str) -> dict[str, Any]:
    if kind == "repair":
        return {**await _repair(fixture), "dry_run": False}
    _, maintenance, bound = await _bound(fixture)
    return {
        "project_id": str(fixture["project_id"]),
        "workflow_id": str(fixture["workflow_id"]),
        "run_id": bound["id"],
        "maintenance": maintenance,
        "dry_run": False,
    }


async def _mutate(fixture: dict[str, Any], payload: dict[str, Any], mutation: str) -> None:
    async with fixture["sessions"]() as session:
        if mutation == "revision":
            workflow = await session.get(Workflow, fixture["workflow_id"])
            workflow.draft_revision += 1
        if mutation == "expired":
            for context in await session.scalars(select(ContextModel)):
                context.expires_at = datetime.now(UTC) - timedelta(days=1)
        if mutation == "frozen" and "run_id" in payload:
            run = await session.get(ChangeRegressionRun, UUID(payload["run_id"]))
            run.status = "passed"
        await session.commit()
