"""Sanitize persisted canonical contracts and recalculate semantic fingerprints."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.redaction import (
    RedactionMode,
    RedactionPolicy,
    reset_redaction_policy,
    set_redaction_policy,
)
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
        # Historical security erasure must run regardless of the installation
        # output policy.  The runtime default is intentionally OFF, but this
        # migration is the one-time boundary that removes legacy plaintext
        # values from persisted contracts.
        policy_token = set_redaction_policy(
            RedactionPolicy(
                mode=RedactionMode.ON,
                source="migration",
                policy_version=1,
            )
        )
        try:
            sanitized = sanitize_contract_payload(raw).payload
            fingerprint = semantic_contract_fingerprint(sanitized)
        finally:
            reset_redaction_policy(policy_token)
        connection.execute(
            versions.update()
            .where(versions.c.id == row["id"])
            .values(
                canonical_contract=sanitized,
                contract_fingerprint=fingerprint,
                contract_completeness=str(sanitized["completeness"]),
            )
        )


def downgrade() -> None:
    # Security erasure is intentionally irreversible. Downgrade changes only the
    # Alembic revision marker and must never recreate removed Secret/PII values.
    pass
