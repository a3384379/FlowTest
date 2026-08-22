"""Add stable URL import source metadata.

Revision ID: 20260816_0030
Revises: 20260813_0028
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0030"
down_revision: str | None = "20260813_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "import_runs",
        sa.Column("source_kind", sa.String(length=16), server_default="file", nullable=False),
    )
    op.add_column("import_runs", sa.Column("source_key", sa.String(length=512)))
    op.add_column("import_runs", sa.Column("source_url", sa.String(length=2048)))
    op.execute(sa.text("UPDATE import_runs SET source_key = 'file:' || source_name"))
    op.alter_column("import_runs", "source_key", nullable=False)
    op.create_check_constraint(
        "import_run_source_kind",
        "import_runs",
        "source_kind IN ('file', 'url')",
    )
    op.create_index(op.f("ix_import_runs_source_key"), "import_runs", ["source_key"])

    op.add_column("api_definitions", sa.Column("import_source_key", sa.String(length=512)))
    op.execute(
        sa.text(
            "UPDATE api_definitions "
            "SET import_source_key = 'file:' || import_source "
            "WHERE import_source IS NOT NULL"
        )
    )
    op.create_index(
        op.f("ix_api_definitions_import_source_key"),
        "api_definitions",
        ["import_source_key"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_api_definitions_import_source_key"),
        table_name="api_definitions",
    )
    op.drop_column("api_definitions", "import_source_key")

    op.drop_index(op.f("ix_import_runs_source_key"), table_name="import_runs")
    op.drop_constraint("import_run_source_kind", "import_runs", type_="check")
    op.drop_column("import_runs", "source_url")
    op.drop_column("import_runs", "source_key")
    op.drop_column("import_runs", "source_kind")
