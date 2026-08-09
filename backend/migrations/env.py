import asyncio
import json
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import JSON, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def compare_server_default(
    _context: Any,
    _inspected_column: Any,
    metadata_column: Any,
    inspected_default: str | None,
    _metadata_default: Any,
    rendered_metadata_default: str | None,
) -> bool | None:
    """Compare JSON defaults without asking PostgreSQL to use JSON equality."""
    if isinstance(metadata_column.type, JSON):
        return _normalize_json_default(inspected_default) != _normalize_json_default(
            rendered_metadata_default
        )
    return None


def _normalize_json_default(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().removeprefix("(").removesuffix(")")
    normalized = normalized.split("::", maxsplit=1)[0].strip().strip("'")
    try:
        return json.dumps(json.loads(normalized), sort_keys=True, separators=(",", ":"))
    except json.JSONDecodeError:
        return normalized


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=compare_server_default,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=compare_server_default,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
