"""Mark the legacy active key as the verified initial encryption version."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0049"
down_revision: str | None = "20260830_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY_ENVELOPE_MAGIC = b"FTK1"
_ENCRYPTED_COLUMNS = (
    ("secrets", "ciphertext"),
    ("credentials", "ciphertext"),
    ("import_runs", "payload_ciphertext"),
    ("workflow_executions", "run_payload_ciphertext"),
    ("test_plans", "webhook_secret_ciphertext"),
    ("notification_webhooks", "secret_ciphertext"),
)


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
    locations = _enveloped_ciphertext_locations(op.get_bind())
    if locations:
        joined_locations = ", ".join(locations)
        raise RuntimeError(
            "Cannot downgrade key-reference encryption while FTK1 ciphertexts exist in "
            f"{joined_locations}; keep the current application or restore the verified "
            "pre-upgrade PostgreSQL and object-storage recovery point"
        )
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


def _enveloped_ciphertext_locations(connection: sa.Connection) -> list[str]:
    locations: list[str] = []
    for table_name, column_name in _ENCRYPTED_COLUMNS:
        ciphertext = sa.column(column_name, sa.LargeBinary())
        table = sa.table(table_name, ciphertext)
        found = connection.execute(
            sa.select(sa.literal(True))
            .select_from(table)
            .where(
                ciphertext.is_not(None),
                sa.func.substr(ciphertext, 1, len(_KEY_ENVELOPE_MAGIC)) == _KEY_ENVELOPE_MAGIC,
            )
            .limit(1)
        ).scalar_one_or_none()
        if found:
            locations.append(f"{table_name}.{column_name}")
    return locations
