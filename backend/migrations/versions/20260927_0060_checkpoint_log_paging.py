"""Index execution checkpoints for chronological log paging."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260927_0060"
down_revision: str | None = "20260925_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_execution_checkpoints_execution_finished_id",
        "execution_checkpoints",
        ["execution_id", "finished_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_execution_checkpoints_execution_finished_id",
        table_name="execution_checkpoints",
    )
