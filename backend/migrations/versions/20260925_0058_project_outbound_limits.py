"""Add opt-in project limits for outbound workflow attempts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_0058"
down_revision: str | None = "20260925_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("outbound_concurrency_limit", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("outbound_requests_per_minute", sa.Integer(), nullable=True))
        batch.create_check_constraint(
            "project_outbound_concurrency_limit",
            "outbound_concurrency_limit IS NULL OR outbound_concurrency_limit BETWEEN 1 AND 500",
        )
        batch.create_check_constraint(
            "project_outbound_requests_per_minute",
            "outbound_requests_per_minute IS NULL OR "
            "outbound_requests_per_minute BETWEEN 1 AND 60000",
        )
    op.create_table(
        "outbound_permits",
        sa.Column("permit_id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=False),
        sa.Column("expires_at_ms", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_outbound_permits_project_expiry",
        "outbound_permits",
        ["project_id", "expires_at_ms"],
    )
    op.create_table(
        "outbound_rate_windows",
        sa.Column("project_id", sa.String(length=36), primary_key=True),
        sa.Column("started_at_ms", sa.Integer(), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("outbound_rate_windows")
    op.drop_index("ix_outbound_permits_project_expiry", table_name="outbound_permits")
    op.drop_table("outbound_permits")
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint("project_outbound_requests_per_minute", type_="check")
        batch.drop_constraint("project_outbound_concurrency_limit", type_="check")
        batch.drop_column("outbound_requests_per_minute")
        batch.drop_column("outbound_concurrency_limit")
