"""Add the project outbound policy compatibility toggle."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0033"
down_revision: str | None = "20260822_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(bind: sa.Connection, name: str) -> bool:
    return any(column["name"] == name for column in sa.inspect(bind).get_columns("projects"))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "outbound_policy_enabled"):
        op.add_column(
            "projects",
            sa.Column(
                "outbound_policy_enabled",
                sa.Boolean(),
                server_default=sa.true(),
                nullable=False,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "outbound_policy_enabled"):
        op.drop_column("projects", "outbound_policy_enabled")
