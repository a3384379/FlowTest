"""Lease-bound Observer projections of one frozen self-test batch's native evidence."""

from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.self_tests import SelfTestPrincipal, SelfTestSettings
from app.models.access import User
from app.models.self_tests import SelfTestBatch
from app.models.tasking import TestPlanRun, TestPlanRunItem
from app.models.workflows import WorkflowExecution
from app.schemas.execution_evidence import (
    ControlRecordsEvidenceResponse,
    ExecutionEvidenceResponse,
    PlanRunEvidenceResponse,
)
from app.schemas.self_test_evidence import SyntheticNameEvidence
from app.schemas.self_tests import LeaseRequest
from app.services.execution_evidence import ExecutionEvidenceService
from app.services.self_test_access import SelfTestAccess, self_test_error
from app.services.self_test_synthetic_evidence import SelfTestSyntheticEvidence


class SelfTestEvidenceService:
    def __init__(self, session: AsyncSession, config: SelfTestSettings) -> None:
        self.session = session
        self.access = SelfTestAccess(session, config)
        self.evidence = ExecutionEvidenceService(session)

    async def _authority(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        batch_id: UUID,
        lease: LeaseRequest,
    ) -> tuple[SelfTestBatch, User]:
        batch = await self.access.batch(project_id, batch_id)
        self.access.agent_binding(principal, project_id, batch.binding_id, "verify")
        self.access.frozen_binding(batch)
        self.access.active_batch(batch)
        self.access.lease(batch, principal, lease)
        if batch.phase != "collecting" or not batch.plan_run_ids:
            raise self_test_error("SELFTEST_OBSERVATION_NOT_READY", "尚未认领有正式运行的核验任务")
        actor = await self.access.actor(batch.created_by_id, project_id, editing=False)
        return batch, actor

    async def _run(self, batch: SelfTestBatch, run_id: UUID) -> None:
        run = await self.session.get(TestPlanRun, run_id)
        if (
            str(run_id) not in batch.plan_run_ids
            or run is None
            or run.project_id != batch.project_id
        ):
            raise self_test_error("SELFTEST_EVIDENCE_NOT_IN_BATCH", "证据不属于此冻结批次", 404)

    async def plan_run(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        batch_id: UUID,
        lease: LeaseRequest,
        run_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> PlanRunEvidenceResponse:
        batch, actor = await self._authority(principal, project_id, batch_id, lease)
        await self._run(batch, run_id)
        return await self.evidence.plan_run(
            actor=actor, project_id=project_id, run_id=run_id, page=page, page_size=page_size
        )

    async def _execution(self, batch: SelfTestBatch, execution_id: UUID) -> None:
        current, seen = execution_id, set[UUID]()
        for _ in range(10):
            model = await self.session.get(WorkflowExecution, current)
            if model is None or model.project_id != batch.project_id or current in seen:
                break
            seen.add(current)
            if model.source_plan_run_item_id is not None:
                item = await self.session.get(TestPlanRunItem, model.source_plan_run_item_id)
                if item is None or str(item.test_plan_run_id) not in batch.plan_run_ids:
                    break
                await self._run(batch, item.test_plan_run_id)
                # Every direct attempt is identified by its native immutable item FK.
                # Dataset/child executions below it must carry only this batch's item FKs.
                if model.parent_execution_id is None:
                    return
            if model.parent_execution_id is None:
                break
            current = model.parent_execution_id
        raise self_test_error("SELFTEST_EVIDENCE_NOT_IN_BATCH", "执行或子执行不属于此冻结批次", 404)

    async def execution(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        batch_id: UUID,
        lease: LeaseRequest,
        execution_id: UUID,
    ) -> ExecutionEvidenceResponse:
        batch, actor = await self._authority(principal, project_id, batch_id, lease)
        await self._execution(batch, execution_id)
        return await self.evidence.execution(
            actor=actor, project_id=project_id, execution_id=execution_id
        )

    async def control_records(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        batch_id: UUID,
        lease: LeaseRequest,
        execution_id: UUID,
        *,
        node_id: str,
        kind: Literal["iteration", "branch"],
        page: int,
        page_size: int,
    ) -> ControlRecordsEvidenceResponse:
        batch, actor = await self._authority(principal, project_id, batch_id, lease)
        await self._execution(batch, execution_id)
        return await self.evidence.control_records(
            actor=actor,
            project_id=project_id,
            execution_id=execution_id,
            node_id=node_id,
            kind=kind,
            page=page,
            page_size=page_size,
        )

    async def synthetic_names(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        batch_id: UUID,
        lease: LeaseRequest,
        execution_id: UUID,
    ) -> SyntheticNameEvidence:
        batch, _actor = await self._authority(principal, project_id, batch_id, lease)
        await self._execution(batch, execution_id)
        binding = self.access.binding(project_id, batch.binding_id)
        return await SelfTestSyntheticEvidence(self.session, binding).read(batch, execution_id)
