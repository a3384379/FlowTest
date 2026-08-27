from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_tenant_context
from app.core.errors import AppError
from app.domain.tenant import OrganizationRole, TenantContext
from app.models.access import User
from app.models.organizations import Organization, OrganizationMember
from app.repositories.organizations import OrganizationRepository
from app.services.audit import AuditService

DEFAULT_ORGANIZATION_SLUG = "default"
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class OrganizationAccess:
    organization: Organization
    role: OrganizationRole | None
    member_count: int | None = None


class OrganizationContextService:
    """Resolve and lazily bootstrap the organization boundary for a user."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._organizations = OrganizationRepository(session)

    async def ensure_default_for_user(self, actor: User) -> OrganizationMember:
        memberships = await self._organizations.list_for_user(actor.id)
        if memberships:
            for candidate, member in memberships:
                if candidate.slug == DEFAULT_ORGANIZATION_SLUG:
                    return member
            return memberships[0][1]
        organization = await self._organizations.get_by_slug(DEFAULT_ORGANIZATION_SLUG)
        if organization is None:
            organization = Organization(
                name="Default Organization",
                slug=DEFAULT_ORGANIZATION_SLUG,
                description="迁移兼容的默认组织",
                enabled=True,
                created_by_id=actor.id,
            )
            self._organizations.add(organization)
            await self._session.flush()
        member = OrganizationMember(
            organization_id=organization.id,
            user_id=actor.id,
            role=OrganizationRole.OWNER.value
            if actor.is_system_admin
            else OrganizationRole.MEMBER.value,
        )
        self._organizations.add(member)
        await self._session.commit()
        await self._session.refresh(member)
        return member

    async def resolve(
        self,
        *,
        actor: User,
        requested_organization_id: UUID | None = None,
    ) -> TenantContext:
        if requested_organization_id is None:
            member = await self.ensure_default_for_user(actor)
            organization_id = member.organization_id
        else:
            organization_id = requested_organization_id
        organization = await self._organizations.get(organization_id)
        if organization is None or not organization.enabled:
            raise AppError(code="ORGANIZATION_NOT_FOUND", message="组织不存在", status_code=404)
        if actor.is_system_admin:
            return TenantContext(
                organization_id=organization.id,
                actor_id=actor.id,
                role=None,
                is_system_admin=True,
            )
        resolved_member = await self._organizations.get_member(
            organization_id=organization.id,
            user_id=actor.id,
        )
        if resolved_member is None:
            raise AppError(code="ORGANIZATION_NOT_FOUND", message="组织不存在", status_code=404)
        return TenantContext(
            organization_id=organization.id,
            actor_id=actor.id,
            role=OrganizationRole(resolved_member.role),
        )


class OrganizationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._organizations = OrganizationRepository(session)
        self._audit = AuditService(session)

    async def list(self, *, actor: User) -> list[OrganizationAccess]:
        if actor.is_system_admin:
            organizations = await self._organizations.list_all()
            return [OrganizationAccess(item, None) for item in organizations]
        rows = await self._organizations.list_for_user(actor.id)
        return [
            OrganizationAccess(
                organization=organization,
                role=OrganizationRole(member.role),
                member_count=None,
            )
            for organization, member in rows
        ]

    async def create(
        self,
        *,
        actor: User,
        name: str,
        slug: str | None,
        description: str,
    ) -> OrganizationAccess:
        normalized_slug = _normalize_slug(slug or name)
        if await self._organizations.get_by_slug(normalized_slug) is not None:
            raise AppError(
                code="ORGANIZATION_SLUG_EXISTS", message="组织标识已存在", status_code=409
            )
        organization = Organization(
            name=name.strip(),
            slug=normalized_slug,
            description=description.strip(),
            enabled=True,
            created_by_id=actor.id,
        )
        self._organizations.add(organization)
        await self._session.flush()
        self._organizations.add(
            OrganizationMember(
                organization_id=organization.id,
                user_id=actor.id,
                role=OrganizationRole.OWNER.value,
            )
        )
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=organization.id,
            project_id=None,
            action="organization.created",
            resource_type="organization",
            resource_id=organization.id,
        )
        await self._session.commit()
        await self._session.refresh(organization)
        return OrganizationAccess(organization=organization, role=OrganizationRole.OWNER)

    async def get(self, *, actor: User, organization_id: UUID) -> OrganizationAccess:
        organization, member = await self._authorize(actor, organization_id, "read")
        role = None if actor.is_system_admin else _required_role(member)
        return OrganizationAccess(
            organization=organization,
            role=role,
            member_count=await self._organizations.count_members(organization.id),
        )

    async def authorize(
        self,
        *,
        actor: User,
        organization_id: UUID,
        capability: str,
    ) -> OrganizationAccess:
        organization, member = await self._authorize(actor, organization_id, capability)
        role = None if actor.is_system_admin else _required_role(member)
        return OrganizationAccess(
            organization=organization,
            role=role,
        )

    async def update(
        self,
        *,
        actor: User,
        organization_id: UUID,
        name: str | None,
        description: str | None,
        enabled: bool | None,
    ) -> OrganizationAccess:
        organization, _member = await self._authorize(actor, organization_id, "manage_members")
        if name is not None:
            organization.name = name.strip()
        if description is not None:
            organization.description = description.strip()
        if enabled is not None:
            organization.enabled = enabled
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=organization.id,
            project_id=None,
            action="organization.updated",
            resource_type="organization",
            resource_id=organization.id,
        )
        await self._session.commit()
        await self._session.refresh(organization)
        return OrganizationAccess(
            organization=organization,
            role=None if actor.is_system_admin else _required_role(_member),
            member_count=await self._organizations.count_members(organization.id),
        )

    async def list_members(
        self, *, actor: User, organization_id: UUID
    ) -> Sequence[OrganizationMember]:
        await self._authorize(actor, organization_id, "read")
        return await self._organizations.list_members(organization_id)

    async def upsert_member(
        self,
        *,
        actor: User,
        organization_id: UUID,
        user_id: UUID,
        role: OrganizationRole,
    ) -> OrganizationMember:
        organization, _member = await self._authorize(actor, organization_id, "manage_members")
        if not role:
            raise AppError(
                code="INVALID_ORGANIZATION_ROLE", message="组织角色无效", status_code=422
            )
        from app.repositories.access import UserRepository

        target = await UserRepository(self._session).get(user_id)
        if target is None or not target.is_active:
            raise AppError(code="USER_NOT_FOUND", message="用户不存在", status_code=404)
        member = await self._organizations.get_member(
            organization_id=organization.id,
            user_id=user_id,
        )
        if member is None:
            from app.domain.governance import QuotaDimension
            from app.services.organization_governance import OrganizationQuotaService

            await OrganizationQuotaService(self._session).enforce(
                organization_id=organization.id,
                dimension=QuotaDimension.USER_COUNT,
            )
            member = OrganizationMember(
                organization_id=organization.id,
                user_id=user_id,
                role=role.value,
            )
            self._organizations.add(member)
        elif member.role == OrganizationRole.OWNER.value and role is not OrganizationRole.OWNER:
            if await self._organizations.count_owners(organization.id) <= 1:
                raise AppError(
                    code="ORGANIZATION_OWNER_REQUIRED",
                    message="组织至少需要一名所有者",
                    status_code=409,
                )
            member.role = role.value
        else:
            member.role = role.value
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=organization.id,
            project_id=None,
            action="organization.member_upserted",
            resource_type="organization_member",
            resource_id=member.id,
            details={"user_id": str(user_id), "role": role.value},
        )
        await self._session.commit()
        await self._session.refresh(member)
        return member

    async def remove_member(self, *, actor: User, organization_id: UUID, user_id: UUID) -> None:
        organization, _member = await self._authorize(actor, organization_id, "manage_members")
        member = await self._organizations.get_member(
            organization_id=organization.id,
            user_id=user_id,
        )
        if member is None:
            raise AppError(
                code="ORGANIZATION_MEMBER_NOT_FOUND", message="组织成员不存在", status_code=404
            )
        if (
            member.role == OrganizationRole.OWNER.value
            and await self._organizations.count_owners(organization.id) <= 1
        ):
            raise AppError(
                code="ORGANIZATION_OWNER_REQUIRED",
                message="组织至少需要一名所有者",
                status_code=409,
            )
        await self._organizations.delete(member)
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=organization.id,
            project_id=None,
            action="organization.member_removed",
            resource_type="organization_member",
            resource_id=member.id,
            details={"user_id": str(user_id)},
        )
        await self._session.commit()

    async def _authorize(
        self,
        actor: User,
        organization_id: UUID,
        capability: str,
    ) -> tuple[Organization, OrganizationMember | None]:
        organization = await self._organizations.get(organization_id)
        if organization is None or not organization.enabled:
            raise AppError(code="ORGANIZATION_NOT_FOUND", message="组织不存在", status_code=404)
        context = get_tenant_context()
        if (
            context is not None
            and not context.is_system_admin
            and context.organization_id != organization.id
        ):
            raise AppError(code="ORGANIZATION_NOT_FOUND", message="组织不存在", status_code=404)
        if actor.is_system_admin:
            return organization, None
        member = await self._organizations.get_member(
            organization_id=organization.id,
            user_id=actor.id,
        )
        if member is None or not OrganizationRole(member.role).allows(capability):
            raise AppError(
                code="ORGANIZATION_FORBIDDEN", message="没有所需的组织权限", status_code=403
            )
        return organization, member


def _normalize_slug(value: str) -> str:
    normalized = _SLUG_PATTERN.sub("-", value.strip().lower()).strip("-")
    return normalized[:80] or "organization"


def _required_role(member: OrganizationMember | None) -> OrganizationRole:
    if member is None:
        raise RuntimeError("organization member is required for a non-admin actor")
    return OrganizationRole(member.role)
