from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.api.v1.endpoints.flow_spec import flow_spec_change_set_detail
from app.schemas.maintenance_proposals import MaintenanceProposalCreate, MaintenanceProposalResponse
from app.services.idempotency import IdempotencyService
from app.services.maintenance_proposals import MaintenanceProposalService

router = APIRouter(prefix="/projects/{project_id}/workflows/{workflow_id}")


@router.post(
    "/maintenance-proposals",
    response_model=MaintenanceProposalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_maintenance_proposal(
    project_id: UUID,
    workflow_id: UUID,
    payload: MaintenanceProposalCreate,
    session: SessionDependency,
    current_user: CurrentUser,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
) -> MaintenanceProposalResponse:
    service = MaintenanceProposalService(session)
    prepared = await service.prepare(
        actor=current_user, project_id=project_id, workflow_id=workflow_id, payload=payload
    )

    async def persist() -> MaintenanceProposalResponse:
        view, provenance = await service.persist(prepared)
        return MaintenanceProposalResponse(
            provenance=provenance, proposal=flow_spec_change_set_detail(view)
        )

    response = await IdempotencyService(session).run(
        key=idempotency_key,
        project_id=project_id,
        actor_key=f"user:{current_user.id}",
        operation=f"maintenance.propose:{workflow_id}",
        request_payload=payload.model_dump(mode="json"),
        action=persist,
    )
    return MaintenanceProposalResponse.model_validate(response)
