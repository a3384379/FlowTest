"""Lost responses and interrupted cancellation preserve the original operation."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from test_selftest_product_api import ProductContext, _claimed_installation, _fixed
from test_selftest_product_api import product as product
from test_tasking_api import tasking_context as tasking_context

from app.core.errors import AppError
from app.models.self_tests import SelfTestInstallation
from app.models.tasking import TestPlanRun as PlanRun
from app.services.tasking import TestPlanService as PlanService


async def test_resume_response_replay_preserves_revision_and_rejects_changed_request(
    product: ProductContext,
):
    installed, _ = await _claimed_installation(product)
    async with product.native.session_maker() as session:
        row = await session.get(SelfTestInstallation, UUID(installed["id"]))
        assert row
        row.status = "blocked"
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    current = await product.get(product.root + f"/installations/{installed['id']}")
    payload = {
        "expected_revision": current["revision"],
        "environment_fingerprint": current["environment_fingerprint"],
        "confirmed": True,
    }
    path = product.root + f"/installations/{installed['id']}/resume"
    first = await product.post(path, payload, key="resume-lost-response")
    replay = await product.post(path, payload, key="resume-lost-response")
    assert replay == first
    after = await product.get(product.root + f"/installations/{installed['id']}")
    assert after["revision"] == first["revision"] == current["revision"] + 1
    conflict = await product.post(
        path,
        {**payload, "expected_revision": first["revision"]},
        key="resume-lost-response",
        status=409,
    )
    assert conflict["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert conflict["error"]["trace_id"]


async def test_interrupted_native_cancellation_remains_retryable(
    product: ProductContext, monkeypatch
):
    batch, _ = await _fixed(product)
    path = product.root + f"/runs/{batch['id']}/cancel"
    original = PlanService.cancel_run
    attempts = 0

    async def interrupted(self, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise AppError(code="TEST_CANCEL_UNAVAILABLE", message="取消暂不可用", status_code=503)
        return await original(self, **kwargs)

    monkeypatch.setattr(PlanService, "cancel_run", interrupted)
    failed = await product.post(path, {}, status=503)
    assert failed["error"]["trace_id"]
    blocked = await product.get(product.root + f"/runs/{batch['id']}")
    assert blocked["phase"] == "cancelled" and blocked["actions"]["can_cancel"] is True
    resumed = await product.post(path, {})
    assert resumed["plan_run_ids"] == batch["plan_run_ids"] and attempts == 2
    async with product.native.session_maker() as session:
        run = await session.get(PlanRun, UUID(batch["plan_run_ids"][0]))
        assert run and (run.cancel_requested_at is not None or run.status == "cancelled")
