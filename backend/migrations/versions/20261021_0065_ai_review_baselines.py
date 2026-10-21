"""Freeze authorized asset baselines separately from AI input material."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261021_0065"
down_revision: str | None = "20261021_0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_change_sets",
        sa.Column("review_baselines", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("ai_change_sets", "review_baselines")
