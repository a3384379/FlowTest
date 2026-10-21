"""Retain the original generated asset identities independently of mutable drafts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261021_0064"
down_revision: str | None = "20261003_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "test_designs",
        sa.Column("materialized_assets", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("test_designs", "materialized_assets")
