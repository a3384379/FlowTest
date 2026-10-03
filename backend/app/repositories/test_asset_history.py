"""Query asset-owned execution history without a project-wide recent-run window."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.tasking import TestPlanRun, TestPlanRunItem
from app.models.workflows import WorkflowExecution, WorkflowVersion
from app.schemas.test_assets import TestCaseRunHistoryResponse


class TestAssetHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_case_runs(
        self, *, project_id: UUID, case_id: UUID, version: int | None, offset: int, limit: int
    ) -> tuple[list[TestCaseRunHistoryResponse], int]:
        history = union_all(
            self._case_executions(project_id, case_id),
            self._legacy_and_pending_case_runs(project_id, case_id),
        ).subquery()
        filters = [] if version is None else [history.c.case_version == version]
        query = select(history).where(*filters)
        total = await self._session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await self._session.execute(
            query.order_by(
                func.coalesce(history.c.started_at, history.c.created_at).desc(),
                history.c.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return [TestCaseRunHistoryResponse.model_validate(row) for row in rows.mappings()], int(
            total or 0
        )

    @staticmethod
    def _case_executions(
        project_id: UUID, case_id: UUID
    ) -> Select[
        tuple[
            UUID,
            UUID,
            int | None,
            UUID | None,
            int,
            UUID,
            str,
            str | None,
            datetime,
            datetime,
            UUID,
            UUID,
        ]
    ]:
        legacy_item = (
            select(TestPlanRunItem.id)
            .join(TestPlanRun, TestPlanRun.id == TestPlanRunItem.test_plan_run_id)
            .where(
                TestPlanRun.project_id == project_id,
                TestPlanRunItem.target_type == "case",
                TestPlanRunItem.target_id == case_id,
                TestPlanRunItem.workflow_execution_id == WorkflowExecution.id,
            )
            .order_by(TestPlanRunItem.id)
            .limit(1)
            .correlate(WorkflowExecution)
            .scalar_subquery()
        )
        return (
            select(
                WorkflowExecution.id.label("id"),
                WorkflowExecution.id.label("execution_id"),
                WorkflowExecution.source_case_version.label("case_version"),
                WorkflowExecution.workflow_id.label("workflow_id"),
                WorkflowVersion.version.label("workflow_version"),
                WorkflowExecution.environment_id.label("environment_id"),
                WorkflowExecution.status.label("status"),
                WorkflowExecution.source_trigger.label("source"),
                WorkflowExecution.started_at.label("started_at"),
                WorkflowExecution.created_at.label("created_at"),
                TestPlanRun.id.label("plan_run_id"),
                TestPlanRun.test_plan_id.label("plan_id"),
            )
            .join(WorkflowVersion, WorkflowVersion.id == WorkflowExecution.workflow_version_id)
            .outerjoin(
                TestPlanRunItem,
                TestPlanRunItem.id
                == func.coalesce(WorkflowExecution.source_plan_run_item_id, legacy_item),
            )
            .outerjoin(
                TestPlanRun,
                and_(
                    TestPlanRun.id == TestPlanRunItem.test_plan_run_id,
                    TestPlanRun.project_id == project_id,
                ),
            )
            .where(
                WorkflowExecution.project_id == project_id,
                WorkflowExecution.source_case_id == case_id,
                WorkflowExecution.parent_execution_id.is_(None),
            )
        )

    @staticmethod
    def _legacy_and_pending_case_runs(
        project_id: UUID, case_id: UUID
    ) -> Select[tuple[UUID, UUID, int, UUID, int, UUID, str, str, datetime, datetime, UUID, UUID]]:
        return (
            select(
                func.coalesce(WorkflowExecution.id, TestPlanRunItem.id).label("id"),
                WorkflowExecution.id.label("execution_id"),
                TestPlanRunItem.target_version.label("case_version"),
                TestPlanRunItem.workflow_id.label("workflow_id"),
                TestPlanRunItem.workflow_version.label("workflow_version"),
                TestPlanRunItem.environment_id.label("environment_id"),
                func.coalesce(WorkflowExecution.status, TestPlanRunItem.status).label("status"),
                literal("plan").label("source"),
                WorkflowExecution.started_at.label("started_at"),
                TestPlanRun.created_at.label("created_at"),
                TestPlanRun.id.label("plan_run_id"),
                TestPlanRun.test_plan_id.label("plan_id"),
            )
            .select_from(TestPlanRunItem)
            .join(TestPlanRun, TestPlanRun.id == TestPlanRunItem.test_plan_run_id)
            .outerjoin(
                WorkflowExecution, WorkflowExecution.id == TestPlanRunItem.workflow_execution_id
            )
            .where(
                TestPlanRun.project_id == project_id,
                TestPlanRunItem.target_type == "case",
                TestPlanRunItem.target_id == case_id,
                or_(
                    WorkflowExecution.id.is_(None),
                    and_(
                        WorkflowExecution.project_id == project_id,
                        WorkflowExecution.source_case_id.is_(None),
                        WorkflowExecution.parent_execution_id.is_(None),
                    ),
                ),
            )
        )

    async def list_suite_runs(
        self, *, project_id: UUID, suite_id: UUID, version: int | None, offset: int, limit: int
    ) -> tuple[list[tuple[TestPlanRun, list[TestPlanRunItem]]], int]:
        filters = self._suite_filters(project_id, suite_id, version)
        matches = (
            select(TestPlanRunItem.test_plan_run_id)
            .join(TestPlanRun, TestPlanRun.id == TestPlanRunItem.test_plan_run_id)
            .where(*filters)
            .distinct()
        )
        total = await self._session.scalar(select(func.count()).select_from(matches.subquery()))
        runs = list(
            (
                await self._session.scalars(
                    select(TestPlanRun)
                    .where(TestPlanRun.id.in_(matches))
                    .order_by(TestPlanRun.created_at.desc(), TestPlanRun.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        if not runs:
            return [], int(total or 0)
        items = (
            await self._session.scalars(
                select(TestPlanRunItem)
                .join(TestPlanRun, TestPlanRun.id == TestPlanRunItem.test_plan_run_id)
                .where(*filters, TestPlanRun.id.in_([run.id for run in runs]))
                .order_by(TestPlanRunItem.position, TestPlanRunItem.id)
            )
        ).all()
        grouped: dict[UUID, list[TestPlanRunItem]] = {run.id: [] for run in runs}
        for item in items:
            grouped[item.test_plan_run_id].append(item)
        return [(run, grouped[run.id]) for run in runs], int(total or 0)

    @staticmethod
    def _suite_filters(
        project_id: UUID, suite_id: UUID, version: int | None
    ) -> list[ColumnElement[bool]]:
        filters = [
            TestPlanRun.project_id == project_id,
            TestPlanRunItem.target_type == "case",
            TestPlanRunItem.target_snapshot["source_suite"]["id"].as_string() == str(suite_id),
        ]
        if version is not None:
            filters.append(
                TestPlanRunItem.target_snapshot["source_suite"]["version"].as_integer() == version
            )
        return filters

    async def latest_suite_runs(
        self, *, project_id: UUID, suite_ids: list[UUID]
    ) -> list[tuple[UUID, TestPlanRun, list[TestPlanRunItem]]]:
        suite = TestPlanRunItem.target_snapshot["source_suite"]["id"].as_string()
        ranked = (
            select(
                suite.label("suite_id"),
                TestPlanRun.id.label("run_id"),
                func.row_number()
                .over(
                    partition_by=suite,
                    order_by=(TestPlanRun.created_at.desc(), TestPlanRun.id.desc()),
                )
                .label("rank"),
            )
            .join(TestPlanRun, TestPlanRun.id == TestPlanRunItem.test_plan_run_id)
            .where(
                TestPlanRun.project_id == project_id,
                TestPlanRunItem.target_type == "case",
                suite.in_([str(item) for item in suite_ids]),
            )
            .subquery()
        )
        rows = await self._session.execute(
            select(ranked.c.suite_id, TestPlanRun, TestPlanRunItem)
            .select_from(ranked)
            .join(TestPlanRun, TestPlanRun.id == ranked.c.run_id)
            .join(TestPlanRunItem, TestPlanRunItem.test_plan_run_id == TestPlanRun.id)
            .where(
                ranked.c.rank == 1,
                suite == ranked.c.suite_id,
                TestPlanRunItem.target_type == "case",
            )
            .order_by(
                TestPlanRun.created_at.desc(), TestPlanRun.id.desc(), TestPlanRunItem.position
            )
        )
        grouped: dict[UUID, tuple[TestPlanRun, list[TestPlanRunItem]]] = {}
        for suite_id, run, item in rows:
            asset_id = UUID(suite_id)
            if asset_id not in grouped:
                grouped[asset_id] = (run, [])
            grouped[asset_id][1].append(item)
        return [(asset_id, run, items) for asset_id, (run, items) in grouped.items()]
