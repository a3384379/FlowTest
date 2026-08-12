from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contracts import ContractRun, PactContractVersion
from app.models.impact import CoverageSnapshot, ImpactAssetMapping, ImpactRun, TestSelection
from app.models.performance import PerformanceScenario
from app.models.protocols import SchemaArtifact
from app.models.test_assets import TestCase
from app.models.workflows import Workflow


@dataclass(frozen=True, slots=True)
class ImpactRunBundle:
    run: ImpactRun
    selection: TestSelection
    coverage: CoverageSnapshot


class ImpactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add_mapping(self, model: ImpactAssetMapping) -> None:
        self._session.add(model)

    async def get_mapping(self, mapping_id: UUID) -> ImpactAssetMapping | None:
        return await self._session.get(ImpactAssetMapping, mapping_id)

    async def find_mapping_by_key(
        self, *, project_id: UUID, mapping_key: str
    ) -> ImpactAssetMapping | None:
        return (
            await self._session.execute(
                select(ImpactAssetMapping).where(
                    ImpactAssetMapping.project_id == project_id,
                    ImpactAssetMapping.mapping_key == mapping_key,
                )
            )
        ).scalar_one_or_none()

    async def list_mappings(
        self, *, project_id: UUID, offset: int = 0, limit: int = 2_000
    ) -> tuple[list[ImpactAssetMapping], int]:
        filters = (ImpactAssetMapping.project_id == project_id,)
        items = list(
            (
                await self._session.scalars(
                    select(ImpactAssetMapping)
                    .where(*filters)
                    .order_by(
                        ImpactAssetMapping.source_kind,
                        ImpactAssetMapping.source_selector,
                        ImpactAssetMapping.created_at,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(ImpactAssetMapping).where(*filters)
        )
        return items, int(total or 0)

    async def delete_mapping(self, model: ImpactAssetMapping) -> None:
        await self._session.delete(model)

    def add_run(self, run: ImpactRun) -> None:
        self._session.add(run)

    def add_run_evidence(self, *, selection: TestSelection, coverage: CoverageSnapshot) -> None:
        self._session.add_all((selection, coverage))

    async def list_runs(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[ImpactRun], int]:
        filters = (ImpactRun.project_id == project_id,)
        items = list(
            (
                await self._session.scalars(
                    select(ImpactRun)
                    .where(*filters)
                    .order_by(ImpactRun.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(ImpactRun).where(*filters)
        )
        return items, int(total or 0)

    async def get_run_bundle(self, run_id: UUID) -> ImpactRunBundle | None:
        row = (
            await self._session.execute(
                select(ImpactRun, TestSelection, CoverageSnapshot)
                .join(TestSelection, TestSelection.impact_run_id == ImpactRun.id)
                .join(CoverageSnapshot, CoverageSnapshot.impact_run_id == ImpactRun.id)
                .where(ImpactRun.id == run_id)
            )
        ).one_or_none()
        return ImpactRunBundle(*row) if row is not None else None

    async def get_contract_run(self, run_id: UUID) -> ContractRun | None:
        return await self._session.get(ContractRun, run_id)

    async def get_schema_artifact(self, artifact_id: UUID) -> SchemaArtifact | None:
        return await self._session.get(SchemaArtifact, artifact_id)

    async def get_test_case(self, asset_id: UUID) -> TestCase | None:
        return await self._session.get(TestCase, asset_id)

    async def get_workflow(self, asset_id: UUID) -> Workflow | None:
        return await self._session.get(Workflow, asset_id)

    async def get_pact(self, asset_id: UUID) -> PactContractVersion | None:
        return await self._session.get(PactContractVersion, asset_id)

    async def get_performance_scenario(self, asset_id: UUID) -> PerformanceScenario | None:
        return await self._session.get(PerformanceScenario, asset_id)

    async def catalog_test_cases(self, *, project_id: UUID) -> list[TestCase]:
        return list(
            (
                await self._session.scalars(
                    select(TestCase)
                    .where(TestCase.project_id == project_id)
                    .order_by(TestCase.name)
                    .limit(1_000)
                )
            ).all()
        )

    async def catalog_workflows(self, *, project_id: UUID) -> list[Workflow]:
        return list(
            (
                await self._session.scalars(
                    select(Workflow)
                    .where(Workflow.project_id == project_id)
                    .order_by(Workflow.name)
                    .limit(1_000)
                )
            ).all()
        )

    async def catalog_openapi_contracts(self, *, project_id: UUID) -> list[ContractRun]:
        return list(
            (
                await self._session.scalars(
                    select(ContractRun)
                    .where(ContractRun.project_id == project_id)
                    .order_by(ContractRun.created_at.desc())
                    .limit(1_000)
                )
            ).all()
        )

    async def catalog_pact_contracts(self, *, project_id: UUID) -> list[PactContractVersion]:
        return list(
            (
                await self._session.scalars(
                    select(PactContractVersion)
                    .where(PactContractVersion.project_id == project_id)
                    .order_by(PactContractVersion.created_at.desc())
                    .limit(1_000)
                )
            ).all()
        )

    async def catalog_performance(self, *, project_id: UUID) -> list[PerformanceScenario]:
        return list(
            (
                await self._session.scalars(
                    select(PerformanceScenario)
                    .where(PerformanceScenario.project_id == project_id)
                    .order_by(PerformanceScenario.name, PerformanceScenario.version.desc())
                    .limit(1_000)
                )
            ).all()
        )

    async def catalog_schemas(self, *, project_id: UUID) -> list[SchemaArtifact]:
        return list(
            (
                await self._session.scalars(
                    select(SchemaArtifact)
                    .where(
                        SchemaArtifact.project_id == project_id,
                        SchemaArtifact.protocol.in_(("graphql", "grpc")),
                    )
                    .order_by(SchemaArtifact.protocol, SchemaArtifact.name, SchemaArtifact.version)
                    .limit(2_000)
                )
            ).all()
        )
