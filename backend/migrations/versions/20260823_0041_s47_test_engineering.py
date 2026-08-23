"""Persist evidence-driven test designs for S47."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0041"
down_revision: str | None = "20260823_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE organization_key_versions "
            "SET migration_status = 'planned', migrated_at = NULL "
            "WHERE migration_status = 'migrated'"
        )
    )
    with op.batch_alter_table("test_designs") as batch:
        batch.add_column(sa.Column("scenarios", sa.JSON(), server_default="[]", nullable=False))
        batch.add_column(sa.Column("evidence_refs", sa.JSON(), server_default="[]", nullable=False))
        batch.add_column(sa.Column("warnings", sa.JSON(), server_default="[]", nullable=False))
        batch.add_column(sa.Column("confidence", sa.Float(), server_default="1", nullable=False))
        batch.add_column(
            sa.Column("review_requirements", sa.JSON(), server_default="[]", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("test_designs") as batch:
        batch.drop_column("review_requirements")
        batch.drop_column("confidence")
        batch.drop_column("warnings")
        batch.drop_column("evidence_refs")
        batch.drop_column("scenarios")
    op.execute(
        sa.text(
            "UPDATE organization_key_versions "
            "SET migration_status = 'migrated', migrated_at = activated_at "
            "WHERE status = 'active' AND migration_status = 'planned'"
        )
    )
