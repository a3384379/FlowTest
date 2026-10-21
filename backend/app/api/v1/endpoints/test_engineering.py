from uuid import UUID

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, SessionDependency
from app.domain.test_engineering import OperationContract, fingerprint_contract
from app.schemas.test_engineering import (
    TestEngineeringApplyResponse,
    TestEngineeringGenerateRequest,
    TestEngineeringGenerateResponse,
    TestEngineeringMaterializedAsset,
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
    service = TestEngineeringService(session)
    design, fingerprint = await service.generate(
        actor=current_user,
        project_id=project_id,
        payload=payload,
    )
    contract = payload.contract
    if payload.api_definition_id is not None:
        contract = await service.contract_for_api(
            project_id=project_id, definition_id=payload.api_definition_id
        )
    if contract is None:
        raise RuntimeError("validated test engineering request lost its contract")
    return TestEngineeringGenerateResponse(
        fingerprint=fingerprint,
        design=design,
        contract_completeness=contract.completeness,
        contract_fingerprint=fingerprint_contract(contract),
        contract=contract,
        evidence_details=service.evidence_details(design, contract, payload.additional_evidence),
    )


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


@router.get("/proposals/{change_set_id}", response_model=TestEngineeringProposalResponse)
async def get_test_design_proposal(
    project_id: UUID,
    change_set_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestEngineeringProposalResponse:
    view = await TestEngineeringProposalService(session).get(
        actor=current_user,
        project_id=project_id,
        change_set_id=change_set_id,
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
        assets=[TestEngineeringMaterializedAsset.model_validate(value) for value in result.assets],
        references_complete=result.references_complete,
    )


def _proposal_response(view: TestEngineeringProposalView) -> TestEngineeringProposalResponse:
    contract_fingerprint = view.change_set.source_snapshot.get("contract_fingerprint")
    raw_contract = view.change_set.source_snapshot.get("contract")
    contract = OperationContract.model_validate(raw_contract)
    completeness = contract.completeness
    return TestEngineeringProposalResponse(
        change_set_id=view.change_set.id,
        status=view.change_set.status,
        review_status=view.item.review_status,
        fingerprint=view.change_set.source_fingerprint,
        design=view.design,
        scenario_ids=view.scenario_ids,
        applied=view.change_set.applied_at is not None,
        contract_completeness=(completeness if isinstance(completeness, str) else "legacy_partial"),
        contract_fingerprint=(
            contract_fingerprint if isinstance(contract_fingerprint, str) else ""
        ),
        contract=contract,
        evidence_details=view.evidence_details,
        materialization=(
            TestEngineeringApplyResponse(
                change_set_id=view.materialization.change_set_id,
                test_design_id=view.materialization.test_design_id,
                workflow_ids=view.materialization.workflow_ids,
                test_case_ids=view.materialization.test_case_ids,
                assets=[
                    TestEngineeringMaterializedAsset.model_validate(value)
                    for value in view.materialization.assets
                ],
                references_complete=view.materialization.references_complete,
            )
            if view.materialization is not None
            else None
        ),
    )
