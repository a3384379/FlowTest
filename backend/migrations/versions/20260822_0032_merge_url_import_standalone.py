"""Merge URL import metadata with the Standalone baseline.

The Standalone baseline was shipped before URL imports were added.  The merge
revision keeps that baseline upgradeable and backfills the new columns when an
existing SQLite database is upgraded in place.  Fresh databases already have
the columns from SQLAlchemy metadata, so the operation is a no-op for them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0032"
down_revision: tuple[str, str] = ("20260816_0031", "20260821_0029")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(bind: sa.Connection, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _index_names(bind: sa.Connection, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def _ensure_import_run_columns(bind: sa.Connection) -> None:
    columns = _column_names(bind, "import_runs")
    if "source_kind" not in columns:
        op.add_column(
            "import_runs",
            sa.Column("source_kind", sa.String(length=16), server_default="file", nullable=False),
        )
        columns.add("source_kind")
    if "source_key" not in columns:
        op.add_column("import_runs", sa.Column("source_key", sa.String(length=512)))
        op.execute(
            sa.text(
                "UPDATE import_runs SET source_key = 'file:' || source_name "
                "WHERE source_key IS NULL"
            )
        )
        if bind.dialect.name != "sqlite":
            op.alter_column("import_runs", "source_key", nullable=False)
    if "source_url" not in columns:
        op.add_column("import_runs", sa.Column("source_url", sa.String(length=2048)))
    if "document_url" not in columns:
        op.add_column("import_runs", sa.Column("document_url", sa.String(length=2048)))
        op.execute(
            sa.text(
                "UPDATE import_runs SET document_url = source_url "
                "WHERE source_kind = 'url' AND source_url IS NOT NULL"
            )
        )
    if "ix_import_runs_source_key" not in _index_names(bind, "import_runs"):
        op.create_index("ix_import_runs_source_key", "import_runs", ["source_key"])


def _ensure_api_definition_columns(bind: sa.Connection) -> None:
    columns = _column_names(bind, "api_definitions")
    if "import_source_key" not in columns:
        op.add_column("api_definitions", sa.Column("import_source_key", sa.String(length=512)))
        op.execute(
            sa.text(
                "UPDATE api_definitions SET import_source_key = 'file:' || import_source "
                "WHERE import_source IS NOT NULL AND import_source_key IS NULL"
            )
        )
    if "ix_api_definitions_import_source_key" not in _index_names(bind, "api_definitions"):
        op.create_index(
            "ix_api_definitions_import_source_key",
            "api_definitions",
            ["import_source_key"],
        )


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "import_runs" in tables:
        _ensure_import_run_columns(bind)
    if "api_definitions" in tables:
        _ensure_api_definition_columns(bind)


def downgrade() -> None:
    # Merge revisions do not own either parent branch's schema changes.
    pass
