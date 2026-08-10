"""Add contract automation runs and reviewable generated cases.

Revision ID: 20260811_0014
Revises: 20260810_0013
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0014"
down_revision: str | None = "20260810_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contract_runs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_run_id", sa.Uuid(), nullable=True),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="completed", nullable=False),
        sa.Column("schema_document", sa.JSON(), nullable=False),
        sa.Column("diff_summary", sa.JSON(), nullable=False),
        sa.Column("breaking_changes", sa.JSON(), nullable=False),
        sa.Column("coverage", sa.JSON(), nullable=False),
        sa.Column("generated_case_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'failed')",
            name=op.f("ck_contract_runs_contract_run_status"),
        ),
        sa.ForeignKeyConstraint(
            ["baseline_run_id"],
            ["contract_runs.id"],
            name=op.f("fk_contract_runs_baseline_run_id_contract_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_contract_runs_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_contract_runs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contract_runs")),
    )
    op.create_index(op.f("ix_contract_runs_project_id"), "contract_runs", ["project_id"])
    op.create_index(op.f("ix_contract_runs_baseline_run_id"), "contract_runs", ["baseline_run_id"])
    op.create_index(op.f("ix_contract_runs_source_name"), "contract_runs", ["source_name"])
    op.create_index(op.f("ix_contract_runs_source_sha256"), "contract_runs", ["source_sha256"])
    _create_generated_cases()


def downgrade() -> None:
    op.drop_index(
        op.f("ix_generated_contract_cases_review_status"),
        table_name="generated_contract_cases",
    )
    op.drop_index(
        op.f("ix_generated_contract_cases_generation_kind"),
        table_name="generated_contract_cases",
    )
    op.drop_index(
        op.f("ix_generated_contract_cases_operation_key"),
        table_name="generated_contract_cases",
    )
    op.drop_index(
        op.f("ix_generated_contract_cases_contract_run_id"),
        table_name="generated_contract_cases",
    )
    op.drop_table("generated_contract_cases")
    op.drop_index(op.f("ix_contract_runs_source_sha256"), table_name="contract_runs")
    op.drop_index(op.f("ix_contract_runs_source_name"), table_name="contract_runs")
    op.drop_index(op.f("ix_contract_runs_baseline_run_id"), table_name="contract_runs")
    op.drop_index(op.f("ix_contract_runs_project_id"), table_name="contract_runs")
    op.drop_table("contract_runs")


def _create_generated_cases() -> None:
    op.create_table(
        "generated_contract_cases",
        sa.Column("contract_run_id", sa.Uuid(), nullable=False),
        sa.Column("operation_key", sa.String(length=64), nullable=False),
        sa.Column("operation_id", sa.String(length=200), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("generation_kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("review_note", sa.Text(), server_default="", nullable=False),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "generation_kind IN ('example', 'boundary', 'property', 'negative')",
            name=op.f("ck_generated_contract_cases_generated_contract_case_kind"),
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')",
            name=op.f("ck_generated_contract_cases_generated_case_review_status"),
        ),
        sa.ForeignKeyConstraint(
            ["contract_run_id"],
            ["contract_runs.id"],
            name=op.f("fk_generated_contract_cases_contract_run_id_contract_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["users.id"],
            name=op.f("fk_generated_contract_cases_reviewed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_contract_cases")),
        sa.UniqueConstraint(
            "contract_run_id",
            "operation_key",
            "generation_kind",
            name="uq_generated_contract_cases_run_operation_kind",
        ),
    )
    op.create_index(
        op.f("ix_generated_contract_cases_contract_run_id"),
        "generated_contract_cases",
        ["contract_run_id"],
    )
    op.create_index(
        op.f("ix_generated_contract_cases_operation_key"),
        "generated_contract_cases",
        ["operation_key"],
    )
    op.create_index(
        op.f("ix_generated_contract_cases_generation_kind"),
        "generated_contract_cases",
        ["generation_kind"],
    )
    op.create_index(
        op.f("ix_generated_contract_cases_review_status"),
        "generated_contract_cases",
        ["review_status"],
    )
