from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.models.contracts import ContractRun, GeneratedContractCase
from app.repositories.catalog_paging import ranked_catalog_page


class ContractRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add_run(self, model: ContractRun) -> None:
        self._session.add(model)

    def add_cases(self, models: list[GeneratedContractCase]) -> None:
        self._session.add_all(models)

    async def get_run(self, run_id: UUID) -> ContractRun | None:
        return await self._session.get(ContractRun, run_id)

    async def get_case(self, case_id: UUID) -> GeneratedContractCase | None:
        return await self._session.get(GeneratedContractCase, case_id)

    async def get_case_for_update(self, case_id: UUID) -> GeneratedContractCase | None:
        result = await self._session.execute(
            select(GeneratedContractCase)
            .where(GeneratedContractCase.id == case_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def list_runs(
        self, *, project_id: UUID, offset: int, limit: int, search: str = ""
    ) -> tuple[list[ContractRun], int]:
        filters = [ContractRun.project_id == project_id]
        if search:
            filters.append(ContractRun.source_name.icontains(search, autoescape=True))
        ranked = (
            select(
                ContractRun.id.label("item_id"),
                func.row_number()
                .over(order_by=(ContractRun.created_at.desc(), ContractRun.id.desc()))
                .label("position"),
            )
            .where(*filters)
            .cte()
        )
        page = ranked_catalog_page(ranked, offset, limit)
        rows = (
            await self._session.execute(
                select(ContractRun, page.c.total)
                .options(defer(ContractRun.schema_document))
                .select_from(page)
                .outerjoin(ContractRun, ContractRun.id == page.c.item_id)
                .order_by(page.c.position)
            )
        ).all()
        return [row[0] for row in rows if row[0] is not None], int(rows[0][1])

    async def latest_run(self, *, project_id: UUID, source_name: str) -> ContractRun | None:
        result = await self._session.execute(
            select(ContractRun)
            .where(
                ContractRun.project_id == project_id,
                ContractRun.source_name == source_name,
                ContractRun.status == "completed",
            )
            .order_by(ContractRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_cases(
        self,
        *,
        run_id: UUID,
        review_status: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[GeneratedContractCase], int]:
        filters = [GeneratedContractCase.contract_run_id == run_id]
        if review_status:
            filters.append(GeneratedContractCase.review_status == review_status)
        items = list(
            (
                await self._session.scalars(
                    select(GeneratedContractCase)
                    .where(*filters)
                    .order_by(
                        GeneratedContractCase.path,
                        GeneratedContractCase.method,
                        GeneratedContractCase.generation_kind,
                        GeneratedContractCase.id,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(GeneratedContractCase).where(*filters)
        )
        return items, int(total or 0)
