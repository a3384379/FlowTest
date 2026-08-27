from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organizations import Organization, OrganizationMember, ServiceAccount


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, organization_id: UUID) -> Organization | None:
        return await self._session.get(Organization, organization_id)

    async def get_by_slug(self, slug: str) -> Organization | None:
        return cast(
            Organization | None,
            await self._session.scalar(select(Organization).where(Organization.slug == slug)),
        )

    async def list_for_user(self, user_id: UUID) -> list[tuple[Organization, OrganizationMember]]:
        rows = await self._session.execute(
            select(Organization, OrganizationMember)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(
                OrganizationMember.user_id == user_id,
                Organization.enabled.is_(True),
            )
            .order_by(Organization.created_at, Organization.id)
        )
        return list(rows.tuples())

    async def list_all(self) -> list[Organization]:
        return list(
            (
                await self._session.scalars(
                    select(Organization)
                    .where(Organization.enabled.is_(True))
                    .order_by(Organization.name)
                )
            ).all()
        )

    async def get_member(
        self, *, organization_id: UUID, user_id: UUID
    ) -> OrganizationMember | None:
        return cast(
            OrganizationMember | None,
            await self._session.scalar(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == organization_id,
                    OrganizationMember.user_id == user_id,
                )
            ),
        )

    async def list_members(self, organization_id: UUID) -> list[OrganizationMember]:
        return list(
            (
                await self._session.scalars(
                    select(OrganizationMember)
                    .where(OrganizationMember.organization_id == organization_id)
                    .order_by(OrganizationMember.created_at)
                )
            ).all()
        )

    async def count_members(self, organization_id: UUID) -> int:
        value = await self._session.scalar(
            select(func.count())
            .select_from(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
        )
        return int(value or 0)

    async def count_owners(self, organization_id: UUID) -> int:
        value = await self._session.scalar(
            select(func.count())
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.role == "owner",
            )
        )
        return int(value or 0)

    async def find_service_account_by_name(
        self, *, organization_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> ServiceAccount | None:
        statement = select(ServiceAccount).where(
            ServiceAccount.organization_id == organization_id,
            ServiceAccount.name == name,
        )
        if excluding_id is not None:
            statement = statement.where(ServiceAccount.id != excluding_id)
        return cast(ServiceAccount | None, await self._session.scalar(statement))

    async def find_service_account_by_key(
        self, *, organization_id: UUID, account_key: str, excluding_id: UUID | None = None
    ) -> ServiceAccount | None:
        statement = select(ServiceAccount).where(
            ServiceAccount.organization_id == organization_id,
            ServiceAccount.account_key == account_key,
        )
        if excluding_id is not None:
            statement = statement.where(ServiceAccount.id != excluding_id)
        return cast(ServiceAccount | None, await self._session.scalar(statement))

    async def get_service_account(self, account_id: UUID) -> ServiceAccount | None:
        return await self._session.get(ServiceAccount, account_id)

    async def find_service_account_by_token(self, token_hash: str) -> ServiceAccount | None:
        return cast(
            ServiceAccount | None,
            await self._session.scalar(
                select(ServiceAccount).where(ServiceAccount.token_hash == token_hash)
            ),
        )

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        return list(
            (
                await self._session.scalars(
                    select(ServiceAccount)
                    .where(ServiceAccount.organization_id == organization_id)
                    .order_by(ServiceAccount.created_at.desc())
                )
            ).all()
        )

    def add(self, entity: Organization | OrganizationMember | ServiceAccount) -> None:
        self._session.add(entity)

    async def delete(self, entity: OrganizationMember | ServiceAccount) -> None:
        await self._session.delete(entity)
