from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.schemas.common import Page
from app.schemas.contracts import (
    ContractCaseReviewRequest,
    ContractRunResponse,
    GeneratedContractCaseResponse,
)
from app.services.contracts import ContractService

router = APIRouter(prefix="/projects/{project_id}/contract-runs")


@router.post("", response_model=ContractRunResponse, status_code=status.HTTP_201_CREATED)
async def create_contract_run(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    document: Annotated[UploadFile, File()],
    source_name: Annotated[str | None, Form(max_length=255)] = None,
    baseline_run_id: Annotated[UUID | None, Form()] = None,
) -> ContractRunResponse:
    content = await document.read(5 * 1024 * 1024 + 1)
    model = await ContractService(session).create_run(
        actor=current_user,
        project_id=project_id,
        source_name=source_name or document.filename or "openapi.yaml",
        content=content,
        baseline_run_id=baseline_run_id,
    )
    return ContractRunResponse.model_validate(model)


@router.get("", response_model=Page[ContractRunResponse])
async def list_contract_runs(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[ContractRunResponse]:
    items, total = await ContractService(session).list_runs(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[ContractRunResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{run_id}", response_model=ContractRunResponse)
async def get_contract_run(
    project_id: UUID,
    run_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ContractRunResponse:
    model = await ContractService(session).get_run(
        actor=current_user, project_id=project_id, run_id=run_id
    )
    return ContractRunResponse.model_validate(model)


@router.get("/{run_id}/generated-cases", response_model=Page[GeneratedContractCaseResponse])
async def list_generated_contract_cases(
    project_id: UUID,
    run_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    review_status: Literal["pending", "accepted", "rejected"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> Page[GeneratedContractCaseResponse]:
    items, total = await ContractService(session).list_generated_cases(
        actor=current_user,
        project_id=project_id,
        run_id=run_id,
        review_status=review_status,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[GeneratedContractCaseResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{run_id}/generated-cases/{case_id}/accept",
    response_model=GeneratedContractCaseResponse,
)
async def accept_generated_contract_case(
    project_id: UUID,
    run_id: UUID,
    case_id: UUID,
    payload: ContractCaseReviewRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> GeneratedContractCaseResponse:
    model = await ContractService(session).review_case(
        actor=current_user,
        project_id=project_id,
        run_id=run_id,
        case_id=case_id,
        accept=True,
        name=payload.name,
        definition=payload.definition,
        note=payload.note,
    )
    return GeneratedContractCaseResponse.model_validate(model)


@router.post(
    "/{run_id}/generated-cases/{case_id}/reject",
    response_model=GeneratedContractCaseResponse,
)
async def reject_generated_contract_case(
    project_id: UUID,
    run_id: UUID,
    case_id: UUID,
    payload: ContractCaseReviewRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> GeneratedContractCaseResponse:
    model = await ContractService(session).review_case(
        actor=current_user,
        project_id=project_id,
        run_id=run_id,
        case_id=case_id,
        accept=False,
        name=payload.name,
        definition=payload.definition,
        note=payload.note,
    )
    return GeneratedContractCaseResponse.model_validate(model)
