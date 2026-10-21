import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_design_asset_reference_upgrade_preserves_legacy_rows_and_reverses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = (
        Path(__file__).parent.parent
        / "migrations/versions/20261021_0064_test_design_materialization.py"
    )
    spec = spec_from_file_location("design_asset_migration", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql(
                "CREATE TABLE test_designs "
                "(id TEXT PRIMARY KEY, fingerprint TEXT, test_case_refs JSON)"
            )
            connection.exec_driver_sql(
                "INSERT INTO test_designs VALUES ('owned', 'original-frozen-fingerprint', '[\"testcase://original\"]')"
            )
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert (
                connection.exec_driver_sql("SELECT materialized_assets FROM test_designs").scalar()
                == "[]"
            )
            connection.exec_driver_sql(
                "UPDATE test_designs SET materialized_assets=?",
                (
                    json.dumps(
                        [
                            {
                                "scenario_id": "scenario-1",
                                "workflow_id": "original-workflow",
                                "test_case_id": "original-case",
                            }
                        ]
                    ),
                ),
            )
            migration.downgrade()
            assert "materialized_assets" not in {
                item["name"] for item in inspect(connection).get_columns("test_designs")
            }
            original = connection.exec_driver_sql(
                "SELECT fingerprint, test_case_refs FROM test_designs"
            ).one()
            assert tuple(original) == ("original-frozen-fingerprint", '["testcase://original"]')
            migration.upgrade()
            assert (
                connection.exec_driver_sql("SELECT materialized_assets FROM test_designs").scalar()
                == "[]"
            )
    finally:
        engine.dispose()
