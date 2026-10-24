from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import standalone_schema
from app.models import Base
from app.models.self_tests import SelfTestInstallation


@pytest.mark.asyncio
async def test_existing_standalone_installation_upgrades_host_capabilities_without_data_loss(
    tmp_path,
    monkeypatch,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'existing.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    identifier = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(
                SelfTestInstallation(
                    id=identifier,
                    project_id=uuid4(),
                    binding_id=uuid4(),
                    template_id="core-v1",
                    template_version="1.0.0",
                    pack_digest="1" * 64,
                    status="needs_input",
                    binding_fingerprint="2" * 64,
                    environment_fingerprint="3" * 64,
                    idempotency_key="old-installation",
                    request_digest="4" * 64,
                    created_by_id=uuid4(),
                )
            )
            await session.commit()
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE self_test_installations DROP COLUMN registered_capabilities")
            )
        monkeypatch.setattr(standalone_schema, "engine", engine)
        await standalone_schema.initialize_standalone_database()
        async with sessions() as session:
            installed = await session.get(SelfTestInstallation, identifier)
            assert installed is not None
            assert installed.registered_capabilities == []
            assert installed.status == "needs_input" and installed.binding_fingerprint == "2" * 64
            installed.registered_capabilities = ["install", "deterministic_mcp"]
            await session.commit()
        await standalone_schema.initialize_standalone_database()
        async with sessions() as session:
            installed = await session.get(SelfTestInstallation, identifier)
            assert installed is not None
            assert installed.registered_capabilities == ["install", "deterministic_mcp"]
            assert installed.idempotency_key == "old-installation"
    finally:
        await engine.dispose()
