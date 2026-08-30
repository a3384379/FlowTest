# Product copy intentionally uses Chinese punctuation.

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.errors import AppError
from app.domain.governance import QuotaRule as DomainQuotaRule
from app.domain.governance import parse_quota_policies
from app.schemas.common import Page
from app.schemas.governance import (
    OrganizationAuditLogResponse,
    OrganizationGovernanceResponse,
    OrganizationGovernanceUpdate,
    OrganizationKeyRotationPrepare,
    OrganizationKeyVersionResponse,
    OrganizationSecurityResponse,
    RunnerGovernancePoolSummary,
    RunnerGovernanceSummary,
    SupportBundleRedactionResponse,
)
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
from app.services.organization_governance import OrganizationGovernanceService
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


@router.get("/{organization_id}/governance", response_model=OrganizationGovernanceResponse)
async def get_organization_governance(
    organization_id: UUID, session: SessionDependency, current_user: CurrentUser
) -> OrganizationGovernanceResponse:
    policy = await OrganizationGovernanceService(session).get(
        actor=current_user, organization_id=organization_id
    )
    return _governance_response(policy)


@router.patch("/{organization_id}/governance", response_model=OrganizationGovernanceResponse)
async def update_organization_governance(
    organization_id: UUID,
    payload: OrganizationGovernanceUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> OrganizationGovernanceResponse:
    policy = await OrganizationGovernanceService(session).update(
        actor=current_user,
        organization_id=organization_id,
        audit_retention_days=payload.audit_retention_days,
        quota_policies=(
            {
                key.value: DomainQuotaRule(
                    mode=value.mode,
                    limit=value.limit,
                    warn_at=value.warn_at,
                )
                for key, value in payload.quota_policies.items()
            }
            if payload.quota_policies is not None
            else None
        ),
        runner_policy=payload.runner_policy,
    )
    return _governance_response(policy)


@router.get(
    "/{organization_id}/audit-logs",
    response_model=Page[OrganizationAuditLogResponse],
)
async def list_organization_audit_logs(
    organization_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    action: str | None = Query(default=None, max_length=100),
    resource_type: str | None = Query(default=None, max_length=100),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> Page[OrganizationAuditLogResponse]:
    logs, total = await OrganizationGovernanceService(session).list_audit_logs(
        actor=current_user,
        organization_id=organization_id,
        action=action,
        resource_type=resource_type,
        created_from=created_from,
        created_to=created_to,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return Page(
        items=[OrganizationAuditLogResponse.model_validate(item) for item in logs],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{organization_id}/runner-governance",
    response_model=RunnerGovernanceSummary,
)
async def get_runner_governance(
    organization_id: UUID, session: SessionDependency, current_user: CurrentUser
) -> RunnerGovernanceSummary:
    pools, counts = await OrganizationGovernanceService(session).runner_summary(
        actor=current_user, organization_id=organization_id
    )
    summaries = [
        RunnerGovernancePoolSummary(
            id=pool.id,
            name=pool.name,
            runner_type=pool.runner_type,
            runtime=pool.runtime,
            enabled=pool.enabled,
            max_concurrency=pool.max_concurrency,
            current_load=counts.get(pool.id, (0, 0))[1],
            runner_count=counts.get(pool.id, (0, 0))[0],
        )
        for pool in pools
    ]
    return RunnerGovernanceSummary(
        organization_id=organization_id,
        pool_count=len(pools),
        runner_count=sum(item.runner_count for item in summaries),
        current_load=sum(item.current_load for item in summaries),
        capacity=sum(item.max_concurrency for item in summaries),
        pools=summaries,
    )


@router.get(
    "/{organization_id}/security",
    response_model=OrganizationSecurityResponse,
)
async def get_organization_security(
    organization_id: UUID, session: SessionDependency, current_user: CurrentUser
) -> OrganizationSecurityResponse:
    records = await OrganizationGovernanceService(session).security(
        actor=current_user, organization_id=organization_id
    )
    return OrganizationSecurityResponse(
        organization_id=organization_id,
        active_key_version=records.policy.active_key_version,
        key_versions=[
            OrganizationKeyVersionResponse.model_validate(item) for item in records.key_versions
        ],
    )


@router.post(
    "/{organization_id}/security/key-rotation/prepare",
    response_model=OrganizationKeyVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建组织数据加密密钥轮换版本",
)
async def prepare_organization_key_rotation(
    organization_id: UUID,
    payload: OrganizationKeyRotationPrepare,
    session: SessionDependency,
    current_user: CurrentUser,
) -> OrganizationKeyVersionResponse:
    version = await OrganizationGovernanceService(session).prepare_key_rotation(
        actor=current_user,
        organization_id=organization_id,
        key_reference=payload.key_reference,
        key_fingerprint=payload.key_fingerprint,
    )
    return OrganizationKeyVersionResponse.model_validate(version)


@router.post(
    "/{organization_id}/security/key-rotation/{key_version_id}/apply",
    response_model=OrganizationKeyVersionResponse,
    summary="重加密、校验并激活组织密钥版本",
)
async def apply_organization_key_rotation(
    organization_id: UUID,
    key_version_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> OrganizationKeyVersionResponse:
    version = await OrganizationGovernanceService(session).apply_key_rotation(
        actor=current_user, organization_id=organization_id, key_version_id=key_version_id
    )
    return OrganizationKeyVersionResponse.model_validate(version)


@router.post(
    "/{organization_id}/security/key-rotation/{key_version_id}/rollback",
    response_model=OrganizationKeyVersionResponse,
    summary="重加密回上一组织密钥版本",
)
async def rollback_organization_key_rotation(
    organization_id: UUID,
    key_version_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> OrganizationKeyVersionResponse:
    version = await OrganizationGovernanceService(session).rollback_key_rotation(
        actor=current_user, organization_id=organization_id, key_version_id=key_version_id
    )
    return OrganizationKeyVersionResponse.model_validate(version)


@router.get(
    "/{organization_id}/support-bundle/redaction",
    response_model=SupportBundleRedactionResponse,
)
async def get_support_bundle_redaction(
    organization_id: UUID, session: SessionDependency, current_user: CurrentUser
) -> SupportBundleRedactionResponse:
    manifest = await OrganizationGovernanceService(session).support_bundle_redaction(
        actor=current_user, organization_id=organization_id
    )
    return SupportBundleRedactionResponse.model_validate(manifest)


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


def _governance_response(policy: object) -> OrganizationGovernanceResponse:
    from app.models.governance import OrganizationGovernance
    from app.schemas.governance import QuotaRule, RunnerGovernancePolicy

    if not isinstance(policy, OrganizationGovernance):
        raise TypeError("organization governance policy is required")
    parsed = parse_quota_policies(policy.quota_policies)
    quota_policies = {
        dimension: QuotaRule(
            mode=rule.mode,
            limit=rule.limit,
            warn_at=rule.warn_at,
        )
        for dimension, rule in parsed.items()
    }
    runner_policy = RunnerGovernancePolicy.model_validate(policy.runner_policy)
    return OrganizationGovernanceResponse(
        organization_id=policy.organization_id,
        audit_retention_days=policy.audit_retention_days,
        quota_policies=quota_policies,
        runner_policy=runner_policy,
        active_key_version=policy.active_key_version,
        updated_at=policy.updated_at,
    )
