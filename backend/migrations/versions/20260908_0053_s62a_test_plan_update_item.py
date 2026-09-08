"""Allow typed Test Plan update suggestions in the shared AIChangeSet lifecycle."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0053"
down_revision: str | None = "20260908_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ai_change_items") as batch:
        batch.drop_constraint(op.f("ck_ai_change_items_ai_change_item_type"), type_="check")
        batch.create_check_constraint(
            op.f("ck_ai_change_items_ai_change_item_type"),
            (
                "item_type IN ('test_case', 'workflow', 'assertion', "
                "'test_design', 'test_plan_update')"
            ),
        )


def downgrade() -> None:
    op.execute("DELETE FROM ai_change_items WHERE item_type = 'test_plan_update'")
    with op.batch_alter_table("ai_change_items") as batch:
        batch.drop_constraint(op.f("ck_ai_change_items_ai_change_item_type"), type_="check")
        batch.create_check_constraint(
            op.f("ck_ai_change_items_ai_change_item_type"),
            "item_type IN ('test_case', 'workflow', 'assertion', 'test_design')",
        )
