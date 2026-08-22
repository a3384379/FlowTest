"""Bootstrap the current schema for the single-process runtime.

Standalone installs intentionally do not invoke a separate migration container.  The
database is created from the checked-in SQLAlchemy metadata on first start and is
stamped with the latest migration revision.  Subsequent schema changes still use
Alembic; the stamp keeps the normal migration tooling aware of the installed baseline.
"""

from sqlalchemy import text

from app.core.database import engine
from app.models import Base

BASELINE_REVISION = "20260822_0032"


async def initialize_standalone_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS flowtest_standalone_meta "
                "(key VARCHAR(100) PRIMARY KEY, value VARCHAR(500) NOT NULL)"
            )
        )
        await connection.execute(
            text(
                "INSERT OR IGNORE INTO flowtest_standalone_meta (key, value) "
                "VALUES ('schema_baseline', :revision)"
            ),
            {"revision": BASELINE_REVISION},
        )
        await connection.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        await connection.execute(
            text(
                "INSERT INTO alembic_version (version_num) "
                "SELECT :revision WHERE NOT EXISTS (SELECT 1 FROM alembic_version)"
            ),
            {"revision": BASELINE_REVISION},
        )
