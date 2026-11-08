"""Expiry and unknown cancellation results must not strand native runs."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from test_selftest_product_api import ProductContext, _fixed
from test_selftest_product_api import product as product
from test_tasking_api import tasking_context as tasking_context

from app.core.errors import AppError
from app.main import app
from app.models.access import User
from app.models.self_tests import SelfTestBatch
from app.models.tasking import TestPlanRun as PlanRun
from app.services.tasking import TestPlanService as PlanService


def _watchdog_payload(batch: dict) -> dict:
    return {key: batch[key] for key in ("manifest_digest", "binding_fingerprint")}


async def _expire(context: ProductContext, identifier: str) -> None:
    # Test-only fault injection into this isolated fixture's clock boundary.
    async with context.native.session_maker() as session:
        batch = await session.get(SelfTestBatch, UUID(identifier))
        assert batch is not None
        batch.deadline = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()


async def test_expired_batch_still_allows_owned_native_cancellation(
    product: ProductContext,
) -> None:
    batch, _ = await _fixed(product)
    await _expire(product, batch["id"])
    current = await product.get(product.root + f"/runs/{batch['id']}")
    assert current["phase"] == "expired"
    assert current["actions"]["can_cancel"] is True
    stopped = await product.post(product.root + f"/runs/{batch['id']}/cancel", {})
    assert stopped["phase"] == "cancelled" and stopped["verdict"] == "blocked"
    async with product.native.session_maker() as session:
        run = await session.get(PlanRun, UUID(batch["plan_run_ids"][0]))
        assert run is not None and run.status == "cancelled"


async def test_cancel_retry_resumes_original_run_after_unknown_dispatch(
    product: ProductContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch, _ = await _fixed(product)
    original = PlanService.cancel_run
    calls: list[UUID] = []

    async def cancel(self: PlanService, *, actor: User, project_id: UUID, run_id: UUID) -> PlanRun:
        calls.append(run_id)
        if len(calls) == 1:
            raise AppError(code="TEST_CANCEL_UNKNOWN", message="合成未知结果", status_code=503)
        return await original(self, actor=actor, project_id=project_id, run_id=run_id)

    monkeypatch.setattr(PlanService, "cancel_run", cancel)
    path = product.root + f"/runs/{batch['id']}/cancel"
    first = await product.post(path, {}, status=503)
    assert first["error"]["trace_id"]
    retried = await product.post(path, {})
    assert retried["phase"] == "cancelled" and retried["verdict"] == "blocked"
    assert calls == [UUID(batch["plan_run_ids"][0])] * 2
    assert len(product.native.queue.test_plan_run_ids) == 1


async def test_watchdog_requires_deployment_h_due_deadline_and_exact_frozen_identity(
    product: ProductContext,
) -> None:
    batch, _ = await _fixed(product)
    path = product.agent + f"/runs/{batch['id']}/watchdog"
    payload = _watchdog_payload(batch)
    early = await product.post(path, payload, machine="h", status=409)
    assert early["error"]["code"] == "SELFTEST_WATCHDOG_NOT_DUE"
    assert early["error"]["trace_id"]
    await _expire(product, batch["id"])
    denied = await product.post(path, payload, machine="o", status=403)
    assert denied["error"]["code"] == "SELFTEST_AGENT_FORBIDDEN"
    await product.post(path, payload, status=401)
    changed = await product.post(
        path, {**payload, "manifest_digest": "a" * 64}, machine="h", status=409
    )
    assert changed["error"]["code"] == "SELFTEST_WATCHDOG_IDENTITY_MISMATCH"
    first = await product.post(path, payload, machine="h")
    second = await product.post(path, payload, machine="h")
    assert first["plan_run_ids"] == second["plan_run_ids"] == batch["plan_run_ids"]
    assert second["phase"] == "expired" and second["verdict"] == "blocked"
    assert second["cleanup_status"] != "completed"
    async with product.native.session_maker() as session:
        run = await session.get(PlanRun, UUID(batch["plan_run_ids"][0]))
        assert run is not None and run.status == "cancelled"
    assert len(product.native.queue.test_plan_run_ids) == 1


async def test_h_watchdog_resumes_lost_response_without_claiming_cleanup_or_new_run(
    product: ProductContext,
    tmp_path: Path,
) -> None:
    sys.path.insert(0, str(Path(__file__).parents[2]))
    from scripts.selftest.io import PublicAPI, read_json
    from scripts.selftest.product_watchdog import run_expired_watchdogs

    from app.schemas.self_tests import BatchResponse

    batch, _ = await _fixed(product)
    await _expire(product, batch["id"])
    current = BatchResponse.model_validate(await product.get(product.root + f"/runs/{batch['id']}"))
    calls: list[str] = []

    class DropFirstResponse(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.inner = httpx.ASGITransport(app=app)

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            response = await self.inner.handle_async_request(request)
            if len(calls) == 1:
                await response.aclose()
                raise httpx.ReadTimeout("private-secret after real cancellation", request=request)
            return response

        async def aclose(self) -> None:
            await self.inner.aclose()

    token = product.machine("h")["Authorization"].removeprefix("Bearer ")
    api = PublicAPI("http://runner", token, transport=DropFirstResponse())
    try:
        await run_expired_watchdogs(api, (current,), Path(tmp_path))
        pending = read_json(tmp_path / batch["id"] / "watchdog.json")
        assert pending["status"] == "pending" and pending["attempts"] == 1
        await run_expired_watchdogs(api, (current,), Path(tmp_path))
        await run_expired_watchdogs(api, (current,), Path(tmp_path))
    finally:
        await api.close()
    recorded = (tmp_path / batch["id"] / "watchdog.json").read_text()
    assert "private-secret" not in recorded and "Bearer" not in recorded
    state = read_json(tmp_path / batch["id"] / "watchdog.json")
    assert state["status"] == "cancel_requested" and state["attempts"] == 2
    assert len(calls) == 2 and len(set(calls)) == 1
    assert len(product.native.queue.test_plan_run_ids) == 1


async def test_h_watchdog_stops_after_three_transient_attempts(
    product: ProductContext,
    tmp_path: Path,
) -> None:
    sys.path.insert(0, str(Path(__file__).parents[2]))
    from scripts.selftest.io import HarnessError, PublicAPI, read_json
    from scripts.selftest.product_watchdog import run_expired_watchdogs

    from app.schemas.self_tests import BatchResponse

    batch, _ = await _fixed(product)
    await _expire(product, batch["id"])
    current = BatchResponse.model_validate(await product.get(product.root + f"/runs/{batch['id']}"))
    requests: list[str] = []

    def reject(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(
            503, json={"error": {"code": "CANCEL_UNKNOWN", "message": "private-secret"}}
        )

    api = PublicAPI("http://runner", transport=httpx.MockTransport(reject))
    try:
        for _ in range(3):
            await run_expired_watchdogs(api, (current,), tmp_path)
        with pytest.raises(HarnessError, match="SELFTEST_WATCHDOG_CANCELLATION_UNKNOWN"):
            await run_expired_watchdogs(api, (current,), tmp_path)
    finally:
        await api.close()
    assert len(requests) == 3 and len(set(requests)) == 1
    state = read_json(tmp_path / batch["id"] / "watchdog.json")
    assert state["attempts"] == 3 and state["status"] == "pending"
    assert "private-secret" not in str(state)


async def test_native_finish_racing_cancel_is_read_back_without_rewriting_raw_result(
    product: ProductContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch, _ = await _fixed(product)

    async def finished(
        self: PlanService, *, actor: User, project_id: UUID, run_id: UUID
    ) -> PlanRun:
        async with product.native.session_maker() as session:
            run = await session.get(PlanRun, run_id)
            assert run is not None
            run.status = "passed"
            await session.commit()
        raise AppError(code="TEST_PLAN_RUN_FINISHED", message="运行刚结束", status_code=409)

    monkeypatch.setattr(PlanService, "cancel_run", finished)
    result = await product.post(product.root + f"/runs/{batch['id']}/cancel", {})
    assert result["phase"] == "cancelled" and result["verdict"] == "blocked"
    async with product.native.session_maker() as session:
        run = await session.get(PlanRun, UUID(batch["plan_run_ids"][0]))
        assert run is not None and run.status == "passed"
