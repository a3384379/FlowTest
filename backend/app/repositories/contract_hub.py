from collections.abc import Sequence
from datetime import UTC
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import and_, case, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.service_catalog import ServiceContractVersion
from app.models.contracts import (
    ContractRun,
    DeploymentCompatibilityCheck,
    PactContractVersion,
    PactProviderVerification,
    ServiceCatalogEntry,
)
from app.repositories.catalog_paging import ranked_catalog_page


class ContractHubRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add_service(self, model: ServiceCatalogEntry) -> None:
        self._session.add(model)

    async def get_service(self, service_id: UUID) -> ServiceCatalogEntry | None:
        return await self._session.get(ServiceCatalogEntry, service_id)

    async def find_service_by_name(
        self, *, project_id: UUID, display_name: str
    ) -> ServiceCatalogEntry | None:
        return (
            await self._session.execute(
                select(ServiceCatalogEntry).where(
                    ServiceCatalogEntry.project_id == project_id,
                    ServiceCatalogEntry.display_name == display_name,
                )
            )
        ).scalar_one_or_none()

    async def find_service_by_key(
        self, *, project_id: UUID, service_key: str
    ) -> ServiceCatalogEntry | None:
        return (
            await self._session.execute(
                select(ServiceCatalogEntry).where(
                    ServiceCatalogEntry.project_id == project_id,
                    ServiceCatalogEntry.service_key == service_key,
                )
            )
        ).scalar_one_or_none()

    async def list_services(self, *, project_id: UUID) -> list[ServiceCatalogEntry]:
        return list(
            (
                await self._session.scalars(
                    select(ServiceCatalogEntry)
                    .where(ServiceCatalogEntry.project_id == project_id)
                    .order_by(ServiceCatalogEntry.display_name)
                )
            ).all()
        )

    async def page_services(
        self, *, project_id: UUID, search: str, offset: int, limit: int
    ) -> tuple[list[ServiceCatalogEntry], int]:
        query = select(ServiceCatalogEntry.id.label("item_id")).where(
            ServiceCatalogEntry.project_id == project_id
        )
        if search:
            query = query.where(
                or_(
                    ServiceCatalogEntry.display_name.icontains(search, autoescape=True),
                    ServiceCatalogEntry.service_key.icontains(search, autoescape=True),
                    ServiceCatalogEntry.description.icontains(search, autoescape=True),
                )
            )
        ranked = query.add_columns(
            func.row_number()
            .over(order_by=(ServiceCatalogEntry.display_name, ServiceCatalogEntry.id))
            .label("position")
        ).cte()
        page = ranked_catalog_page(ranked, offset, limit)
        rows = (
            await self._session.execute(
                select(ServiceCatalogEntry, page.c.total)
                .select_from(page)
                .outerjoin(ServiceCatalogEntry, ServiceCatalogEntry.id == page.c.item_id)
                .order_by(page.c.position)
            )
        ).all()
        return [row[0] for row in rows if row[0] is not None], int(rows[0][1])

    async def page_service_versions(
        self, *, project_id: UUID, service_id: UUID, offset: int, limit: int
    ) -> tuple[list[ServiceContractVersion], int]:
        openapi = select(
            ContractRun.id.label("item_id"),
            literal("openapi").label("kind"),
            ContractRun.provider_version.label("version"),
            ContractRun.source_name,
            literal("provider").label("service_role"),
            ContractRun.status,
            ContractRun.created_at,
        ).where(ContractRun.project_id == project_id, ContractRun.provider_service_id == service_id)
        pact = select(
            PactContractVersion.id.label("item_id"),
            literal("pact").label("kind"),
            PactContractVersion.consumer_version.label("version"),
            PactContractVersion.source_name,
            case(
                (
                    and_(
                        PactContractVersion.consumer_service_id == service_id,
                        PactContractVersion.provider_service_id == service_id,
                    ),
                    "both",
                ),
                (PactContractVersion.consumer_service_id == service_id, "consumer"),
                else_="provider",
            ).label("service_role"),
            literal("completed").label("status"),
            PactContractVersion.created_at,
        ).where(
            PactContractVersion.project_id == project_id,
            or_(
                PactContractVersion.consumer_service_id == service_id,
                PactContractVersion.provider_service_id == service_id,
            ),
        )
        history = union_all(openapi, pact).subquery()
        ranked = select(
            history,
            func.row_number()
            .over(order_by=(history.c.created_at.desc(), history.c.item_id.desc(), history.c.kind))
            .label("position"),
        ).cte()
        page = ranked_catalog_page(ranked, offset, limit)
        rows = (await self._session.execute(select(page).order_by(page.c.position))).all()
        return [
            ServiceContractVersion(
                id=row.item_id,
                kind=cast(Literal["openapi", "pact"], row.kind),
                version=row.version,
                source_name=row.source_name,
                service_role=cast(Literal["provider", "consumer", "both"], row.service_role),
                status=cast(Literal["completed", "failed"], row.status),
                created_at=row.created_at
                if row.created_at.utcoffset() is not None
                else row.created_at.replace(tzinfo=UTC),
            )
            for row in rows
            if row.item_id is not None
        ], int(rows[0].total)

    def add_pact(self, model: PactContractVersion) -> None:
        self._session.add(model)

    async def get_pact(self, pact_id: UUID) -> PactContractVersion | None:
        return await self._session.get(PactContractVersion, pact_id)

    async def find_pact_by_hash(
        self, *, project_id: UUID, consumer_version: str, content_sha256: str
    ) -> PactContractVersion | None:
        return (
            await self._session.execute(
                select(PactContractVersion).where(
                    PactContractVersion.project_id == project_id,
                    PactContractVersion.consumer_version == consumer_version,
                    PactContractVersion.content_sha256 == content_sha256,
                )
            )
        ).scalar_one_or_none()

    async def list_pacts(self, *, project_id: UUID) -> list[PactContractVersion]:
        return list(
            (
                await self._session.scalars(
                    select(PactContractVersion)
                    .where(PactContractVersion.project_id == project_id)
                    .order_by(PactContractVersion.created_at.desc())
                )
            ).all()
        )

    def add_verification(self, model: PactProviderVerification) -> None:
        self._session.add(model)

    async def list_verifications(
        self, *, project_id: UUID, pact_ids: Sequence[UUID] | None = None
    ) -> list[PactProviderVerification]:
        filters = [PactProviderVerification.project_id == project_id]
        if pact_ids is not None:
            if not pact_ids:
                return []
            filters.append(PactProviderVerification.pact_contract_version_id.in_(pact_ids))
        return list(
            (
                await self._session.scalars(
                    select(PactProviderVerification)
                    .where(*filters)
                    .order_by(PactProviderVerification.created_at.desc())
                )
            ).all()
        )

    async def list_openapi_runs_for_provider(
        self, *, project_id: UUID, provider_service_id: UUID
    ) -> list[ContractRun]:
        return list(
            (
                await self._session.scalars(
                    select(ContractRun)
                    .where(
                        ContractRun.project_id == project_id,
                        ContractRun.provider_service_id == provider_service_id,
                    )
                    .order_by(ContractRun.created_at.desc())
                )
            ).all()
        )

    async def list_openapi_runs(self, *, project_id: UUID) -> list[ContractRun]:
        return list(
            (
                await self._session.scalars(
                    select(ContractRun)
                    .where(ContractRun.project_id == project_id)
                    .order_by(ContractRun.created_at.desc())
                )
            ).all()
        )

    def add_deployment_check(self, model: DeploymentCompatibilityCheck) -> None:
        self._session.add(model)

    async def list_deployment_checks(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[DeploymentCompatibilityCheck], int]:
        filters = (DeploymentCompatibilityCheck.project_id == project_id,)
        items = list(
            (
                await self._session.scalars(
                    select(DeploymentCompatibilityCheck)
                    .where(*filters)
                    .order_by(DeploymentCompatibilityCheck.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(DeploymentCompatibilityCheck).where(*filters)
        )
        return items, int(total or 0)

    async def contract_counts(self, *, project_id: UUID) -> tuple[int, int]:
        openapi = await self._session.scalar(
            select(func.count())
            .select_from(ContractRun)
            .where(ContractRun.project_id == project_id)
        )
        pact = await self._session.scalar(
            select(func.count())
            .select_from(PactContractVersion)
            .where(PactContractVersion.project_id == project_id)
        )
        return int(openapi or 0), int(pact or 0)

    async def breaking_change_count(self, *, project_id: UUID) -> int:
        runs = (
            await self._session.scalars(
                select(ContractRun.breaking_changes).where(ContractRun.project_id == project_id)
            )
        ).all()
        return sum(len(items) for items in runs)
