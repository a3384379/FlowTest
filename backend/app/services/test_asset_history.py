from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import User
from app.models.tasking import TestPlanRun, TestPlanRunItem
from app.repositories.test_asset_history import TestAssetHistoryRepository
from app.schemas.tasking import (
    TestPlanRunDetailResponse,
    TestPlanRunItemResponse,
    TestPlanRunResponse,
)
from app.schemas.test_assets import TestCaseRunHistoryResponse, TestSuiteLatestRunResponse
from app.services.projects import ProjectService
from app.services.test_assets import TestCaseService, TestSuiteService


class TestAssetHistoryReader(Protocol):
    async def list_case_runs(
        self, *, project_id: UUID, case_id: UUID, version: int | None, offset: int, limit: int
    ) -> tuple[list[TestCaseRunHistoryResponse], int]: ...
    async def list_suite_runs(
        self, *, project_id: UUID, suite_id: UUID, version: int | None, offset: int, limit: int
    ) -> tuple[list[tuple[TestPlanRun, list[TestPlanRunItem]]], int]: ...
    async def latest_suite_runs(
        self, *, project_id: UUID, suite_ids: list[UUID]
    ) -> list[tuple[UUID, TestPlanRun, list[TestPlanRunItem]]]: ...


class TestAssetHistoryService:
    def __init__(self, session: AsyncSession, reader: TestAssetHistoryReader | None = None) -> None:
        self._session = session
        self._reader = reader or TestAssetHistoryRepository(session)

    async def case_runs(
        self,
        *,
        actor: User,
        project_id: UUID,
        case_id: UUID,
        version: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[TestCaseRunHistoryResponse], int]:
        await TestCaseService(self._session).get(
            actor=actor, project_id=project_id, case_id=case_id
        )
        return await self._reader.list_case_runs(
            project_id=project_id,
            case_id=case_id,
            version=version,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def suite_runs(
        self,
        *,
        actor: User,
        project_id: UUID,
        suite_id: UUID,
        version: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[TestPlanRunDetailResponse], int]:
        await TestSuiteService(self._session).get(
            actor=actor, project_id=project_id, suite_id=suite_id
        )
        rows, total = await self._reader.list_suite_runs(
            project_id=project_id,
            suite_id=suite_id,
            version=version,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return [_suite_detail(run, items) for run, items in rows], total

    async def latest_suite_runs(
        self, *, actor: User, project_id: UUID, suite_ids: list[UUID]
    ) -> list[TestSuiteLatestRunResponse]:
        await ProjectService(self._session).authorize(
            actor=actor, project_id=project_id, editing=False
        )
        latest = await self._reader.latest_suite_runs(project_id=project_id, suite_ids=suite_ids)
        return [
            TestSuiteLatestRunResponse(suite_id=suite_id, detail=_suite_detail(run, items))
            for suite_id, run, items in latest
        ]


def _suite_detail(run: TestPlanRun, items: list[TestPlanRunItem]) -> TestPlanRunDetailResponse:
    return TestPlanRunDetailResponse(
        run=TestPlanRunResponse.model_validate(run),
        items=[TestPlanRunItemResponse.model_validate(item) for item in items],
    )
