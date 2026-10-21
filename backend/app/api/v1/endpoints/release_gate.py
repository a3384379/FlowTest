from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.schemas.common import Page
from app.schemas.release_gate import (
    ReleaseDecisionCreate,
    ReleaseDecisionResponse,
    ReleasePolicyResponse,
    ReleasePolicyWrite,
    ReleaseRunnerEvidenceResponse,
)
from app.services.release_gate import ReleaseGateService

router = APIRouter(prefix="/projects/{project_id}")


@router.get("/release-runner-evidence", response_model=Page[ReleaseRunnerEvidenceResponse])
async def list_release_runner_evidence(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Literal["queued", "leased", "completed", "failed", "cancelled"] | None = None,
    search: str = Query(default="", max_length=200),
) -> Page[ReleaseRunnerEvidenceResponse]:
    tasks, total = await ReleaseGateService(session).list_runner_evidence(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
        status=status,
        search=search,
    )
    return Page(
        items=[ReleaseRunnerEvidenceResponse.model_validate(task) for task in tasks],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/release-runner-evidence/{task_id}", response_model=ReleaseRunnerEvidenceResponse)
async def get_release_runner_evidence(
    project_id: UUID,
    task_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ReleaseRunnerEvidenceResponse:
    task = await ReleaseGateService(session).get_runner_evidence(
        actor=current_user, project_id=project_id, task_id=task_id
    )
    return ReleaseRunnerEvidenceResponse.model_validate(task)


@router.get("/release-policies", response_model=list[ReleasePolicyResponse])
async def list_release_policies(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[ReleasePolicyResponse]:
    policies = await ReleaseGateService(session).list_policies(
        actor=current_user, project_id=project_id
    )
    return [ReleasePolicyResponse.model_validate(policy) for policy in policies]


@router.post(
    "/release-policies",
    response_model=ReleasePolicyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_release_policy(
    project_id: UUID,
    payload: ReleasePolicyWrite,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ReleasePolicyResponse:
    policy = await ReleaseGateService(session).create_policy(
        actor=current_user, project_id=project_id, payload=payload
    )
    return ReleasePolicyResponse.model_validate(policy)


@router.put(
    "/release-policies/{policy_id}",
    response_model=ReleasePolicyResponse,
)
async def update_release_policy(
    project_id: UUID,
    policy_id: UUID,
    payload: ReleasePolicyWrite,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ReleasePolicyResponse:
    policy = await ReleaseGateService(session).update_policy(
        actor=current_user,
        project_id=project_id,
        policy_id=policy_id,
        payload=payload,
    )
    return ReleasePolicyResponse.model_validate(policy)


@router.post(
    "/release-decisions",
    response_model=ReleaseDecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_release_decision(
    project_id: UUID,
    payload: ReleaseDecisionCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ReleaseDecisionResponse:
    decision = await ReleaseGateService(session).create_decision(
        actor=current_user, project_id=project_id, payload=payload
    )
    return ReleaseDecisionResponse.model_validate(decision)


@router.get("/release-decisions", response_model=Page[ReleaseDecisionResponse])
async def list_release_decisions(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[ReleaseDecisionResponse]:
    decisions, total = await ReleaseGateService(session).list_decisions(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[ReleaseDecisionResponse.model_validate(item) for item in decisions],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/release-decisions/{decision_id}",
    response_model=ReleaseDecisionResponse,
)
async def get_release_decision(
    project_id: UUID,
    decision_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ReleaseDecisionResponse:
    decision = await ReleaseGateService(session).get_decision(
        actor=current_user, project_id=project_id, decision_id=decision_id
    )
    return ReleaseDecisionResponse.model_validate(decision)
