"""Sanitize persisted canonical contracts and recalculate semantic fingerprints."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.domain.canonical_contracts import (
    sanitize_contract_payload,
    semantic_contract_fingerprint,
)

revision: str = "20260823_0043"
down_revision: str | None = "20260823_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    versions = sa.table(
        "api_versions",
        sa.column("id"),
        sa.column("canonical_contract", sa.JSON()),
        sa.column("contract_fingerprint", sa.String()),
        sa.column("contract_completeness", sa.String()),
    )
    rows = connection.execute(sa.select(versions.c.id, versions.c.canonical_contract)).mappings()
    for row in rows:
        raw = row["canonical_contract"]
        if not isinstance(raw, dict) or not raw:
            continue
        sanitized = sanitize_contract_payload(raw).payload
        connection.execute(
            versions.update()
            .where(versions.c.id == row["id"])
            .values(
                canonical_contract=sanitized,
                contract_fingerprint=semantic_contract_fingerprint(sanitized),
                contract_completeness=str(sanitized["completeness"]),
            )
        )


def downgrade() -> None:
    # Security erasure is intentionally irreversible. Downgrade changes only the
    # Alembic revision marker and must never recreate removed Secret/PII values.
    pass
