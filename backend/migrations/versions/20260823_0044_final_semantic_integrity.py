"""Close S47.3 canonical history and semantic gap waiver integrity."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migrations_support.canonical_contract_v2 import clean_historical_contract

revision: str = "20260823_0044"
down_revision: str | None = "20260823_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_semantic_gap_waivers()
    _clean_canonical_contract_history()


def _create_semantic_gap_waivers() -> None:
    op.create_table(
        "semantic_gap_waivers",
        sa.Column("regression_run_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("gap_key", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("approved_by_id", sa.Uuid(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operation_identity", sa.JSON(), nullable=False),
        sa.Column("semantic_requirement", sa.JSON(), nullable=False),
        sa.Column("requirement_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["regression_run_id"],
            ["change_regression_runs.id"],
            name="fk_semantic_gap_waiver_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_semantic_gap_waiver_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["users.id"],
            name="fk_semantic_gap_waiver_approver",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_semantic_gap_waivers")),
        sa.UniqueConstraint(
            "regression_run_id",
            "gap_key",
            name="uq_semantic_gap_waiver_run_gap",
        ),
    )
    for column in (
        "approved_at",
        "expires_at",
        "gap_key",
        "project_id",
        "regression_run_id",
        "requirement_fingerprint",
    ):
        op.create_index(
            op.f(f"ix_semantic_gap_waivers_{column}"),
            "semantic_gap_waivers",
            [column],
            unique=False,
        )


def _clean_canonical_contract_history() -> None:
    connection = op.get_bind()
    versions = sa.table(
        "api_versions",
        sa.column("id"),
        sa.column("canonical_contract", sa.JSON()),
        sa.column("contract_fingerprint", sa.String()),
        sa.column("contract_completeness", sa.String()),
    )
    rows = list(
        connection.execute(sa.select(versions.c.id, versions.c.canonical_contract)).mappings()
    )
    for row in rows:
        raw = row["canonical_contract"]
        if not isinstance(raw, dict) or not raw:
            continue
        cleaned = clean_historical_contract(raw)
        connection.execute(
            versions.update()
            .where(versions.c.id == row["id"])
            .values(
                canonical_contract=cleaned.payload,
                contract_fingerprint=cleaned.fingerprint,
                contract_completeness=cleaned.completeness,
            )
        )


def downgrade() -> None:
    # Canonical safety cleanup is intentionally irreversible: downgrade never restores
    # removed plaintext, invalid keyword values, or legacy unsalted enum hashes.
    for column in (
        "requirement_fingerprint",
        "regression_run_id",
        "project_id",
        "gap_key",
        "expires_at",
        "approved_at",
    ):
        op.drop_index(
            op.f(f"ix_semantic_gap_waivers_{column}"),
            table_name="semantic_gap_waivers",
        )
    op.drop_table("semantic_gap_waivers")
