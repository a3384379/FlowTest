"""Make the existing change-set storage reusable for FlowSpec imports."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0036"
down_revision: str | None = "20260822_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column, table in (
        ("impact_run_id", "ai_change_sets"),
        ("release_risk_id", "ai_change_sets"),
        ("ai_job_id", "ai_change_sets"),
    ):
        op.alter_column(
            table,
            column,
            existing_type=sa.Uuid(),
            existing_nullable=False,
            nullable=True,
        )
    op.alter_column(
        "ai_change_items",
        "suggestion_id",
        existing_type=sa.Uuid(),
        existing_nullable=False,
        nullable=True,
    )
    op.add_column(
        "ai_change_sets",
        sa.Column("source_type", sa.String(length=24), server_default="ai", nullable=False),
    )
    op.add_column("ai_change_sets", sa.Column("source_ref", sa.String(length=512), nullable=True))
    op.add_column(
        "ai_change_sets",
        sa.Column("actor_type", sa.String(length=32), server_default="user", nullable=False),
    )
    op.add_column("ai_change_sets", sa.Column("actor_id", sa.Uuid(), nullable=True))
    op.add_column(
        "ai_change_sets",
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_ai_change_sets_actor_id_users"),
        "ai_change_sets",
        "users",
        ["actor_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_ai_change_sets_ai_change_set_source_type"),
        "ai_change_sets",
        "source_type IN ('ai', 'flow_spec', 'mcp', 'rest', 'cli')",
    )
    for column in ("source_type", "source_ref", "actor_type", "actor_id", "applied_at"):
        op.create_index(op.f(f"ix_ai_change_sets_{column}"), "ai_change_sets", [column])


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM ai_change_items WHERE change_set_id IN "
            "(SELECT id FROM ai_change_sets WHERE source_type = 'flow_spec')"
        )
    )
    bind.execute(sa.text("DELETE FROM ai_change_sets WHERE source_type = 'flow_spec'"))
    for column in ("applied_at", "actor_id", "actor_type", "source_ref", "source_type"):
        op.drop_index(op.f(f"ix_ai_change_sets_{column}"), table_name="ai_change_sets")
    op.drop_constraint(
        op.f("ck_ai_change_sets_ai_change_set_source_type"),
        "ai_change_sets",
        type_="check",
    )
    op.drop_constraint(
        op.f("fk_ai_change_sets_actor_id_users"), "ai_change_sets", type_="foreignkey"
    )
    for column in ("applied_at", "actor_id", "actor_type", "source_ref", "source_type"):
        op.drop_column("ai_change_sets", column)
    op.alter_column(
        "ai_change_items",
        "suggestion_id",
        existing_type=sa.Uuid(),
        existing_nullable=True,
        nullable=False,
    )
    for column in ("ai_job_id", "release_risk_id", "impact_run_id"):
        op.alter_column(
            "ai_change_sets",
            column,
            existing_type=sa.Uuid(),
            existing_nullable=True,
            nullable=False,
        )
