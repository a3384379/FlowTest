from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import case, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.domain.asset_catalog import AssetCatalogRun, AssetCatalogScope
from app.models.test_assets import (
    TestCase,
    TestCaseVersion,
    TestSuite,
    TestSuiteVersion,
    TestSuiteVersionItem,
)
from app.repositories.asset_catalog import (
    apply_catalog_scope,
    case_catalog_page,
    catalog_order,
    catalog_run,
    latest_case_catalog,
    latest_suite_catalog,
)
from app.repositories.catalog_paging import ranked_catalog_page
from app.schemas.test_assets import AssetDirectoryCountsResponse, AssetFolderCount

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
        folder_id: UUID | None = None,
        unfiled: bool = False,
        scope: AssetCatalogScope | None = None,
    ) -> tuple[list[TestCase], int, dict[UUID, AssetCatalogRun]]:
        filters = self._catalog_filters(TestCase, project_id, search, tag, folder_id, unfiled)
        if is_template is not None:
            filters.append(TestCase.is_template == is_template)
        selected = scope or AssetCatalogScope()
        latest = latest_case_catalog(project_id)
        query = apply_catalog_scope(
            select(TestCase).where(*filters),
            model=TestCase,
            project_id=project_id,
            scope=selected,
            latest=latest,
        )
        page = case_catalog_page(query, latest, selected, offset, limit)
        rows = (
            await self._session.execute(
                select(TestCase, page)
                .select_from(page)
                .outerjoin(TestCase, TestCase.id == page.c.item_id)
                .order_by(page.c.position)
            )
        ).all()
        items: list[TestCase] = []
        runs: dict[UUID, AssetCatalogRun] = {}
        for row in rows:
            model = row[0]
            if model is not None:
                items.append(model)
                if row._mapping["asset_key"] is not None:
                    runs[model.id] = catalog_run(row._mapping)
        return items, int(rows[0]._mapping["total"]), runs

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
        folder_id: UUID | None = None,
        unfiled: bool = False,
        scope: AssetCatalogScope | None = None,
    ) -> tuple[list[TestSuite], int]:
        filters = self._catalog_filters(TestSuite, project_id, search, tag, folder_id, unfiled)
        selected = scope or AssetCatalogScope()
        latest = latest_suite_catalog(project_id) if selected.order == "latest_run_desc" else None
        query = apply_catalog_scope(
            select(TestSuite).where(*filters),
            model=TestSuite,
            project_id=project_id,
            scope=selected,
            latest=latest,
        )
        ranked = (
            query.order_by(None)
            .with_only_columns(
                TestSuite.id.label("item_id"),
                func.row_number()
                .over(order_by=catalog_order(TestSuite, latest, selected))
                .label("position"),
            )
            .cte()
        )
        page = ranked_catalog_page(ranked, offset, limit)
        rows = (
            await self._session.execute(
                select(TestSuite, page.c.total)
                .select_from(page)
                .outerjoin(TestSuite, TestSuite.id == page.c.item_id)
                .order_by(page.c.position)
            )
        ).all()
        return [row[0] for row in rows if row[0] is not None], int(rows[0][1])

    def _catalog_filters(
        self,
        model: type[TestCase] | type[TestSuite],
        project_id: UUID,
        search: str | None,
        tag: str | None,
        folder_id: UUID | None,
        unfiled: bool,
    ) -> list[ColumnElement[bool]]:
        filters = [model.project_id == project_id, model.archived_at.is_(None)]
        if search:
            pattern = f"%{search}%"
            filters.append(or_(model.name.ilike(pattern), model.description.ilike(pattern)))
        if tag:
            filters.append(self._tag_filter(model.tags, tag))
        if folder_id is not None:
            filters.append(model.folder_id == folder_id)
        if unfiled:
            filters.append(model.folder_id.is_(None))
        return filters

    def _tag_filter(
        self, column: InstrumentedAttribute[list[str]], tag: str
    ) -> ColumnElement[bool]:
        if self._session.get_bind().dialect.name == "sqlite":
            values = func.json_each(column).table_valued("value")
            return select(literal(1)).select_from(values).where(values.c.value == tag).exists()
        return cast(column, JSONB).contains([tag])

    async def directory_counts(
        self,
        *,
        project_id: UUID,
        search: str | None,
        tag: str | None,
        scope: AssetCatalogScope | None = None,
    ) -> AssetDirectoryCountsResponse:
        case_query = (
            apply_catalog_scope(
                select(TestCase).where(
                    *self._catalog_filters(TestCase, project_id, search, tag, None, False)
                ),
                model=TestCase,
                project_id=project_id,
                scope=scope or AssetCatalogScope(),
            )
            .order_by(None)
            .subquery()
        )
        case_rows = await self._session.execute(
            select(
                case_query.c.folder_id,
                func.count(),
                func.sum(case((case_query.c.current_version.is_not(None), 1), else_=0)),
            ).group_by(case_query.c.folder_id)
        )
        case_groups = case_rows.all()
        cases = {folder_id: int(count) for folder_id, count, _published in case_groups}
        # Aggregates retain one row per folder, rather than materializing assets.
        published = sum(int(value or 0) for _folder, _count, value in case_groups)
        suite_query = (
            apply_catalog_scope(
                select(TestSuite).where(
                    *self._catalog_filters(TestSuite, project_id, search, tag, None, False)
                ),
                model=TestSuite,
                project_id=project_id,
                scope=scope or AssetCatalogScope(),
            )
            .order_by(None)
            .subquery()
        )
        suite_rows = await self._session.execute(
            select(suite_query.c.folder_id, func.count()).group_by(suite_query.c.folder_id)
        )
        suites = {folder_id: int(count) for folder_id, count in suite_rows}
        folder_ids = sorted(
            {folder_id for folder_id in (*cases, *suites) if folder_id is not None}, key=str
        )
        return AssetDirectoryCountsResponse(
            case_total=sum(cases.values()),
            suite_total=sum(suites.values()),
            published_case_total=int(published or 0),
            unfiled_cases=cases.get(None, 0),
            unfiled_suites=suites.get(None, 0),
            folders=[
                AssetFolderCount(
                    folder_id=folder_id,
                    cases=cases.get(folder_id, 0),
                    suites=suites.get(folder_id, 0),
                )
                for folder_id in folder_ids
            ],
        )

    async def suite_name_exists(
        self, *, project_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> bool:
        query = select(TestSuite.id).where(
            TestSuite.project_id == project_id, TestSuite.name == name
        )
        if excluding_id is not None:
            query = query.where(TestSuite.id != excluding_id)
        return await self._session.scalar(query) is not None
