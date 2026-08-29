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
    with op.batch_alter_table("context_evidence_items") as batch:
        batch.drop_constraint(op.f(_CONSTRAINT_NAME), type_="check")
        batch.create_check_constraint(op.f(_CONSTRAINT_NAME), _LEGACY_SOURCE_TYPES)
