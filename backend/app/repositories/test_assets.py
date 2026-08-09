from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_assets import (
    TestCase,
    TestCaseVersion,
    TestSuite,
    TestSuiteVersion,
    TestSuiteVersionItem,
)

TestAssetEntity = TestCase | TestCaseVersion | TestSuite | TestSuiteVersion | TestSuiteVersionItem


class TestAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: TestAssetEntity) -> None:
        self._session.add(entity)

    def add_all(self, entities: Sequence[TestAssetEntity]) -> None:
        self._session.add_all(entities)

    async def get_case(self, case_id: UUID) -> TestCase | None:
        return await self._session.get(TestCase, case_id)

    async def get_case_for_update(self, case_id: UUID) -> TestCase | None:
        result = await self._session.execute(
            select(TestCase)
            .where(TestCase.id == case_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def find_case_version(self, case_id: UUID, version: int) -> TestCaseVersion | None:
        result = await self._session.execute(
            select(TestCaseVersion).where(
                TestCaseVersion.test_case_id == case_id, TestCaseVersion.version == version
            )
        )
        return result.scalar_one_or_none()

    async def list_case_versions(self, case_id: UUID) -> list[TestCaseVersion]:
        return list(
            (
                await self._session.scalars(
                    select(TestCaseVersion)
                    .where(TestCaseVersion.test_case_id == case_id)
                    .order_by(TestCaseVersion.version.desc())
                )
            ).all()
        )

    async def list_cases(
        self,
        *,
        project_id: UUID,
        search: str | None,
        tag: str | None,
        is_template: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[TestCase], int]:
        filters = [TestCase.project_id == project_id]
        if search:
            pattern = f"%{search}%"
            filters.append(or_(TestCase.name.ilike(pattern), TestCase.description.ilike(pattern)))
        if is_template is not None:
            filters.append(TestCase.is_template == is_template)
        query = select(TestCase).where(*filters)
        if tag:
            matches = [
                item for item in (await self._session.scalars(query)).all() if tag in item.tags
            ]
            return matches[offset : offset + limit], len(matches)
        items = list(
            (
                await self._session.scalars(
                    query.order_by(TestCase.updated_at.desc()).offset(offset).limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(TestCase).where(*filters)
        )
        return items, int(total or 0)

    async def case_name_exists(
        self, *, project_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> bool:
        query = select(TestCase.id).where(TestCase.project_id == project_id, TestCase.name == name)
        if excluding_id is not None:
            query = query.where(TestCase.id != excluding_id)
        return await self._session.scalar(query) is not None

    async def get_suite(self, suite_id: UUID) -> TestSuite | None:
        return await self._session.get(TestSuite, suite_id)

    async def get_suite_for_update(self, suite_id: UUID) -> TestSuite | None:
        result = await self._session.execute(
            select(TestSuite)
            .where(TestSuite.id == suite_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def find_suite_version(self, suite_id: UUID, version: int) -> TestSuiteVersion | None:
        result = await self._session.execute(
            select(TestSuiteVersion).where(
                TestSuiteVersion.test_suite_id == suite_id,
                TestSuiteVersion.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def list_suite_versions(self, suite_id: UUID) -> list[TestSuiteVersion]:
        return list(
            (
                await self._session.scalars(
                    select(TestSuiteVersion)
                    .where(TestSuiteVersion.test_suite_id == suite_id)
                    .order_by(TestSuiteVersion.version.desc())
                )
            ).all()
        )

    async def list_suite_items(self, version_id: UUID) -> list[TestSuiteVersionItem]:
        return list(
            (
                await self._session.scalars(
                    select(TestSuiteVersionItem)
                    .where(TestSuiteVersionItem.test_suite_version_id == version_id)
                    .order_by(TestSuiteVersionItem.position)
                )
            ).all()
        )

    async def list_suites(
        self,
        *,
        project_id: UUID,
        search: str | None,
        tag: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[TestSuite], int]:
        filters = [TestSuite.project_id == project_id]
        if search:
            pattern = f"%{search}%"
            filters.append(or_(TestSuite.name.ilike(pattern), TestSuite.description.ilike(pattern)))
        query = select(TestSuite).where(*filters)
        if tag:
            matches = [
                item for item in (await self._session.scalars(query)).all() if tag in item.tags
            ]
            return matches[offset : offset + limit], len(matches)
        items = list(
            (
                await self._session.scalars(
                    query.order_by(TestSuite.updated_at.desc()).offset(offset).limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(TestSuite).where(*filters)
        )
        return items, int(total or 0)

    async def suite_name_exists(
        self, *, project_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> bool:
        query = select(TestSuite.id).where(
            TestSuite.project_id == project_id, TestSuite.name == name
        )
        if excluding_id is not None:
            query = query.where(TestSuite.id != excluding_id)
        return await self._session.scalar(query) is not None
