"""Add typed Test Design storage and controlled-write approvals for S42."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0037"
down_revision: str | None = "20260822_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ai_change_items") as batch:
        batch.drop_constraint(op.f("ck_ai_change_items_ai_change_item_type"), type_="check")
        batch.create_check_constraint(
            op.f("ck_ai_change_items_ai_change_item_type"),
            "item_type IN ('test_case', 'workflow', 'assertion', 'test_design')",
        )

    op.create_table(
        "test_designs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("intent", sa.JSON(), nullable=False),
        sa.Column("knowledge_graph", sa.JSON(), nullable=False),
        sa.Column("state_model", sa.JSON(), nullable=False),
        sa.Column("oracles", sa.JSON(), nullable=False),
        sa.Column("coverage", sa.JSON(), nullable=False),
        sa.Column("test_case_refs", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_change_set_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), server_default="", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'rejected', 'archived')",
            name=op.f("ck_test_designs_test_design_status"),
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_change_set_id"], ["ai_change_sets.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name=op.f("uq_test_designs_project_name")),
    )
    for column in ("project_id", "status", "fingerprint", "source_change_set_id"):
        op.create_index(op.f(f"ix_test_designs_{column}"), "test_designs", [column])

    op.create_table(
        "change_set_approvals",
        sa.Column("change_set_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("approved_by_id", sa.Uuid(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name=op.f("ck_change_set_approvals_change_set_approval_decision"),
        ),
        sa.ForeignKeyConstraint(["change_set_id"], ["ai_change_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("change_set_id", name=op.f("uq_change_set_approvals_change_set")),
    )
    op.create_index(
        op.f("ix_change_set_approvals_change_set_id"),
        "change_set_approvals",
        ["change_set_id"],
    )
    op.create_index(op.f("ix_change_set_approvals_decision"), "change_set_approvals", ["decision"])


def downgrade() -> None:
    op.execute("DELETE FROM ai_change_items WHERE item_type = 'test_design'")
    op.drop_index(op.f("ix_change_set_approvals_decision"), table_name="change_set_approvals")
    op.drop_index(op.f("ix_change_set_approvals_change_set_id"), table_name="change_set_approvals")
    op.drop_table("change_set_approvals")
    for column in ("source_change_set_id", "fingerprint", "status", "project_id"):
        op.drop_index(op.f(f"ix_test_designs_{column}"), table_name="test_designs")
    op.drop_table("test_designs")
    with op.batch_alter_table("ai_change_items") as batch:
        batch.drop_constraint(op.f("ck_ai_change_items_ai_change_item_type"), type_="check")
        batch.create_check_constraint(
            op.f("ck_ai_change_items_ai_change_item_type"),
            "item_type IN ('test_case', 'workflow', 'assertion')",
        )
