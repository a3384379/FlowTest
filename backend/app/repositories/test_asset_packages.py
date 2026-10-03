from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import Folder
from app.models.api_assets import Environment
from app.models.test_assets import TestCase, TestCaseVersion, TestSuite, TestSuiteVersion
from app.models.workflows import Workflow, WorkflowVersion
from app.schemas.test_assets import TestAssetKind


class TestAssetPackageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def asset(
        self, project_id: UUID, kind: TestAssetKind, asset_id: UUID
    ) -> TestCase | TestSuite | None:
        model = TestCase if kind == "case" else TestSuite
        result = await self._session.scalar(
            select(model)
            .where(model.project_id == project_id, model.id == asset_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return cast(TestCase | TestSuite | None, result)

    async def named(
        self, project_id: UUID, kind: TestAssetKind, name: str
    ) -> TestCase | TestSuite | None:
        model = TestCase if kind == "case" else TestSuite
        result = await self._session.scalar(
            select(model)
            .where(model.project_id == project_id, model.name == name)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return cast(TestCase | TestSuite | None, result)

    async def case_versions(self, case_id: UUID) -> list[TestCaseVersion]:
        return list(
            (
                await self._session.scalars(
                    select(TestCaseVersion)
                    .where(TestCaseVersion.test_case_id == case_id)
                    .order_by(TestCaseVersion.version)
                )
            ).all()
        )

    async def suite_versions(self, suite_id: UUID) -> list[TestSuiteVersion]:
        return list(
            (
                await self._session.scalars(
                    select(TestSuiteVersion)
                    .where(TestSuiteVersion.test_suite_id == suite_id)
                    .order_by(TestSuiteVersion.version)
                )
            ).all()
        )

    async def workflow(self, project_id: UUID, workflow_id: UUID) -> Workflow | None:
        result = await self._session.scalar(
            select(Workflow)
            .where(
                Workflow.project_id == project_id,
                Workflow.id == workflow_id,
                Workflow.archived_at.is_(None),
            )
            .with_for_update()
        )
        return result

    async def workflow_version(self, workflow_id: UUID, version: int) -> WorkflowVersion | None:
        result = await self._session.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow_id, WorkflowVersion.version == version
            )
        )
        return result

    async def environment(self, project_id: UUID, environment_id: UUID) -> Environment | None:
        result = await self._session.scalar(
            select(Environment)
            .where(
                Environment.project_id == project_id,
                Environment.id == environment_id,
                Environment.archived_at.is_(None),
            )
            .with_for_update()
        )
        return result

    async def folder(self, project_id: UUID, folder_id: UUID) -> Folder | None:
        result = await self._session.scalar(
            select(Folder)
            .where(Folder.project_id == project_id, Folder.id == folder_id)
            .with_for_update()
        )
        return result
