from uuid import UUID

from fastapi import APIRouter, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.errors import AppError
from app.schemas.organizations import (
    OrganizationCreate,
    OrganizationMemberResponse,
    OrganizationMemberUpsert,
    OrganizationResponse,
    OrganizationUpdate,
    ServiceAccountCreate,
    ServiceAccountIssuedResponse,
    ServiceAccountResponse,
)
from app.services.organizations import OrganizationAccess, OrganizationService
from app.services.service_accounts import IssuedServiceAccount, ServiceAccountService

router = APIRouter(prefix="/organizations")


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    session: SessionDependency, current_user: CurrentUser
) -> list[OrganizationResponse]:
    items = await OrganizationService(session).list(actor=current_user)
    return [_organization_response(item) for item in items]


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> OrganizationResponse:
    item = await OrganizationService(session).create(
        actor=current_user,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
    )
    return _organization_response(item)


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: UUID, session: SessionDependency, current_user: CurrentUser
) -> OrganizationResponse:
    return _organization_response(
        await OrganizationService(session).get(actor=current_user, organization_id=organization_id)
    )


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: UUID,
    payload: OrganizationUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> OrganizationResponse:
    return _organization_response(
        await OrganizationService(session).update(
            actor=current_user,
            organization_id=organization_id,
            name=payload.name,
            description=payload.description,
            enabled=payload.enabled,
        )
    )


@router.get("/{organization_id}/members", response_model=list[OrganizationMemberResponse])
async def list_organization_members(
    organization_id: UUID, session: SessionDependency, current_user: CurrentUser
) -> list[OrganizationMemberResponse]:
    members = await OrganizationService(session).list_members(
        actor=current_user,
        organization_id=organization_id,
    )
    return [OrganizationMemberResponse.model_validate(item) for item in members]


@router.put(
    "/{organization_id}/members/{user_id}",
    response_model=OrganizationMemberResponse,
)
async def upsert_organization_member(
    organization_id: UUID,
    user_id: UUID,
    payload: OrganizationMemberUpsert,
    session: SessionDependency,
    current_user: CurrentUser,
) -> OrganizationMemberResponse:
    if payload.user_id != user_id:
        raise AppError(code="USER_ID_MISMATCH", message="成员 ID 不一致", status_code=422)
    member = await OrganizationService(session).upsert_member(
        actor=current_user,
        organization_id=organization_id,
        user_id=user_id,
        role=payload.role,
    )
    return OrganizationMemberResponse.model_validate(member)


@router.delete("/{organization_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_organization_member(
    organization_id: UUID,
    user_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> None:
    await OrganizationService(session).remove_member(
        actor=current_user,
        organization_id=organization_id,
        user_id=user_id,
    )


@router.get(
    "/{organization_id}/service-accounts",
    response_model=list[ServiceAccountResponse],
)
async def list_service_accounts(
    organization_id: UUID, session: SessionDependency, current_user: CurrentUser
) -> list[ServiceAccountResponse]:
    accounts = await ServiceAccountService(session).list(
        actor=current_user,
        organization_id=organization_id,
    )
    return [ServiceAccountResponse.model_validate(item) for item in accounts]


@router.post(
    "/{organization_id}/service-accounts",
    response_model=ServiceAccountIssuedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_service_account(
    organization_id: UUID,
    payload: ServiceAccountCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ServiceAccountIssuedResponse:
    issued = await ServiceAccountService(session).create(
        actor=current_user,
        organization_id=organization_id,
        name=payload.name,
        account_key=payload.account_key,
        scopes=payload.scopes,
        expires_at=payload.expires_at,
        metadata=payload.metadata,
    )
    return _issued_service_account_response(issued)


@router.post(
    "/{organization_id}/service-accounts/{account_id}/rotate",
    response_model=ServiceAccountIssuedResponse,
)
async def rotate_service_account(
    organization_id: UUID,
    account_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ServiceAccountIssuedResponse:
    issued = await ServiceAccountService(session).rotate(
        actor=current_user,
        organization_id=organization_id,
        account_id=account_id,
    )
    return _issued_service_account_response(issued)


@router.post(
    "/{organization_id}/service-accounts/{account_id}/revoke",
    response_model=ServiceAccountResponse,
)
async def revoke_service_account(
    organization_id: UUID,
    account_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ServiceAccountResponse:
    account = await ServiceAccountService(session).revoke(
        actor=current_user,
        organization_id=organization_id,
        account_id=account_id,
    )
    return ServiceAccountResponse.model_validate(account)


def _organization_response(item: OrganizationAccess) -> OrganizationResponse:
    organization = item.organization
    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        description=organization.description,
        enabled=organization.enabled,
        created_by_id=organization.created_by_id,
        role=item.role,
        member_count=item.member_count,
        created_at=organization.created_at,
        updated_at=organization.updated_at,
    )


def _issued_service_account_response(issued: IssuedServiceAccount) -> ServiceAccountIssuedResponse:
    response = ServiceAccountResponse.model_validate(issued.account)
    return ServiceAccountIssuedResponse(
        **response.model_dump(),
        token=issued.token,
    )
