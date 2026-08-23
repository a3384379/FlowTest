from uuid import UUID

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, SessionDependency
from app.schemas.test_engineering import (
    TestEngineeringApplyResponse,
    TestEngineeringGenerateRequest,
    TestEngineeringGenerateResponse,
    TestEngineeringProposalCreate,
    TestEngineeringProposalResponse,
    TestEngineeringProposalReview,
)
from app.services.test_engineering import TestEngineeringService
from app.services.test_engineering_proposals import (
    TestEngineeringProposalService,
    TestEngineeringProposalView,
)

router = APIRouter(prefix="/projects/{project_id}/test-engineering")


@router.post("/generate", response_model=TestEngineeringGenerateResponse)
async def generate_test_design(
    project_id: UUID,
    payload: TestEngineeringGenerateRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestEngineeringGenerateResponse:
    design, fingerprint = await TestEngineeringService(session).generate(
        actor=current_user,
        project_id=project_id,
        payload=payload,
    )
    return TestEngineeringGenerateResponse(fingerprint=fingerprint, design=design)


@router.post("/proposals", response_model=TestEngineeringProposalResponse, status_code=201)
async def propose_test_design(
    project_id: UUID,
    payload: TestEngineeringProposalCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestEngineeringProposalResponse:
    view = await TestEngineeringProposalService(session).propose(
        actor=current_user, project_id=project_id, payload=payload
    )
    return _proposal_response(view)


@router.post("/proposals/{change_set_id}/review", response_model=TestEngineeringProposalResponse)
async def review_test_design_proposal(
    project_id: UUID,
    change_set_id: UUID,
    payload: TestEngineeringProposalReview,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestEngineeringProposalResponse:
    view = await TestEngineeringProposalService(session).review(
        actor=current_user,
        project_id=project_id,
        change_set_id=change_set_id,
        accept=payload.accept,
        note=payload.note,
    )
    return _proposal_response(view)


@router.post("/proposals/{change_set_id}/apply", response_model=TestEngineeringApplyResponse)
async def apply_test_design_proposal(
    project_id: UUID,
    change_set_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestEngineeringApplyResponse:
    result = await TestEngineeringProposalService(session).apply(
        actor=current_user, project_id=project_id, change_set_id=change_set_id
    )
    return TestEngineeringApplyResponse(
        change_set_id=result.change_set_id,
        test_design_id=result.test_design_id,
        workflow_ids=result.workflow_ids,
        test_case_ids=result.test_case_ids,
    )


def _proposal_response(view: TestEngineeringProposalView) -> TestEngineeringProposalResponse:
    return TestEngineeringProposalResponse(
        change_set_id=view.change_set.id,
        status=view.change_set.status,
        review_status=view.item.review_status,
        fingerprint=view.change_set.source_fingerprint,
        design=view.design,
        scenario_ids=view.scenario_ids,
        applied=view.change_set.applied_at is not None,
    )
