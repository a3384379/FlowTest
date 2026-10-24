"""Freeze the capabilities actually registered by an external self-test host."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261023_0067"
down_revision: str | None = "20261023_0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "self_test_installations",
        sa.Column("registered_capabilities", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("self_test_installations", "registered_capabilities")
