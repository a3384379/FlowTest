import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_ai_review_baseline_upgrade_preserves_legacy_rows_and_reverses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path(__file__).parent.parent / "migrations/versions/20261021_0065_ai_review_baselines.py"
    spec = spec_from_file_location("ai_review_baseline_migration", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql(
                "CREATE TABLE ai_change_sets "
                "(id TEXT PRIMARY KEY, fingerprint TEXT, source_snapshot JSON)"
            )
            connection.exec_driver_sql(
                "INSERT INTO ai_change_sets VALUES ('owned', "
                "'original-frozen-fingerprint', '{\"fixed\":true}')"
            )
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert (
                connection.exec_driver_sql("SELECT review_baselines FROM ai_change_sets").scalar()
                == "[]"
            )
            connection.exec_driver_sql(
                "UPDATE ai_change_sets SET review_baselines=?",
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
            assert "review_baselines" not in {
                item["name"] for item in inspect(connection).get_columns("ai_change_sets")
            }
            original = connection.exec_driver_sql(
                "SELECT fingerprint, source_snapshot FROM ai_change_sets"
            ).one()
            assert tuple(original) == ("original-frozen-fingerprint", '{"fixed":true}')
            migration.upgrade()
            assert (
                connection.exec_driver_sql("SELECT review_baselines FROM ai_change_sets").scalar()
                == "[]"
            )
    finally:
        engine.dispose()
