"""Preserve Evidence Bundle provider provenance."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0047"
down_revision: str | None = "20260828_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = "ck_context_evidence_items_context_evidence_source_type"
_LEGACY_SOURCE_TYPES = (
    "source_type IN ('repository', 'contract', 'data_profile', 'existing_test', "
    "'workflow', 'runtime', 'database')"
)
_PROVENANCE_SOURCE_TYPES = (
    "source_type IN ('repository', 'contract', 'data_profile', "
    "'service_topology', 'existing_test', 'workflow', 'runtime', 'change', "
    "'user_confirmed_rule', 'database')"
)


def upgrade() -> None:
    with op.batch_alter_table("context_evidence_items") as batch:
        batch.drop_constraint(op.f(_CONSTRAINT_NAME), type_="check")
        batch.create_check_constraint(op.f(_CONSTRAINT_NAME), _PROVENANCE_SOURCE_TYPES)


def downgrade() -> None:
    # Revision completeness snapshots embed provider types even before evidence exists.
    # Keeping either those snapshots or new-type evidence would leave unreadable 0046
    # contexts. Quoted-token matching is portable across PostgreSQL JSON and SQLite JSON
    # text; declared CASCADE relationships remove each incompatible context atomically.
    op.execute(
        "DELETE FROM test_contexts WHERE id IN ("
        "SELECT DISTINCT revisions.context_id FROM test_context_revisions AS revisions "
        "WHERE CAST(revisions.completeness AS TEXT) LIKE '%\"service_topology\"%' "
        "OR CAST(revisions.completeness AS TEXT) LIKE '%\"change\"%' "
        "OR CAST(revisions.completeness AS TEXT) LIKE '%\"user_confirmed_rule\"%' "
        "OR EXISTS (SELECT 1 FROM context_evidence_items AS evidence "
        "WHERE evidence.context_revision_id = revisions.id "
        "AND evidence.source_type IN "
        "('service_topology', 'change', 'user_confirmed_rule')))"
    )
    with op.batch_alter_table("context_evidence_items") as batch:
        batch.drop_constraint(op.f(_CONSTRAINT_NAME), type_="check")
        batch.create_check_constraint(op.f(_CONSTRAINT_NAME), _LEGACY_SOURCE_TYPES)
