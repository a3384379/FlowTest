"""Explicit, tenant-scoped asset discovery queries for the MCP surface."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import String, case, cast, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AIChangeSet
from app.models.api_assets import APIDefinition, APIVersion
from app.models.change_regression import ChangeRegressionRun
from app.models.imports import ImportRun
from app.models.tasking import TestPlan
from app.models.test_assets import TestCase, TestSuite
from app.models.test_contexts import TestContext
from app.models.workflows import Workflow, WorkflowExecution


@dataclass(frozen=True, slots=True)
class MCPAssetRow:
    resource_type: str
    resource_id: UUID
    project_id: UUID
    name: str
    summary: str
    version: int | None
    status: str
    source_ref: str | None
    updated_at: object


class MCPAssetRepository:
    """Search only the approved asset types; no arbitrary table/query input is accepted."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_assets(
        self,
        *,
        project_id: UUID,
        asset_types: Iterable[str],
        query: str,
        method: str | None,
        path: str | None,
        source: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[MCPAssetRow], int]:
        requested = set(asset_types)
        if "test_asset" in requested:
            requested.update({"test_case", "test_suite"})
        builders: dict[str, Callable[..., Any]] = {
            "api": self._api_select,
            "workflow": self._workflow_select,
            "context": self._context_select,
            "proposal": self._proposal_select,
            "test_case": self._case_select,
            "test_suite": self._suite_select,
            "test_plan": self._plan_select,
            "import_run": self._import_select,
            "execution": self._execution_select,
            "change_regression_run": self._regression_select,
        }
        selects: list[Any] = [
            builder(
                project_id=project_id,
                query=query,
                method=method,
                path=path,
                source=source,
            )
            for resource_type, builder in builders.items()
            if resource_type in requested
            # Method/path are contract-level filters.  Do not silently return
            # unrelated workflows, contexts or proposals when callers combine
            # a typed filter with a broad asset-type list.
            and (not (method or path) or resource_type == "api")
        ]
        if not selects:
            return [], 0
        assets = union_all(*selects).subquery("mcp_assets")
        total_value = await self._session.scalar(select(func.count()).select_from(assets))
        ordered = (
            select(assets)
            .order_by(
                assets.c.updated_at.desc(),
                assets.c.resource_type.asc(),
                assets.c.resource_id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        rows = (await self._session.execute(ordered)).mappings().all()
        result = [
            MCPAssetRow(
                resource_type=str(row["resource_type"]),
                resource_id=UUID(str(row["resource_id"])),
                project_id=UUID(str(row["project_id"])),
                name=str(row["name"] or ""),
                summary=str(row["summary"] or ""),
                version=_parse_version(row["version"]),
                status=str(row["status"] or "unknown"),
                source_ref=str(row["source_ref"]) if row["source_ref"] else None,
                updated_at=row["updated_at"],
            )
            for row in rows
        ]
        return result, int(total_value or 0)

    @staticmethod
    def _columns(
        resource_type: str,
        resource_id: object,
        project_id: object,
        name: object,
        summary: object,
        version: object,
        status: object,
        source_ref: object,
        updated_at: Any,
    ) -> tuple[Any, ...]:
        return (
            literal(resource_type, type_=String(32)).label("resource_type"),
            cast(resource_id, String(36)).label("resource_id"),
            cast(project_id, String(36)).label("project_id"),
            cast(name, String(200)).label("name"),
            cast(summary, String(400)).label("summary"),
            cast(version, String(24)).label("version"),
            cast(status, String(32)).label("status"),
            cast(source_ref, String(512)).label("source_ref"),
            updated_at.label("updated_at"),
        )

    @staticmethod
    def _conditions(
        *,
        project_column: Any,
        project_id: UUID,
        query: str,
        query_columns: tuple[Any, ...],
        source: str | None,
        source_columns: tuple[Any, ...] = (),
    ) -> list[Any]:
        conditions: list[Any] = [project_column == project_id]
        if query:
            pattern = f"%{query}%"
            conditions.append(or_(*(column.ilike(pattern) for column in query_columns)))
        if source is not None:
            pattern = f"%{source}%"
            if not source_columns:
                conditions.append(literal(False))
            else:
                conditions.append(or_(*(column.ilike(pattern) for column in source_columns)))
        return conditions

    def _api_select(
        self,
        *,
        project_id: UUID,
        query: str,
        method: str | None,
        path: str | None,
        source: str | None,
    ) -> Any:
        conditions = self._conditions(
            project_column=APIDefinition.project_id,
            project_id=project_id,
            query=query,
            query_columns=(APIDefinition.name, APIDefinition.description),
            source=source,
            source_columns=(APIDefinition.import_source, APIDefinition.import_source_key),
        )
        if method or path:
            version_conditions: list[Any] = [
                APIVersion.api_definition_id == APIDefinition.id,
                APIVersion.version == APIDefinition.current_version,
            ]
            if method:
                version_conditions.append(APIVersion.method == method)
            if path:
                version_conditions.append(APIVersion.path.ilike(f"%{path}%"))
            conditions.append(select(APIVersion.id).where(*version_conditions).exists())
        return select(
            *self._columns(
                "api",
                APIDefinition.id,
                APIDefinition.project_id,
                APIDefinition.name,
                APIDefinition.description,
                APIDefinition.current_version,
                case(
                    (APIDefinition.is_active.is_(True), literal("active")),
                    else_=literal("inactive"),
                ),
                APIDefinition.import_source_key,
                APIDefinition.updated_at,
            )
        ).where(*conditions)

    def _workflow_select(self, **kwargs: Any) -> Any:
        return select(
            *self._columns(
                "workflow",
                Workflow.id,
                Workflow.project_id,
                Workflow.name,
                Workflow.description,
                Workflow.current_version,
                literal("draft"),
                literal(None),
                Workflow.updated_at,
            )
        ).where(
            *self._conditions(
                project_column=Workflow.project_id,
                project_id=kwargs["project_id"],
                query=kwargs["query"],
                query_columns=(Workflow.name, Workflow.description),
                source=kwargs["source"],
            )
        )

    def _context_select(self, **kwargs: Any) -> Any:
        return select(
            *self._columns(
                "context",
                TestContext.id,
                TestContext.project_id,
                TestContext.name,
                TestContext.objective,
                TestContext.current_revision,
                TestContext.status,
                literal(None),
                TestContext.updated_at,
            )
        ).where(
            *self._conditions(
                project_column=TestContext.project_id,
                project_id=kwargs["project_id"],
                query=kwargs["query"],
                query_columns=(TestContext.name, TestContext.objective),
                source=kwargs["source"],
            )
        )

    def _proposal_select(self, **kwargs: Any) -> Any:
        return select(
            *self._columns(
                "proposal",
                AIChangeSet.id,
                AIChangeSet.project_id,
                AIChangeSet.title,
                literal(""),
                literal(None),
                AIChangeSet.status,
                AIChangeSet.source_ref,
                AIChangeSet.updated_at,
            )
        ).where(
            *self._conditions(
                project_column=AIChangeSet.project_id,
                project_id=kwargs["project_id"],
                query=kwargs["query"],
                query_columns=(AIChangeSet.title, AIChangeSet.source_ref),
                source=kwargs["source"],
                source_columns=(AIChangeSet.source_ref,),
            )
        )

    def _case_select(self, **kwargs: Any) -> Any:
        return select(
            *self._columns(
                "test_case",
                TestCase.id,
                TestCase.project_id,
                TestCase.name,
                TestCase.description,
                TestCase.current_version,
                literal("draft"),
                literal(None),
                TestCase.updated_at,
            )
        ).where(
            *self._conditions(
                project_column=TestCase.project_id,
                project_id=kwargs["project_id"],
                query=kwargs["query"],
                query_columns=(TestCase.name, TestCase.description),
                source=kwargs["source"],
            )
        )

    def _suite_select(self, **kwargs: Any) -> Any:
        return select(
            *self._columns(
                "test_suite",
                TestSuite.id,
                TestSuite.project_id,
                TestSuite.name,
                TestSuite.description,
                TestSuite.current_version,
                literal("draft"),
                literal(None),
                TestSuite.updated_at,
            )
        ).where(
            *self._conditions(
                project_column=TestSuite.project_id,
                project_id=kwargs["project_id"],
                query=kwargs["query"],
                query_columns=(TestSuite.name, TestSuite.description),
                source=kwargs["source"],
            )
        )

    def _plan_select(self, **kwargs: Any) -> Any:
        return select(
            *self._columns(
                "test_plan",
                TestPlan.id,
                TestPlan.project_id,
                TestPlan.name,
                TestPlan.description,
                literal(None),
                case((TestPlan.enabled.is_(True), literal("enabled")), else_=literal("disabled")),
                literal(None),
                TestPlan.updated_at,
            )
        ).where(
            *self._conditions(
                project_column=TestPlan.project_id,
                project_id=kwargs["project_id"],
                query=kwargs["query"],
                query_columns=(TestPlan.name, TestPlan.description),
                source=kwargs["source"],
            )
        )

    def _import_select(self, **kwargs: Any) -> Any:
        return select(
            *self._columns(
                "import_run",
                ImportRun.id,
                ImportRun.project_id,
                ImportRun.source_name,
                ImportRun.source_type,
                literal(None),
                ImportRun.status,
                ImportRun.source_key,
                ImportRun.updated_at,
            )
        ).where(
            *self._conditions(
                project_column=ImportRun.project_id,
                project_id=kwargs["project_id"],
                query=kwargs["query"],
                query_columns=(ImportRun.source_name, ImportRun.source_type, ImportRun.source_key),
                source=kwargs["source"],
                source_columns=(ImportRun.source_key, ImportRun.source_name),
            )
        )

    def _execution_select(self, **kwargs: Any) -> Any:
        conditions = self._conditions(
            project_column=WorkflowExecution.project_id,
            project_id=kwargs["project_id"],
            query=kwargs["query"],
            query_columns=(Workflow.name,),
            source=kwargs["source"],
        )
        return (
            select(
                *self._columns(
                    "execution",
                    WorkflowExecution.id,
                    WorkflowExecution.project_id,
                    func.coalesce(Workflow.name, literal("workflow execution")),
                    WorkflowExecution.status,
                    literal(None),
                    WorkflowExecution.status,
                    literal(None),
                    WorkflowExecution.updated_at,
                )
            )
            .join(Workflow, Workflow.id == WorkflowExecution.workflow_id, isouter=True)
            .where(*conditions)
        )

    def _regression_select(self, **kwargs: Any) -> Any:
        return select(
            *self._columns(
                "change_regression_run",
                ChangeRegressionRun.id,
                ChangeRegressionRun.project_id,
                ChangeRegressionRun.title,
                ChangeRegressionRun.source_ref,
                literal(None),
                ChangeRegressionRun.status,
                ChangeRegressionRun.source_ref,
                ChangeRegressionRun.updated_at,
            )
        ).where(
            *self._conditions(
                project_column=ChangeRegressionRun.project_id,
                project_id=kwargs["project_id"],
                query=kwargs["query"],
                query_columns=(ChangeRegressionRun.title, ChangeRegressionRun.source_ref),
                source=kwargs["source"],
                source_columns=(ChangeRegressionRun.source_ref,),
            )
        )


def _parse_version(value: Any) -> int | None:
    try:
        parsed = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return parsed if parsed is not None and parsed >= 1 else None
