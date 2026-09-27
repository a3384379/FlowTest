"""Runner lease outbound-policy snapshots migrate reversibly."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_runner_outbound_snapshot_migration_round_trip(monkeypatch) -> None:
    migration_path = (
        Path(__file__).parent.parent
        / "migrations/versions/20260925_0059_runner_outbound_policy_snapshot.py"
    )
    spec = spec_from_file_location("runner_outbound_snapshot_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE runner_leases (id VARCHAR(36) PRIMARY KEY)")
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            names = {column["name"] for column in inspect(connection).get_columns("runner_leases")}
            assert {"outbound_concurrency_limit", "outbound_requests_per_minute"} <= names

            migration.downgrade()
            names = {column["name"] for column in inspect(connection).get_columns("runner_leases")}
            assert names == {"id"}
    finally:
        engine.dispose()
