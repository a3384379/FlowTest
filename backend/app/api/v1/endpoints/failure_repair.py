from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.api.v1.endpoints.flow_spec import flow_spec_change_set_detail
from app.schemas.failure_repair import (
    FailureDiagnosisResponse,
    RepairProposalCreate,
    RepairProposalResponse,
)
from app.services.failure_repair import FailureRepairService
from app.services.idempotency import IdempotencyService

router = APIRouter(prefix="/projects/{project_id}/workflow-executions/{execution_id}")


@router.get("/failure-diagnosis", response_model=FailureDiagnosisResponse)
async def get_failure_diagnosis(
    project_id: UUID,
    execution_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> FailureDiagnosisResponse:
    view = await FailureRepairService(session).diagnose(
        actor=current_user,
        project_id=project_id,
        execution_id=execution_id,
    )
    return FailureDiagnosisResponse(
        execution_id=view.execution.id,
        workflow_id=view.workflow_id,
        diagnosis=view.diagnosis,
    )


@router.post(
    "/repair-proposals",
    response_model=RepairProposalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_repair_proposal(
    project_id: UUID,
    execution_id: UUID,
    payload: RepairProposalCreate,
    session: SessionDependency,
    current_user: CurrentUser,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=200),
    ],
) -> RepairProposalResponse:
    service = FailureRepairService(session)
    prepared = await service.prepare_repair_proposal(
        actor=current_user,
        project_id=project_id,
        execution_id=execution_id,
        payload=payload,
    )

    async def persist() -> RepairProposalResponse:
        view = await service.persist_repair_proposal(prepared)
        return RepairProposalResponse(
            execution_id=execution_id,
            diagnosis=prepared.diagnosis,
            proposal=flow_spec_change_set_detail(view),
        )

    response = await IdempotencyService(session).run(
        key=idempotency_key,
        project_id=project_id,
        actor_key=f"user:{current_user.id}",
        operation=f"failure_repair.propose:{execution_id}",
        request_payload=payload.model_dump(mode="json"),
        action=persist,
    )
    return RepairProposalResponse.model_validate(response)
