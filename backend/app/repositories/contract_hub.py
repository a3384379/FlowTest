from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contracts import (
    ContractRun,
    DeploymentCompatibilityCheck,
    PactContractVersion,
    PactProviderVerification,
    ServiceCatalogEntry,
)


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
