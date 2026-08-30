"""Add sandbox preview approvals, environment classification, and execution evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0050"
down_revision: str | None = "20260830_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("environments") as batch:
        batch.add_column(
            sa.Column(
                "classification",
                sa.String(length=24),
                server_default="unclassified",
                nullable=False,
            )
        )
        batch.create_check_constraint(
            op.f("ck_environments_environment_classification"),
            "classification IN ('unclassified', 'test', 'sandbox', 'staging', 'production')",
        )
    op.create_index(
        op.f("ix_environments_classification"),
        "environments",
        ["classification"],
        unique=False,
    )
    _create_preview_approvals()
    _add_preview_execution_contract()


def _create_preview_approvals() -> None:
    op.create_table(
        "sandbox_preview_approvals",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("change_set_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("environment_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("executor_kind", sa.String(length=24), nullable=False),
        sa.Column("executor_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("context_revision_id", sa.Uuid(), nullable=False),
        sa.Column("context_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("budget", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "executor_kind IN ('user', 'service_account')",
            name=op.f("ck_sandbox_preview_approvals_preview_approval_executor_kind"),
        ),
        sa.CheckConstraint(
            "(consumed_at IS NULL AND execution_id IS NULL) OR "
            "(consumed_at IS NOT NULL AND execution_id IS NOT NULL)",
            name=op.f("ck_sandbox_preview_approvals_preview_approval_consumption"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
            name=op.f("fk_sandbox_preview_approvals_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name=op.f("fk_sandbox_preview_approvals_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["change_set_id"],
            ["ai_change_sets.id"],
            ondelete="CASCADE",
            name=op.f("fk_sandbox_preview_approvals_change_set_id_ai_change_sets"),
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            ondelete="RESTRICT",
            name=op.f("fk_sandbox_preview_approvals_environment_id_environments"),
        ),
        sa.ForeignKeyConstraint(
            ["context_revision_id"],
            ["test_context_revisions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_sandbox_preview_approvals_context_revision_id_test_context_revisions"),
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["workflow_executions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_sandbox_preview_approvals_execution_id_workflow_executions"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_sandbox_preview_approvals_created_by_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sandbox_preview_approvals")),
    )
    for column in (
        "organization_id",
        "project_id",
        "change_set_id",
        "environment_id",
        "executor_kind",
        "executor_id",
        "proposal_fingerprint",
        "context_revision_id",
        "context_fingerprint",
        "expires_at",
        "consumed_at",
        "execution_id",
        "created_by_id",
    ):
        op.create_index(
            op.f(f"ix_sandbox_preview_approvals_{column}"),
            "sandbox_preview_approvals",
            [column],
            unique=False,
        )


def _add_preview_execution_contract() -> None:
    with op.batch_alter_table("workflow_executions") as batch:
        batch.alter_column("workflow_id", existing_type=sa.Uuid(), nullable=True)
        batch.alter_column("workflow_version_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(
            sa.Column(
                "run_purpose", sa.String(length=16), server_default="standard", nullable=False
            )
        )
        batch.add_column(sa.Column("source_change_set_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("preview_approval_id", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column("preview_budget", sa.JSON(), server_default="{}", nullable=False)
        )
        batch.add_column(
            sa.Column("preview_evidence", sa.JSON(), server_default="{}", nullable=False)
        )
        batch.create_foreign_key(
            op.f("fk_workflow_executions_source_change_set_id_ai_change_sets"),
            "ai_change_sets",
            ["source_change_set_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            op.f("fk_workflow_executions_preview_approval_id_sandbox_preview_approvals"),
            "sandbox_preview_approvals",
            ["preview_approval_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            op.f("ck_workflow_executions_workflow_execution_run_purpose"),
            "(run_purpose = 'standard' AND workflow_id IS NOT NULL "
            "AND workflow_version_id IS NOT NULL AND source_change_set_id IS NULL "
            "AND preview_approval_id IS NULL) OR "
            "(run_purpose = 'preview' AND source_change_set_id IS NOT NULL "
            "AND preview_approval_id IS NOT NULL)",
        )
    for column in ("run_purpose", "source_change_set_id", "preview_approval_id"):
        op.create_index(
            op.f(f"ix_workflow_executions_{column}"),
            "workflow_executions",
            [column],
            unique=False,
        )


def downgrade() -> None:
    preview_count = (
        op.get_bind()
        .execute(sa.text("SELECT COUNT(*) FROM workflow_executions WHERE run_purpose = 'preview'"))
        .scalar_one()
    )
    if preview_count:
        raise RuntimeError(
            "Cannot downgrade sandbox preview while preview executions exist; "
            "retain the current application or restore the verified pre-upgrade recovery point"
        )
    for column in ("preview_approval_id", "source_change_set_id", "run_purpose"):
        op.drop_index(op.f(f"ix_workflow_executions_{column}"), table_name="workflow_executions")
    with op.batch_alter_table("workflow_executions") as batch:
        batch.drop_constraint(
            op.f("ck_workflow_executions_workflow_execution_run_purpose"), type_="check"
        )
        batch.drop_constraint(
            op.f("fk_workflow_executions_preview_approval_id_sandbox_preview_approvals"),
            type_="foreignkey",
        )
        batch.drop_constraint(
            op.f("fk_workflow_executions_source_change_set_id_ai_change_sets"),
            type_="foreignkey",
        )
        batch.drop_column("preview_evidence")
        batch.drop_column("preview_budget")
        batch.drop_column("preview_approval_id")
        batch.drop_column("source_change_set_id")
        batch.drop_column("run_purpose")
        batch.alter_column("workflow_version_id", existing_type=sa.Uuid(), nullable=False)
        batch.alter_column("workflow_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_table("sandbox_preview_approvals")
    op.drop_index(op.f("ix_environments_classification"), table_name="environments")
    with op.batch_alter_table("environments") as batch:
        batch.drop_constraint(op.f("ck_environments_environment_classification"), type_="check")
        batch.drop_column("classification")
