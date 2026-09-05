"""Pinned workflow coverage for the V6 extension; sandbox previews never qualify."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.engine.contracts import WorkflowDefinition
from app.models.change_regression import ChangeRegressionRun
from app.models.tasking import TestPlanItem, TestPlanRunItem
from app.models.workflows import Workflow, WorkflowExecution, WorkflowVersion
from app.schemas.regression_maintenance import (
    RegressionMaintenanceSnapshot,
    RegressionWorkflowEvidence,
    maintenance_snapshot,
)
from app.services.tasking import TestPlanService
from app.services.workflows import WorkflowService


class RegressionMaintenanceCoverage:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def freeze(
        self, run: ChangeRegressionRun, snapshot: RegressionMaintenanceSnapshot
    ) -> list[RegressionWorkflowEvidence]:
        refs = await self._plan_refs(run)
        result = []
        for item in snapshot.affected.affected_workflows:
            result.append(await self._published_target(run.project_id, item.workflow_id, refs))
        return result

    async def require_plan(self, run: ChangeRegressionRun, *, check_draft: bool = False) -> None:
        snapshot = maintenance_snapshot(run.selection_summary)
        if snapshot is None:
            return
        refs = await self._plan_refs(run)
        for item in snapshot.required_workflows:
            if (item.workflow_id, item.workflow_version) not in refs:
                raise _coverage_error("PLAN_GAP", "当前测试计划缺少已审核的固定流程版本")
            if check_draft:
                current = await self._published_target(run.project_id, item.workflow_id, refs)
                if current != item:
                    raise _coverage_error(
                        "REVIEW_STALE", "流程草稿或发布版本已变化, 请重新审核维护证据"
                    )

    async def require_execution(self, run: ChangeRegressionRun) -> None:
        snapshot = maintenance_snapshot(run.selection_summary)
        if snapshot is None:
            return
        rows = (
            await self._session.execute(
                select(
                    TestPlanRunItem.workflow_id,
                    TestPlanRunItem.workflow_version,
                    WorkflowExecution.workflow_version_id,
                )
                .join(
                    WorkflowExecution, TestPlanRunItem.workflow_execution_id == WorkflowExecution.id
                )
                .where(
                    TestPlanRunItem.test_plan_run_id == run.test_plan_run_id,
                    TestPlanRunItem.status == "passed",
                    WorkflowExecution.status == "passed",
                    WorkflowExecution.project_id == run.project_id,
                    WorkflowExecution.workflow_id == TestPlanRunItem.workflow_id,
                    WorkflowExecution.source_change_set_id.is_(None),
                    WorkflowExecution.run_purpose == "standard",
                )
            )
        ).all()
        covered = set(rows)
        if any(
            (item.workflow_id, item.workflow_version, item.workflow_version_id) not in covered
            for item in snapshot.required_workflows
        ):
            raise _coverage_error(
                "EXECUTION_GAP", "受影响流程缺少固定版本的正式成功执行; Preview 不计覆盖"
            )

    async def _plan_refs(self, run: ChangeRegressionRun) -> set[tuple[UUID, int]]:
        items = (
            await self._session.scalars(
                select(TestPlanItem).where(TestPlanItem.test_plan_id == run.test_plan_id)
            )
        ).all()
        service = TestPlanService(self._session)
        refs: set[tuple[UUID, int]] = set()
        for item in items:
            expanded = await service._expand_plan_item(run.project_id, item)
            refs.update((value.workflow_id, value.workflow_version) for value in expanded)
        return refs

    async def _published_target(
        self, project_id: UUID, workflow_id: UUID, refs: set[tuple[UUID, int]]
    ) -> RegressionWorkflowEvidence:
        workflow = await self._session.scalar(
            select(Workflow)
            .where(Workflow.id == workflow_id, Workflow.project_id == project_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if workflow is None:
            raise _coverage_error("TARGET_MISSING", "受影响流程已不存在")
        definition = WorkflowDefinition.model_validate(workflow.draft_definition)
        pinned = await WorkflowService(self._session)._pin_api_versions(definition)
        expected = pinned.model_dump(mode="json", exclude_none=True)
        versions = (
            await self._session.scalars(
                select(WorkflowVersion)
                .where(WorkflowVersion.workflow_id == workflow.id)
                .order_by(WorkflowVersion.version.desc())
            )
        ).all()
        candidate = next(
            (
                version
                for version in versions
                if (workflow.id, version.version) in refs
                and WorkflowDefinition.model_validate(version.definition).model_dump(
                    mode="json", exclude_none=True
                )
                == expected
            ),
            None,
        )
        if candidate is None:
            raise _coverage_error("PLAN_GAP", "请先发布受影响流程当前草稿并将该版本加入测试计划")
        return RegressionWorkflowEvidence(
            workflow_id=workflow.id,
            draft_revision=workflow.draft_revision,
            workflow_version=candidate.version,
            workflow_version_id=candidate.id,
            fingerprint=candidate.fingerprint,
        )


def _coverage_error(code: str, message: str) -> AppError:
    return AppError(code=f"REGRESSION_MAINTENANCE_{code}", message=message, status_code=409)
