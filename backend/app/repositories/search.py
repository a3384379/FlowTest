from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, case, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.models.access import Project
from app.models.api_assets import APIDefinition, Environment
from app.models.contracts import ServiceCatalogEntry
from app.models.data_sources import MockService
from app.models.impact import ImpactRun
from app.models.performance import PerformanceScenario
from app.models.quality import QualityGate
from app.models.quality_intelligence import ReleaseRisk
from app.models.release_gate import ReleasePolicy
from app.models.tasking import TestPlan
from app.models.test_assets import TestCase, TestSuite
from app.models.workflows import Workflow


@dataclass(frozen=True, slots=True)
class SearchRow:
    resource_type: str
    resource_id: UUID
    project_id: UUID
    project_name: str
    title: str
    description: str
    section: str
    updated_at: datetime


class SearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        *,
        query: str,
        project_ids: set[UUID],
        offset: int,
        limit: int,
    ) -> tuple[list[SearchRow], int]:
        if not project_ids:
            return [], 0
        resources = _searchable_resources(query)
        searchable = union_all(*resources).subquery("searchable_assets")
        filtered = (
            select(searchable)
            .where(searchable.c.project_id.in_(project_ids))
            .subquery("accessible_search_results")
        )
        total = await self._session.scalar(select(func.count()).select_from(filtered))
        statement = (
            select(
                filtered.c.resource_type,
                filtered.c.resource_id,
                filtered.c.project_id,
                Project.name.label("project_name"),
                filtered.c.title,
                filtered.c.description,
                filtered.c.section,
                filtered.c.updated_at,
            )
            .join(Project, Project.id == filtered.c.project_id)
            .order_by(filtered.c.rank, filtered.c.updated_at.desc(), filtered.c.title)
            .offset(offset)
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).mappings().all()
        return [SearchRow(**row) for row in rows], int(total or 0)


def _searchable_resources(query: str) -> list[Select[Any]]:
    return [
        _resource_query(
            query=query,
            resource_type="project",
            resource_id=Project.id,
            project_id=Project.id,
            title=Project.name,
            description=Project.description,
            section="settings",
            updated_at=Project.updated_at,
        ),
        _resource_query(
            query=query,
            resource_type="api",
            resource_id=APIDefinition.id,
            project_id=APIDefinition.project_id,
            title=APIDefinition.name,
            description=APIDefinition.description,
            section="apis",
            updated_at=APIDefinition.updated_at,
        ),
        _resource_query(
            query=query,
            resource_type="workflow",
            resource_id=Workflow.id,
            project_id=Workflow.project_id,
            title=Workflow.name,
            description=Workflow.description,
            section="workflows",
            updated_at=Workflow.updated_at,
        ),
        _resource_query(
            query=query,
            resource_type="test_case",
            resource_id=TestCase.id,
            project_id=TestCase.project_id,
            title=TestCase.name,
            description=TestCase.description,
            section="assets",
            updated_at=TestCase.updated_at,
        ),
        _resource_query(
            query=query,
            resource_type="test_suite",
            resource_id=TestSuite.id,
            project_id=TestSuite.project_id,
            title=TestSuite.name,
            description=TestSuite.description,
            section="assets",
            updated_at=TestSuite.updated_at,
        ),
        _resource_query(
            query=query,
            resource_type="test_plan",
            resource_id=TestPlan.id,
            project_id=TestPlan.project_id,
            title=TestPlan.name,
            description=TestPlan.description,
            section="tasks",
            updated_at=TestPlan.updated_at,
        ),
        _resource_query(
            query=query,
            resource_type="environment",
            resource_id=Environment.id,
            project_id=Environment.project_id,
            title=Environment.name,
            description=literal(""),
            section="environments",
            updated_at=Environment.updated_at,
        ),
        _resource_query(
            query=query,
            resource_type="mock_service",
            resource_id=MockService.id,
            project_id=MockService.project_id,
            title=MockService.name,
            description=MockService.description,
            section="data",
            updated_at=MockService.updated_at,
        ),
        _resource_query(
            query=query,
            resource_type="performance_scenario",
            resource_id=PerformanceScenario.id,
            project_id=PerformanceScenario.project_id,
            title=PerformanceScenario.name,
            description=PerformanceScenario.description,
            section="performance",
            updated_at=PerformanceScenario.updated_at,
        ),
        _resource_query(
            query=query,
            resource_type="contract_service",
            resource_id=ServiceCatalogEntry.id,
            project_id=ServiceCatalogEntry.project_id,
            title=ServiceCatalogEntry.display_name,
            description=ServiceCatalogEntry.description,
            section="services",
            updated_at=ServiceCatalogEntry.updated_at,
        ),
        _resource_query(
            query=query,
            resource_type="impact_run",
            resource_id=ImpactRun.id,
            project_id=ImpactRun.project_id,
            title=ImpactRun.title,
            description=ImpactRun.source_ref,
            section="impact",
            updated_at=ImpactRun.updated_at,
        ),
        _resource_query(
            query=query,
            resource_type="quality_gate",
            resource_id=QualityGate.id,
            project_id=QualityGate.project_id,
            title=QualityGate.name,
            description=literal(""),
            section="quality",
            updated_at=QualityGate.updated_at,
        ),
        _resource_query(
            query=query,
            resource_type="release_risk",
            resource_id=ReleaseRisk.id,
            project_id=ReleaseRisk.project_id,
            title=ReleaseRisk.title,
            description=literal(""),
            section="quality",
            updated_at=ReleaseRisk.updated_at,
        ),
        _resource_query(
            query=query,
            resource_type="release_policy",
            resource_id=ReleasePolicy.id,
            project_id=ReleasePolicy.project_id,
            title=ReleasePolicy.name,
            description=literal(""),
            section="release",
            updated_at=ReleasePolicy.updated_at,
        ),
    ]


def _resource_query(
    *,
    query: str,
    resource_type: str,
    resource_id: InstrumentedAttribute[UUID] | ColumnElement[UUID],
    project_id: InstrumentedAttribute[UUID] | ColumnElement[UUID],
    title: InstrumentedAttribute[str] | ColumnElement[str],
    description: InstrumentedAttribute[str] | ColumnElement[str],
    section: str,
    updated_at: InstrumentedAttribute[datetime] | ColumnElement[datetime],
) -> Select[Any]:
    escaped = _escape_like(query)
    contains = f"%{escaped}%"
    starts_with = f"{escaped}%"
    normalized = query.casefold()
    return select(
        literal(resource_type).label("resource_type"),
        resource_id.label("resource_id"),
        project_id.label("project_id"),
        title.label("title"),
        description.label("description"),
        literal(section).label("section"),
        updated_at.label("updated_at"),
        case(
            (func.lower(title) == normalized, 0),
            (title.ilike(starts_with, escape="\\"), 1),
            (title.ilike(contains, escape="\\"), 2),
            else_=3,
        ).label("rank"),
    ).where(
        or_(
            title.ilike(contains, escape="\\"),
            description.ilike(contains, escape="\\"),
        )
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
