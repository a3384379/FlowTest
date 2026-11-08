"""Persist bounded worker ownership so interrupted plans can settle without replay."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261024_0068"
down_revision: str | None = "20261023_0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("test_plan_runs", sa.Column("worker_lease_owner", sa.String(36), nullable=True))
    op.add_column(
        "test_plan_runs",
        sa.Column("worker_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_test_plan_runs_worker_lease_expires_at", "test_plan_runs", ["worker_lease_expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_test_plan_runs_worker_lease_expires_at", table_name="test_plan_runs")
    op.drop_column("test_plan_runs", "worker_lease_expires_at")
    op.drop_column("test_plan_runs", "worker_lease_owner")
