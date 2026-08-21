from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.domain.runtime_profiles import RuntimeProfile


def _standalone_database_url() -> str:
    configured = settings.database_url.strip()
    if configured.startswith("sqlite+aiosqlite://"):
        return configured
    database_path = Path(settings.data_dir).expanduser().resolve() / "flowtest.db"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{database_path.as_posix()}"


def _engine_kwargs() -> dict[str, object]:
    if settings.runtime_profile is RuntimeProfile.STANDALONE:
        return {
            "connect_args": {"check_same_thread": False, "timeout": 30},
            "pool_pre_ping": True,
        }
    return {"pool_pre_ping": True, "pool_recycle": 300}


database_url = (
    _standalone_database_url()
    if settings.runtime_profile is RuntimeProfile.STANDALONE
    else settings.database_url
)
engine: AsyncEngine = create_async_engine(database_url, **_engine_kwargs())


if settings.runtime_profile is RuntimeProfile.STANDALONE:

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(connection: object, _record: object) -> None:
        cursor = connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()


session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


async def check_database() -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def close_database() -> None:
    await engine.dispose()
