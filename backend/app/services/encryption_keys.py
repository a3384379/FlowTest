"""Resolve organization encryption keys without exposing key material."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import DEFAULT_KEY_REFERENCE
from app.core.errors import AppError
from app.models.access import Project
from app.models.governance import OrganizationGovernance, OrganizationKeyVersion


async def active_key_reference_for_project(
    session: AsyncSession,
    project_id: UUID,
) -> str:
    organization_id = await session.scalar(
        select(Project.organization_id).where(Project.id == project_id)
    )
    if organization_id is None:
        return DEFAULT_KEY_REFERENCE
    return await active_key_reference_for_organization(session, organization_id)


async def active_key_reference_for_organization(
    session: AsyncSession,
    organization_id: UUID,
) -> str:
    policy = await session.scalar(
        select(OrganizationGovernance)
        .where(OrganizationGovernance.organization_id == organization_id)
        .with_for_update(read=True)
    )
    if policy is None:
        return DEFAULT_KEY_REFERENCE
    key = await session.scalar(
        select(OrganizationKeyVersion).where(
            OrganizationKeyVersion.organization_id == organization_id,
            OrganizationKeyVersion.version == policy.active_key_version,
        )
    )
    if key is None or key.status != "active":
        raise AppError(
            code="ACTIVE_KEY_VERSION_NOT_FOUND",
            message="当前密钥版本不存在或未激活",
            status_code=409,
        )
    return key.key_reference
