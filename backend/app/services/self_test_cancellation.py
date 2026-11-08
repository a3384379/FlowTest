"""Resume cancellation of the exact native runs without reviving expired batches."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.self_tests import SelfTestPrincipal, SelfTestSettings
from app.domain.self_tests import aware
from app.models.access import User
from app.models.self_tests import SelfTestBatch
from app.models.tasking import TestPlanRun
from app.schemas.self_test_watchdog import WatchdogRequest
from app.schemas.self_tests import BatchResponse
from app.services.self_test_access import SelfTestAccess, self_test_error
from app.services.self_test_views import SelfTestViews
from app.services.tasking import TestPlanService


class SelfTestCancellation:
    def __init__(self, session: AsyncSession, config: SelfTestSettings) -> None:
        self.session = session
        self.access = SelfTestAccess(session, config)
        self.views = SelfTestViews(session, config)

    async def watchdog(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        identifier: UUID,
        payload: WatchdogRequest,
    ) -> BatchResponse:
        batch = await self.access.batch(project_id, identifier)
        self.access.agent_binding(principal, project_id, batch.binding_id, "install")
        self.access.frozen_binding(batch)
        if (
            payload.manifest_digest != batch.manifest_digest
            or payload.binding_fingerprint != batch.binding_fingerprint
        ):
            raise self_test_error("SELFTEST_WATCHDOG_IDENTITY_MISMATCH", "截止清理的冻结身份不符")
        if aware(batch.deadline) > datetime.now(UTC):
            raise self_test_error("SELFTEST_WATCHDOG_NOT_DUE", "批次尚未达到截止时间")
        actor = await self.access.actor(batch.created_by_id, project_id, editing=True)
        return await self.cancel(actor, batch, expired=True)

    async def cancel(
        self, actor: User, batch: SelfTestBatch, *, expired: bool = False
    ) -> BatchResponse:
        if batch.sealed_at is not None or batch.phase == "completed":
            raise self_test_error("SELFTEST_BATCH_FINISHED", "批次已封存, 不能改变结果")
        if await self.access.repository.lock_batch(batch) is None:
            raise self_test_error("SELFTEST_BATCH_BUSY", "批次正在被其他任务修改")
        # Commit the blocked intent first. A failed response can safely resume
        # cancellation of these same runs, while receipt sealing stays denied.
        batch.phase = "expired" if expired else "cancelled"
        batch.generation_stage, batch.verdict, batch.readiness = "cancelled", "blocked", "blocked"
        batch.reason_codes = (
            ["SELFTEST_BATCH_EXPIRED", "SELFTEST_WATCHDOG_CANCEL_REQUESTED"]
            if expired
            else ["SELFTEST_CANCEL_REQUESTED"]
        )
        await self.session.commit()
        await self._native(actor, batch)
        return await self.views.batch(batch, editing=True)

    async def _native(self, actor: User, batch: SelfTestBatch) -> None:
        for identifier in batch.plan_run_ids:
            run = await self.session.get(TestPlanRun, UUID(identifier))
            if run is None or run.project_id != batch.project_id:
                raise self_test_error("SELFTEST_NATIVE_RUN_MISSING", "本批原生运行无法核实", 404)
            if (
                run.status in {"passed", "failed", "cancelled"}
                or run.cancel_requested_at is not None
            ):
                continue
            try:
                await TestPlanService(self.session).cancel_run(
                    actor=actor, project_id=batch.project_id, run_id=run.id
                )
            except AppError as error:
                if error.code != "TEST_PLAN_RUN_FINISHED":
                    raise
                await self.session.refresh(run)
                if run.status not in {"passed", "failed", "cancelled"}:
                    raise
