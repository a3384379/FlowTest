from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tasking import TestPlan, TestPlanItem, TestPlanRun, TestPlanRunItem
from app.models.test_assets import TestCase, TestSuite, TestSuiteVersion, TestSuiteVersionItem
from app.models.workflows import WorkflowExecution
from app.schemas.test_assets import AssetReference, TestAssetKind, TestSuiteDefinitionInput


class TestAssetDeletionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def selected_for_update(
        self, *, project_id: UUID, kind: TestAssetKind, asset_ids: list[UUID]
    ) -> list[TestCase | TestSuite]:
        if kind == "case":
            return list(
                (
                    await self._session.scalars(
                        select(TestCase)
                        .where(TestCase.project_id == project_id, TestCase.id.in_(asset_ids))
                        .order_by(TestCase.id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).all()
            )
        return list(
            (
                await self._session.scalars(
                    select(TestSuite)
                    .where(TestSuite.project_id == project_id, TestSuite.id.in_(asset_ids))
                    .order_by(TestSuite.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )

    async def references(
        self, *, project_id: UUID, kind: TestAssetKind, asset_id: UUID
    ) -> list[AssetReference]:
        plan_rows = await self._session.execute(
            select(TestPlan.id, TestPlan.name, TestPlanItem.target_version)
            .join(TestPlanItem, TestPlanItem.test_plan_id == TestPlan.id)
            .where(
                TestPlan.project_id == project_id,
                TestPlanItem.target_type == kind,
                TestPlanItem.target_id == asset_id,
            )
            .distinct()
        )
        refs = [
            AssetReference(kind="test_plan", id=plan_id, name=name, version=version)
            for plan_id, name, version in plan_rows
        ]
        refs.extend(await self._active_runs(project_id, kind, asset_id))
        if kind == "case":
            refs.extend(await self._suite_plan_references(project_id, asset_id))
            refs.extend(await self._suite_references(project_id, asset_id))
        return refs

    async def _suite_plan_references(self, project_id: UUID, case_id: UUID) -> list[AssetReference]:
        rows = await self._session.execute(
            select(TestPlan.id, TestPlan.name, TestPlanItem.target_version)
            .join(TestPlanItem, TestPlanItem.test_plan_id == TestPlan.id)
            .join(
                TestSuiteVersion,
                (TestSuiteVersion.test_suite_id == TestPlanItem.target_id)
                & (TestSuiteVersion.version == TestPlanItem.target_version),
            )
            .join(
                TestSuiteVersionItem,
                TestSuiteVersionItem.test_suite_version_id == TestSuiteVersion.id,
            )
            .where(
                TestPlan.project_id == project_id,
                TestPlanItem.target_type == "suite",
                TestSuiteVersionItem.test_case_id == case_id,
            )
            .distinct()
        )
        return [
            AssetReference(kind="test_plan", id=plan_id, name=name, version=version)
            for plan_id, name, version in rows
        ]

    async def _active_runs(
        self, project_id: UUID, kind: TestAssetKind, asset_id: UUID
    ) -> list[AssetReference]:
        item_filter = (
            TestPlanRunItem.target_id == asset_id
            if kind == "case"
            else TestPlanRunItem.target_snapshot["source_suite"]["id"].as_string() == str(asset_id)
        )
        plan_rows = (
            await self._session.scalars(
                select(TestPlanRun.id)
                .join(TestPlanRunItem, TestPlanRunItem.test_plan_run_id == TestPlanRun.id)
                .where(
                    TestPlanRun.project_id == project_id,
                    TestPlanRun.status.in_(("queued", "running")),
                    TestPlanRunItem.target_type == "case",
                    item_filter,
                )
                .distinct()
            )
        ).all()
        refs = [
            AssetReference(kind="execution", id=run_id, name="活动计划运行") for run_id in plan_rows
        ]
        if kind == "suite":
            return refs
        legacy = (
            select(TestPlanRunItem.workflow_execution_id)
            .join(TestPlanRun, TestPlanRun.id == TestPlanRunItem.test_plan_run_id)
            .where(
                TestPlanRun.project_id == project_id,
                TestPlanRunItem.target_type == "case",
                TestPlanRunItem.target_id == asset_id,
            )
        )
        executions = (
            await self._session.scalars(
                select(WorkflowExecution.id).where(
                    WorkflowExecution.project_id == project_id,
                    WorkflowExecution.status.in_(("queued", "running")),
                    or_(
                        WorkflowExecution.source_case_id == asset_id,
                        WorkflowExecution.id.in_(legacy),
                    ),
                )
            )
        ).all()
        refs.extend(
            AssetReference(kind="execution", id=execution_id, name="活动用例运行")
            for execution_id in executions
        )
        return refs

    async def _suite_references(self, project_id: UUID, case_id: UUID) -> list[AssetReference]:
        published = await self._session.execute(
            select(TestSuite.id, TestSuite.name, TestSuiteVersion.version)
            .join(TestSuiteVersion, TestSuiteVersion.test_suite_id == TestSuite.id)
            .join(
                TestSuiteVersionItem,
                TestSuiteVersionItem.test_suite_version_id == TestSuiteVersion.id,
            )
            .where(
                TestSuite.project_id == project_id,
                TestSuite.archived_at.is_(None),
                TestSuiteVersionItem.test_case_id == case_id,
            )
            .distinct()
        )
        refs = [
            AssetReference(kind="test_suite", id=suite_id, name=name, version=version)
            for suite_id, name, version in published
        ]
        suites = (
            await self._session.scalars(
                select(TestSuite).where(
                    TestSuite.project_id == project_id, TestSuite.archived_at.is_(None)
                )
            )
        ).all()
        for suite in suites:
            draft = TestSuiteDefinitionInput.model_validate(suite.draft_definition)
            if any(item.test_case_id == case_id for item in draft.items):
                refs.append(AssetReference(kind="test_suite", id=suite.id, name=suite.name))
        return refs
