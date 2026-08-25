"""Add immutable semantic-gap waiver revisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0045"
down_revision: str | None = "20260823_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "semantic_gap_waivers",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=True),
    )
    op.add_column(
        "semantic_gap_waivers",
        sa.Column("supersedes_waiver_id", sa.Uuid(), nullable=True),
    )
    waivers = sa.table("semantic_gap_waivers", sa.column("revision", sa.Integer()))
    op.execute(waivers.update().where(waivers.c.revision.is_(None)).values(revision=1))
    with op.batch_alter_table("semantic_gap_waivers") as batch:
        batch.alter_column("revision", existing_type=sa.Integer(), nullable=False)
        batch.drop_constraint("uq_semantic_gap_waiver_run_gap", type_="unique")
        batch.create_unique_constraint(
            "uq_semantic_gap_waiver_run_gap_revision",
            ["regression_run_id", "gap_key", "revision"],
        )
        batch.create_check_constraint("semantic_gap_waiver_revision_positive", "revision >= 1")
        batch.create_foreign_key(
            "fk_semantic_gap_waiver_supersedes",
            "semantic_gap_waivers",
            ["supersedes_waiver_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        op.f("ix_semantic_gap_waivers_supersedes_waiver_id"),
        "semantic_gap_waivers",
        ["supersedes_waiver_id"],
        unique=False,
    )


def downgrade() -> None:
    # Revision history cannot be represented by 0044. Retain the latest revision
    # for each run/gap before restoring the original uniqueness contract.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM semantic_gap_waivers AS older "
            "WHERE EXISTS (SELECT 1 FROM semantic_gap_waivers AS newer "
            "WHERE newer.regression_run_id = older.regression_run_id "
            "AND newer.gap_key = older.gap_key AND newer.revision > older.revision)"
        )
    )
    op.drop_index(
        op.f("ix_semantic_gap_waivers_supersedes_waiver_id"),
        table_name="semantic_gap_waivers",
    )
    with op.batch_alter_table("semantic_gap_waivers") as batch:
        batch.drop_constraint("fk_semantic_gap_waiver_supersedes", type_="foreignkey")
        batch.drop_constraint("semantic_gap_waiver_revision_positive", type_="check")
        batch.drop_constraint("uq_semantic_gap_waiver_run_gap_revision", type_="unique")
        batch.create_unique_constraint(
            "uq_semantic_gap_waiver_run_gap",
            ["regression_run_id", "gap_key"],
        )
        batch.drop_column("supersedes_waiver_id")
        batch.drop_column("revision")
