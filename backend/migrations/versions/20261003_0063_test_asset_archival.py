"""Retain immutable test assets and history when removing catalog entries."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261003_0063"
down_revision: str | None = "20260928_0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("test_cases", "test_suites"):
        op.add_column(table, sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index(f"ix_{table}_archived_at", table, ["archived_at"])
        op.create_index(
            f"ix_{table}_project_folder_active", table, ["project_id", "archived_at", "folder_id"]
        )


def downgrade() -> None:
    for table in ("test_suites", "test_cases"):
        op.drop_index(f"ix_{table}_project_folder_active", table_name=table)
        op.drop_index(f"ix_{table}_archived_at", table_name=table)
        op.drop_column(table, "archived_at")
