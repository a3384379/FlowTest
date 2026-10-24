from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies import CIExecutionReader, SessionDependency
from app.schemas.execution_evidence import (
    ControlRecordsEvidenceResponse,
    ExecutionEvidenceResponse,
    PlanRunEvidenceResponse,
)
from app.services.execution_evidence import ExecutionEvidenceService

router = APIRouter(prefix="/ci/projects/{project_id}")


@router.get("/test-plan-runs/{run_id}", response_model=PlanRunEvidenceResponse)
async def get_plan_run_evidence(
    project_id: UUID,
    run_id: UUID,
    session: SessionDependency,
    identity: CIExecutionReader,
    page: int = Query(default=1, ge=1, le=1000),
    page_size: int = Query(default=100, ge=1, le=100),
) -> PlanRunEvidenceResponse:
    return await ExecutionEvidenceService(session).plan_run(
        actor=identity.actor,
        project_id=project_id,
        run_id=run_id,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/workflow-executions/{execution_id}/evidence", response_model=ExecutionEvidenceResponse
)
async def get_execution_evidence(
    project_id: UUID,
    execution_id: UUID,
    session: SessionDependency,
    identity: CIExecutionReader,
) -> ExecutionEvidenceResponse:
    return await ExecutionEvidenceService(session).execution(
        actor=identity.actor,
        project_id=project_id,
        execution_id=execution_id,
    )


@router.get(
    "/workflow-executions/{execution_id}/evidence/control-records",
    response_model=ControlRecordsEvidenceResponse,
)
async def get_control_records_evidence(
    project_id: UUID,
    execution_id: UUID,
    session: SessionDependency,
    identity: CIExecutionReader,
    node_id: str = Query(min_length=1, max_length=128),
    kind: Literal["iteration", "branch"] = "iteration",
    page: int = Query(default=1, ge=1, le=1000),
    page_size: int = Query(default=100, ge=1, le=100),
) -> ControlRecordsEvidenceResponse:
    return await ExecutionEvidenceService(session).control_records(
        actor=identity.actor,
        project_id=project_id,
        execution_id=execution_id,
        node_id=node_id,
        kind=kind,
        page=page,
        page_size=page_size,
    )
