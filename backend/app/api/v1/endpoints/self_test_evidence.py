"""Read-only evidence transport authenticated by the current external O task lease."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from app.api.dependencies import SessionDependency
from app.api.v1.endpoints.self_tests import Agent, Config
from app.schemas.execution_evidence import (
    ControlRecordsEvidenceResponse,
    ExecutionEvidenceResponse,
    PlanRunEvidenceResponse,
)
from app.schemas.self_test_evidence import SyntheticNameEvidence
from app.schemas.self_tests import LeaseRequest
from app.services.self_test_access import self_test_error
from app.services.self_test_evidence import SelfTestEvidenceService

router = APIRouter(prefix="/agent/projects/{project_id}/self-tests/runs/{batch_id}/evidence")


def evidence_lease(
    token: Annotated[
        str | None, Header(alias="X-SelfTest-Lease-Token", min_length=32, max_length=200)
    ] = None,
    nonce: Annotated[
        str | None, Header(alias="X-SelfTest-Nonce", min_length=32, max_length=200)
    ] = None,
) -> LeaseRequest:
    if token is None or nonce is None:
        raise self_test_error("SELFTEST_LEASE_INVALID", "需要本批次租约及 nonce", 403)
    return LeaseRequest(lease_token=token, nonce=nonce)


Lease = Annotated[LeaseRequest, Depends(evidence_lease)]


@router.get(
    "/workflow-executions/{execution_id}/synthetic-names", response_model=SyntheticNameEvidence
)
async def synthetic_names(
    project_id: UUID,
    batch_id: UUID,
    execution_id: UUID,
    principal: Agent,
    lease: Lease,
    session: SessionDependency,
    config: Config,
) -> SyntheticNameEvidence:
    return await SelfTestEvidenceService(session, config).synthetic_names(
        principal, project_id, batch_id, lease, execution_id
    )


@router.get("/test-plan-runs/{run_id}", response_model=PlanRunEvidenceResponse)
async def plan_run(
    project_id: UUID,
    batch_id: UUID,
    run_id: UUID,
    principal: Agent,
    lease: Lease,
    session: SessionDependency,
    config: Config,
    page: int = Query(default=1, ge=1, le=1000),
    page_size: int = Query(default=100, ge=1, le=100),
) -> PlanRunEvidenceResponse:
    return await SelfTestEvidenceService(session, config).plan_run(
        principal, project_id, batch_id, lease, run_id, page=page, page_size=page_size
    )


@router.get("/workflow-executions/{execution_id}", response_model=ExecutionEvidenceResponse)
async def execution(
    project_id: UUID,
    batch_id: UUID,
    execution_id: UUID,
    principal: Agent,
    lease: Lease,
    session: SessionDependency,
    config: Config,
) -> ExecutionEvidenceResponse:
    return await SelfTestEvidenceService(session, config).execution(
        principal, project_id, batch_id, lease, execution_id
    )


@router.get(
    "/workflow-executions/{execution_id}/control-records",
    response_model=ControlRecordsEvidenceResponse,
)
async def control_records(
    project_id: UUID,
    batch_id: UUID,
    execution_id: UUID,
    principal: Agent,
    lease: Lease,
    session: SessionDependency,
    config: Config,
    node_id: str = Query(min_length=1, max_length=128),
    kind: Literal["iteration", "branch"] = "iteration",
    page: int = Query(default=1, ge=1, le=1000),
    page_size: int = Query(default=100, ge=1, le=100),
) -> ControlRecordsEvidenceResponse:
    return await SelfTestEvidenceService(session, config).control_records(
        principal,
        project_id,
        batch_id,
        lease,
        execution_id,
        node_id=node_id,
        kind=kind,
        page=page,
        page_size=page_size,
    )
