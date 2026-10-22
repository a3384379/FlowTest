from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.core import standalone_schema
from app.models import Base
from app.models.access import Project, User
from app.models.ai import AIChangeSet
from app.models.test_design import MaterializedAssetRecord
from app.models.test_design import TestDesign as DesignModel


@pytest.mark.asyncio
async def test_existing_standalone_design_recovers_new_column_without_changing_frozen_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'existing-design.db'}")
    monkeypatch.setattr(standalone_schema, "engine", engine)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        design_id = await _seed_design(engine)
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE test_designs DROP COLUMN materialized_assets")
            )
            columns = await connection.run_sync(
                lambda sync: inspect(sync).get_columns("test_designs")
            )
            assert {column["name"] for column in columns} == {
                column.name
                for column in DesignModel.__table__.columns
                if column.name != "materialized_assets"
            }
            assert not await standalone_schema._flow_spec_tables_need_rebuild(connection)
            original = await _frozen_design_rows(connection)

        await standalone_schema.initialize_standalone_database()
        async with engine.connect() as connection:
            assert await _frozen_design_rows(connection) == original
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            design = await session.get(DesignModel, design_id)
            assert design is not None and design.materialized_assets == []
            design.materialized_assets = _materialized_assets()
            await session.commit()
            saved_assets = design.materialized_assets
        async with engine.connect() as connection:
            saved = await _frozen_design_rows(connection)
        for _ in range(2):
            await standalone_schema.initialize_standalone_database()
            async with sessions() as session:
                design = await session.get(DesignModel, design_id)
                assert design is not None and design.materialized_assets == saved_assets
            async with engine.connect() as connection:
                assert await _frozen_design_rows(connection) == saved
                assert (await connection.execute(text("PRAGMA foreign_key_check"))).all() == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fresh_standalone_design_keeps_materialized_references_on_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fresh-design.db'}")
    monkeypatch.setattr(standalone_schema, "engine", engine)
    try:
        await standalone_schema.initialize_standalone_database()
        design_id = await _seed_design(engine)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            design = await session.get(DesignModel, design_id)
            assert design is not None and design.materialized_assets == []
            saved_assets = _materialized_assets()
            design.materialized_assets = saved_assets
            await session.commit()
        await standalone_schema.initialize_standalone_database()
        async with sessions() as session:
            design = await session.get(DesignModel, design_id)
            assert design is not None and design.materialized_assets == saved_assets
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync: inspect(sync).get_columns("test_designs")
            )
            column = next(column for column in columns if column["name"] == "materialized_assets")
            assert column["nullable"] is False and column["default"] == "'[]'"
    finally:
        await engine.dispose()


async def _seed_design(engine: AsyncEngine) -> UUID:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        actor = User(
            email="legacy-design@example.com", display_name="旧设计审核人", password_hash="unused"
        )
        session.add(actor)
        await session.flush()
        project = Project(name="旧设计项目", created_by_id=actor.id)
        session.add(project)
        await session.flush()
        change_set = AIChangeSet(
            project_id=project.id,
            title="原设计来源",
            status="accepted",
            source_snapshot={"contract": {"operation": "original-operation"}},
            source_fingerprint="b" * 64,
            source_type="rest",
            source_ref="contract://original-operation",
            actor_type="user",
            actor_id=actor.id,
            created_by_id=actor.id,
        )
        session.add(change_set)
        await session.flush()
        design = DesignModel(
            project_id=project.id,
            name="既有批准设计",
            status="approved",
            intent={"objective": "保留原目标"},
            knowledge_graph={},
            state_model={},
            scenarios=[{"id": "original-scenario"}],
            oracles=[{"id": "original-oracle"}],
            coverage={"entries": []},
            evidence_refs=[{"source_ref": "contract://original-operation"}],
            test_case_refs=["testcase://original-case"],
            fingerprint="a" * 64,
            source_change_set_id=change_set.id,
            created_by_id=actor.id,
            reviewed_by_id=actor.id,
            review_note="原审核说明",
        )
        session.add(design)
        await session.commit()
        return design.id


async def _frozen_design_rows(connection: AsyncConnection) -> list[tuple[object, ...]]:
    columns = tuple(
        column for column in DesignModel.__table__.columns if column.name != "materialized_assets"
    )
    rows = await connection.execute(select(*columns).order_by(DesignModel.id))
    return [tuple(row) for row in rows]


def _materialized_assets() -> list[MaterializedAssetRecord]:
    return [
        {
            "scenario_id": "original-scenario",
            "workflow_id": str(uuid4()),
            "test_case_id": str(uuid4()),
        }
    ]
