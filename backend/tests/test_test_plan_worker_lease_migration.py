"""Worker leases upgrade and roll back without removing existing run data."""

from io import StringIO

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from test_selftest_product_migration import _migration

from app.core.standalone_schema import initialize_standalone_database
from app.models import Base


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
def test_worker_lease_upgrade_and_downgrade_compile(monkeypatch, dialect):
    migration = _migration("20261024_0068_test_plan_worker_lease.py")
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name=dialect, opts={"as_sql": True, "output_buffer": output}
    )
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    migration.downgrade()
    assert "ADD COLUMN worker_lease_owner" in output.getvalue()
    assert "DROP COLUMN worker_lease_expires_at" in output.getvalue()


def test_worker_lease_round_trip_preserves_legacy_run_and_null_ownership(monkeypatch):
    migration = _migration("20261024_0068_test_plan_worker_lease.py")
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE test_plan_runs (id INTEGER PRIMARY KEY, status TEXT)"
            )
            connection.exec_driver_sql("INSERT INTO test_plan_runs VALUES (1, 'running')")
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert connection.exec_driver_sql(
                "SELECT worker_lease_owner, worker_lease_expires_at FROM test_plan_runs"
            ).one() == (None, None)
            assert any(
                i["name"] == "ix_test_plan_runs_worker_lease_expires_at"
                for i in inspect(connection).get_indexes("test_plan_runs")
            )
            migration.downgrade()
            assert connection.exec_driver_sql("SELECT id, status FROM test_plan_runs").one() == (
                1,
                "running",
            )
            assert {c["name"] for c in inspect(connection).get_columns("test_plan_runs")} == {
                "id",
                "status",
            }
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_existing_standalone_gains_both_columns_and_expiry_index_idempotently(
    tmp_path, monkeypatch
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'prior.sqlite3'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.exec_driver_sql("DROP INDEX ix_test_plan_runs_worker_lease_expires_at")
            await connection.exec_driver_sql(
                "ALTER TABLE test_plan_runs DROP COLUMN worker_lease_expires_at"
            )
            await connection.exec_driver_sql(
                "ALTER TABLE test_plan_runs DROP COLUMN worker_lease_owner"
            )
        monkeypatch.setattr("app.core.standalone_schema.engine", engine)
        await initialize_standalone_database()
        await initialize_standalone_database()
        async with engine.begin() as connection:
            columns = await connection.run_sync(lambda c: inspect(c).get_columns("test_plan_runs"))
            indexes = await connection.run_sync(lambda c: inspect(c).get_indexes("test_plan_runs"))
            assert {"worker_lease_owner", "worker_lease_expires_at"} <= {c["name"] for c in columns}
            assert (
                sum(i["name"] == "ix_test_plan_runs_worker_lease_expires_at" for i in indexes) == 1
            )
    finally:
        await engine.dispose()
