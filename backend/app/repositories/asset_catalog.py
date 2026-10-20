"""Read the latest asset-owned run before applying catalog filters."""

from datetime import UTC, datetime
from typing import Literal
from typing import cast as type_cast
from uuid import UUID

from sqlalchemy import (
    Select,
    SQLColumnExpression,
    String,
    and_,
    case,
    cast,
    exists,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from app.domain.asset_catalog import AssetCatalogEnvironment, AssetCatalogRun, AssetCatalogScope
from app.models.api_assets import Environment
from app.models.tasking import TestPlanRun, TestPlanRunItem
from app.models.test_assets import TestCase, TestSuite
from app.models.workflows import WorkflowExecution
from app.repositories.catalog_paging import ranked_catalog_page


def apply_catalog_scope[CatalogModel: (TestCase, TestSuite)](
    query: Select[tuple[CatalogModel]],
    *,
    model: type[CatalogModel],
    project_id: UUID,
    scope: AssetCatalogScope,
    latest: Subquery | None = None,
) -> Select[tuple[CatalogModel]]:
    if scope.publication == "published":
        query = query.where(model.current_version.is_not(None))
    elif scope.publication == "unpublished":
        query = query.where(model.current_version.is_(None))
    if (
        latest is not None
        or scope.latest_result
        or scope.environment_id
        or scope.order == "latest_run_desc"
    ):
        latest = (
            latest
            if latest is not None
            else (
                latest_case_catalog(project_id)
                if model is TestCase
                else latest_suite_catalog(project_id)
            )
        )
        query = query.outerjoin(latest, latest.c.asset_key == normalized_asset_id(model.id))
        query = _filter_latest(query, model, project_id, latest, scope)
    return _order_catalog(query, model, latest, scope)


def case_catalog_page(
    query: Select[tuple[TestCase]],
    latest: Subquery,
    scope: AssetCatalogScope,
    offset: int,
    limit: int,
) -> Subquery:
    orders = catalog_order(TestCase, latest, scope)
    filtered = (
        query.order_by(None)
        .with_only_columns(
            TestCase.id.label("item_id"),
            latest.c.asset_key,
            latest.c.status,
            latest.c.occurred_at,
            latest.c.execution_id,
            latest.c.plan_id,
            latest.c.plan_run_id,
            latest.c.asset_version,
            latest.c.source,
            func.row_number().over(order_by=orders).label("position"),
        )
        .cte("filtered_catalog_cases")
    )
    return ranked_catalog_page(filtered, offset, limit)


def catalog_order[CatalogModel: (TestCase, TestSuite)](
    model: type[CatalogModel], latest: Subquery | None, scope: AssetCatalogScope
) -> tuple[SQLColumnExpression[str] | SQLColumnExpression[datetime], SQLColumnExpression[UUID]]:
    if scope.order == "name_asc":
        return model.name.asc(), model.id.asc()
    if scope.order == "name_desc":
        return model.name.desc(), model.id.desc()
    if scope.order == "latest_run_desc" and latest is not None:
        return latest.c.occurred_at.desc().nulls_last(), model.id.desc()
    return model.updated_at.desc(), model.id.desc()


def _filter_latest[CatalogModel: (TestCase, TestSuite)](
    query: Select[tuple[CatalogModel]],
    model: type[CatalogModel],
    project_id: UUID,
    latest: Subquery,
    scope: AssetCatalogScope,
) -> Select[tuple[CatalogModel]]:
    if scope.latest_result == "unrun":
        query = query.where(latest.c.asset_key.is_(None))
    elif scope.latest_result:
        query = query.where(latest.c.status == scope.latest_result)
    if scope.environment_id is not None:
        match = (
            latest.c.environment_id == scope.environment_id
            if model is TestCase
            else _suite_environment_match(project_id, latest, scope.environment_id)
        )
        query = query.where(match)
    return query


def _suite_environment_match(
    project_id: UUID, latest: Subquery, environment_id: UUID
) -> ColumnElement[bool]:
    return exists(
        select(TestPlanRunItem.id)
        .outerjoin(
            WorkflowExecution,
            and_(
                WorkflowExecution.id == TestPlanRunItem.workflow_execution_id,
                WorkflowExecution.project_id == project_id,
            ),
        )
        .where(
            TestPlanRunItem.test_plan_run_id == latest.c.plan_run_id,
            TestPlanRunItem.target_type == "case",
            suite_item_key() == latest.c.asset_key,
            func.coalesce(WorkflowExecution.environment_id, TestPlanRunItem.environment_id)
            == environment_id,
        )
        .correlate(latest)
    )


def _order_catalog[CatalogModel: (TestCase, TestSuite)](
    query: Select[tuple[CatalogModel]],
    model: type[CatalogModel],
    latest: Subquery | None,
    scope: AssetCatalogScope,
) -> Select[tuple[CatalogModel]]:
    return query.order_by(*catalog_order(model, latest, scope))


class AssetCatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def environment_options(
        self, *, project_id: UUID, search: str, selected_id: UUID | None, offset: int, limit: int
    ) -> tuple[list[AssetCatalogEnvironment], int]:
        case_environments = select(WorkflowExecution.environment_id).where(
            WorkflowExecution.project_id == project_id,
            WorkflowExecution.source_case_id.is_not(None),
            WorkflowExecution.parent_execution_id.is_(None),
        )
        plan_environments = (
            select(func.coalesce(WorkflowExecution.environment_id, TestPlanRunItem.environment_id))
            .select_from(TestPlanRunItem)
            .join(TestPlanRun, TestPlanRun.id == TestPlanRunItem.test_plan_run_id)
            .outerjoin(
                WorkflowExecution,
                and_(
                    WorkflowExecution.id == TestPlanRunItem.workflow_execution_id,
                    WorkflowExecution.project_id == project_id,
                ),
            )
            .where(TestPlanRun.project_id == project_id, TestPlanRunItem.target_type == "case")
        )
        query = select(Environment.id, Environment.name).where(
            Environment.project_id == project_id,
            or_(Environment.id.in_(case_environments), Environment.id.in_(plan_environments)),
        )
        if search:
            query = query.where(Environment.name.icontains(search, autoescape=True))
        if selected_id is not None:
            query = query.where(Environment.id == selected_id)
        total = await self._session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await self._session.execute(
            query.order_by(Environment.name, Environment.id).offset(offset).limit(limit)
        )
        return [AssetCatalogEnvironment(identifier, name) for identifier, name in rows], int(
            total or 0
        )


def catalog_run(row: RowMapping) -> AssetCatalogRun:
    occurred_at: datetime = row["occurred_at"]
    if occurred_at.utcoffset() is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    return AssetCatalogRun(
        status=row["status"],
        occurred_at=occurred_at,
        execution_id=row["execution_id"],
        plan_id=row["plan_id"],
        plan_run_id=row["plan_run_id"],
        asset_version=row["asset_version"],
        source=type_cast(Literal["direct", "plan"], row["source"]),
    )


def latest_case_catalog(project_id: UUID, asset_ids: list[UUID] | None = None) -> Subquery:
    current = _case_executions(project_id)
    legacy = _case_plan_history(project_id)
    history = union_all(select(current), select(legacy)).subquery()
    query = select(
        history,
        func.row_number()
        .over(
            partition_by=history.c.asset_id,
            order_by=(history.c.occurred_at.desc(), history.c.order_id.desc()),
        )
        .label("rank"),
    )
    if asset_ids is not None:
        query = query.where(history.c.asset_id.in_(asset_ids))
    ranked = query.subquery()
    return (
        select(ranked, normalized_asset_id(ranked.c.asset_id).label("asset_key"))
        .where(ranked.c.rank == 1)
        .subquery()
    )


def normalized_asset_id(column: SQLColumnExpression[UUID]) -> ColumnElement[str]:
    return func.replace(func.lower(cast(column, String)), "-", "")


def suite_item_key() -> ColumnElement[str]:
    value = TestPlanRunItem.target_snapshot["source_suite"]["id"].as_string()
    return func.replace(func.lower(value), "-", "")


def latest_suite_catalog(project_id: UUID) -> Subquery:
    key = suite_item_key()
    priority = case(
        (TestPlanRunItem.status == "failed", 0),
        (TestPlanRunItem.status == "running", 1),
        (TestPlanRunItem.status == "queued", 2),
        (TestPlanRunItem.status == "cancelled", 3),
        (TestPlanRunItem.status == "quarantined", 4),
        else_=5,
    )
    grouped = (
        select(
            key.label("asset_key"),
            TestPlanRun.id.label("plan_run_id"),
            TestPlanRun.test_plan_id.label("plan_id"),
            TestPlanRun.created_at.label("occurred_at"),
            func.min(priority).label("priority"),
        )
        .select_from(TestPlanRunItem)
        .join(TestPlanRun, TestPlanRun.id == TestPlanRunItem.test_plan_run_id)
        .where(
            TestPlanRun.project_id == project_id,
            TestPlanRunItem.target_type == "case",
            key.is_not(None),
        )
        .group_by(key, TestPlanRun.id, TestPlanRun.test_plan_id, TestPlanRun.created_at)
        .subquery()
    )
    ranked = select(
        grouped,
        func.row_number()
        .over(
            partition_by=grouped.c.asset_key,
            order_by=(grouped.c.occurred_at.desc(), grouped.c.plan_run_id.desc()),
        )
        .label("rank"),
    ).subquery()
    return (
        select(
            ranked.c.asset_key,
            ranked.c.plan_run_id,
            ranked.c.plan_id,
            ranked.c.occurred_at,
            case(
                (ranked.c.priority == 0, "failed"),
                (ranked.c.priority == 1, "running"),
                (ranked.c.priority == 2, "queued"),
                (ranked.c.priority == 3, "cancelled"),
                (ranked.c.priority == 4, "quarantined"),
                else_="passed",
            ).label("status"),
            literal(None).label("execution_id"),
            literal(None).label("asset_version"),
            literal(None).label("environment_id"),
            literal("plan").label("source"),
        )
        .where(ranked.c.rank == 1)
        .subquery()
    )


def _case_executions(project_id: UUID) -> Subquery:
    return (
        select(
            WorkflowExecution.source_case_id.label("asset_id"),
            WorkflowExecution.id.label("execution_id"),
            WorkflowExecution.source_case_version.label("asset_version"),
            WorkflowExecution.status.label("status"),
            WorkflowExecution.started_at.label("occurred_at"),
            WorkflowExecution.id.label("order_id"),
            WorkflowExecution.environment_id.label("environment_id"),
            TestPlanRun.test_plan_id.label("plan_id"),
            TestPlanRun.id.label("plan_run_id"),
            WorkflowExecution.source_trigger.label("source"),
        )
        .select_from(WorkflowExecution)
        .outerjoin(TestPlanRunItem, TestPlanRunItem.id == WorkflowExecution.source_plan_run_item_id)
        .outerjoin(
            TestPlanRun,
            and_(
                TestPlanRun.id == TestPlanRunItem.test_plan_run_id,
                TestPlanRun.project_id == project_id,
            ),
        )
        .where(
            WorkflowExecution.project_id == project_id,
            WorkflowExecution.parent_execution_id.is_(None),
            WorkflowExecution.source_case_id.is_not(None),
        )
        .subquery()
    )


def _case_plan_history(project_id: UUID) -> Subquery:
    return (
        select(
            TestPlanRunItem.target_id.label("asset_id"),
            WorkflowExecution.id.label("execution_id"),
            TestPlanRunItem.target_version.label("asset_version"),
            func.coalesce(WorkflowExecution.status, TestPlanRunItem.status).label("status"),
            func.coalesce(WorkflowExecution.started_at, TestPlanRun.created_at).label(
                "occurred_at"
            ),
            func.coalesce(WorkflowExecution.id, TestPlanRunItem.id).label("order_id"),
            func.coalesce(WorkflowExecution.environment_id, TestPlanRunItem.environment_id).label(
                "environment_id"
            ),
            TestPlanRun.test_plan_id.label("plan_id"),
            TestPlanRun.id.label("plan_run_id"),
            literal("plan").label("source"),
        )
        .select_from(TestPlanRunItem)
        .join(TestPlanRun, TestPlanRun.id == TestPlanRunItem.test_plan_run_id)
        .outerjoin(WorkflowExecution, WorkflowExecution.id == TestPlanRunItem.workflow_execution_id)
        .where(
            TestPlanRun.project_id == project_id,
            TestPlanRunItem.target_type == "case",
            or_(
                WorkflowExecution.id.is_(None),
                and_(
                    WorkflowExecution.project_id == project_id,
                    WorkflowExecution.source_case_id.is_(None),
                    WorkflowExecution.parent_execution_id.is_(None),
                    or_(
                        WorkflowExecution.source_plan_run_item_id.is_(None),
                        WorkflowExecution.source_plan_run_item_id == TestPlanRunItem.id,
                    ),
                ),
            ),
        )
        .subquery()
    )
