"""Add project retention policy.

Revision ID: 20260809_0010
Revises: 20260809_0009
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0010"
down_revision: str | None = "20260809_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("retention_days", sa.Integer(), server_default="90", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_projects_retention_days"),
        "projects",
        "retention_days BETWEEN 1 AND 3650",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_projects_retention_days"), "projects", type_="check")
    op.drop_column("projects", "retention_days")
