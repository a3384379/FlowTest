"""Mark the legacy active key as the verified initial encryption version."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0049"
down_revision: str | None = "20260830_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    key_versions = sa.table(
        "organization_key_versions",
        sa.column("status", sa.String()),
        sa.column("migration_status", sa.String()),
        sa.column("activated_at", sa.DateTime(timezone=True)),
        sa.column("migrated_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        key_versions.update()
        .where(
            key_versions.c.status == "active",
            key_versions.c.migration_status == "planned",
        )
        .values(
            migration_status="migrated",
            migrated_at=key_versions.c.activated_at,
        )
    )


def downgrade() -> None:
    key_versions = sa.table(
        "organization_key_versions",
        sa.column("version", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("migration_status", sa.String()),
        sa.column("previous_version", sa.Integer()),
        sa.column("migrated_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        key_versions.update()
        .where(
            key_versions.c.version == 1,
            key_versions.c.status == "active",
            key_versions.c.migration_status == "migrated",
            key_versions.c.previous_version.is_(None),
        )
        .values(migration_status="planned", migrated_at=None)
    )
