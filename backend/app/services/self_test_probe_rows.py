"""Bounded union of metadata columns; payloads never enter the inventory rows."""

from typing import Any
from uuid import UUID

from sqlalchemy import Integer, Row, Text, Uuid, case, cast, func, literal, null, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import CompoundSelect

from app.models.ai import AIChangeSet
from app.models.tasking import TestPlan, TestPlanRun
from app.models.test_assets import TestCase, TestCaseVersion
from app.models.test_design import ChangeSetApproval, TestDesign
from app.models.workflows import Workflow, WorkflowExecution, WorkflowVersion
from app.schemas.self_test_probes import ProbeResource


def _query(project_ids: tuple[UUID, ...]) -> CompoundSelect[Any]:
    return union_all(
        select(
            literal("workflow"),
            Workflow.id,
            Workflow.project_id,
            cast(null(), Uuid),
            cast(null(), Uuid),
            Workflow.current_version,
            case(
                (Workflow.archived_at.is_not(None), "archived"),
                (Workflow.current_version.is_not(None), "published"),
                else_="draft",
            ),
            cast(null(), Text),
            Workflow.created_by_id,
            cast(null(), Uuid),
            cast(null(), Text),
        ).where(Workflow.project_id.in_(project_ids)),
        select(
            literal("workflow_version"),
            WorkflowVersion.id,
            Workflow.project_id,
            WorkflowVersion.workflow_id,
            cast(null(), Uuid),
            WorkflowVersion.version,
            literal("published"),
            WorkflowVersion.fingerprint,
            WorkflowVersion.created_by_id,
            cast(null(), Uuid),
            cast(null(), Text),
        )
        .join(Workflow)
        .where(Workflow.project_id.in_(project_ids)),
        select(
            literal("test_case"),
            TestCase.id,
            TestCase.project_id,
            cast(null(), Uuid),
            cast(null(), Uuid),
            TestCase.current_version,
            case(
                (TestCase.archived_at.is_not(None), "archived"),
                (TestCase.current_version.is_not(None), "published"),
                else_="draft",
            ),
            cast(null(), Text),
            TestCase.created_by_id,
            cast(null(), Uuid),
            cast(null(), Text),
        ).where(TestCase.project_id.in_(project_ids)),
        select(
            literal("test_case_version"),
            TestCaseVersion.id,
            TestCase.project_id,
            TestCaseVersion.test_case_id,
            cast(null(), Uuid),
            TestCaseVersion.version,
            literal("published"),
            TestCaseVersion.fingerprint,
            TestCaseVersion.created_by_id,
            cast(null(), Uuid),
            cast(null(), Text),
        )
        .join(TestCase)
        .where(TestCase.project_id.in_(project_ids)),
        select(
            literal("test_plan"),
            TestPlan.id,
            TestPlan.project_id,
            cast(null(), Uuid),
            cast(null(), Uuid),
            cast(null(), Integer),
            case((TestPlan.enabled, "enabled"), else_="disabled"),
            cast(null(), Text),
            TestPlan.created_by_id,
            cast(null(), Uuid),
            cast(null(), Text),
        ).where(TestPlan.project_id.in_(project_ids)),
        select(
            literal("test_plan_run"),
            TestPlanRun.id,
            TestPlanRun.project_id,
            TestPlanRun.test_plan_id,
            cast(null(), Uuid),
            cast(null(), Integer),
            TestPlanRun.status,
            cast(null(), Text),
            TestPlanRun.requested_by_id,
            cast(null(), Uuid),
            cast(null(), Text),
        ).where(TestPlanRun.project_id.in_(project_ids)),
        select(
            literal("workflow_execution"),
            WorkflowExecution.id,
            WorkflowExecution.project_id,
            WorkflowExecution.workflow_id,
            WorkflowExecution.source_change_set_id,
            cast(null(), Integer),
            WorkflowExecution.status,
            cast(null(), Text),
            WorkflowExecution.triggered_by_id,
            cast(null(), Uuid),
            cast(null(), Text),
        ).where(WorkflowExecution.project_id.in_(project_ids)),
        select(
            literal("ai_change_set"),
            AIChangeSet.id,
            AIChangeSet.project_id,
            cast(null(), Uuid),
            cast(null(), Uuid),
            cast(null(), Integer),
            AIChangeSet.status,
            AIChangeSet.source_fingerprint,
            AIChangeSet.created_by_id,
            cast(null(), Uuid),
            AIChangeSet.actor_type,
        ).where(AIChangeSet.project_id.in_(project_ids)),
        select(
            literal("test_design"),
            TestDesign.id,
            TestDesign.project_id,
            cast(null(), Uuid),
            TestDesign.source_change_set_id,
            cast(null(), Integer),
            TestDesign.status,
            TestDesign.fingerprint,
            TestDesign.created_by_id,
            TestDesign.reviewed_by_id,
            cast(null(), Text),
        ).where(TestDesign.project_id.in_(project_ids)),
        select(
            literal("change_set_approval"),
            ChangeSetApproval.id,
            AIChangeSet.project_id,
            ChangeSetApproval.change_set_id,
            ChangeSetApproval.change_set_id,
            cast(null(), Integer),
            ChangeSetApproval.decision,
            cast(null(), Text),
            cast(null(), Uuid),
            ChangeSetApproval.approved_by_id,
            cast(null(), Text),
        )
        .join(AIChangeSet)
        .where(AIChangeSet.project_id.in_(project_ids)),
    )


def _resource(row: Row[Any]) -> ProbeResource:
    return ProbeResource(
        kind=row[0],
        id=row[1],
        project_id=row[2],
        parent_id=row[3],
        source_change_set_id=row[4],
        version=row[5],
        status=row[6],
        fingerprint=row[7],
        created_by_id=row[8],
        reviewed_by_id=row[9],
        actor_type=row[10],
    )


async def probe_rows(
    session: AsyncSession, project_ids: tuple[UUID, ...]
) -> tuple[int, tuple[ProbeResource, ...]]:
    query = _query(project_ids)
    total = int(await session.scalar(select(func.count()).select_from(query.subquery())) or 0)
    if total > 500:
        return total, ()
    rows = (await session.execute(query.limit(501))).all()
    if len(rows) != total:
        return total, ()
    return total, tuple(sorted((_resource(row) for row in rows), key=lambda r: (r.kind, r.id)))
