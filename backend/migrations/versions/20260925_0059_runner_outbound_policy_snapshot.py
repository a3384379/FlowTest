"""Freeze project outbound limits on each Runner lease."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_0059"
down_revision: str | None = "20260925_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runner_leases") as batch:
        batch.add_column(sa.Column("outbound_concurrency_limit", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("outbound_requests_per_minute", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("runner_leases") as batch:
        batch.drop_column("outbound_requests_per_minute")
        batch.drop_column("outbound_concurrency_limit")
