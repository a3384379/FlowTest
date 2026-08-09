"""Add immutable test cases, suites, and generic plan targets.

Revision ID: 20260810_0012
Revises: 20260809_0011
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0012"
down_revision: str | None = "20260809_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_test_case_tables()
    _create_test_suite_tables()
    _upgrade_test_plan_items()
    _upgrade_test_plan_run_items()


def downgrade() -> None:
    _downgrade_test_plan_run_items()
    _downgrade_test_plan_items()
    op.drop_index(
        op.f("ix_test_suite_version_items_test_case_id"),
        table_name="test_suite_version_items",
    )
    op.drop_index(
        op.f("ix_test_suite_version_items_test_suite_version_id"),
        table_name="test_suite_version_items",
    )
    op.drop_table("test_suite_version_items")
    op.drop_index(op.f("ix_test_suite_versions_test_suite_id"), table_name="test_suite_versions")
    op.drop_table("test_suite_versions")
    op.drop_index(op.f("ix_test_suites_folder_id"), table_name="test_suites")
    op.drop_index(op.f("ix_test_suites_project_id"), table_name="test_suites")
    op.drop_table("test_suites")
    op.drop_index(op.f("ix_test_case_versions_test_case_id"), table_name="test_case_versions")
    op.drop_table("test_case_versions")
    op.drop_index(op.f("ix_test_cases_folder_id"), table_name="test_cases")
    op.drop_index(op.f("ix_test_cases_is_template"), table_name="test_cases")
    op.drop_index(op.f("ix_test_cases_project_id"), table_name="test_cases")
    op.drop_table("test_cases")


def _create_test_case_tables() -> None:
    op.create_table(
        "test_cases",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("folder_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("tags", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("is_template", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("draft_definition", sa.JSON(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "current_version IS NULL OR current_version >= 1",
            name=op.f("ck_test_cases_test_case_current_version"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_test_cases_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["folders.id"],
            name=op.f("fk_test_cases_folder_id_folders"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_test_cases_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_cases")),
        sa.UniqueConstraint("project_id", "name", name="uq_test_cases_project_name"),
    )
    op.create_index(op.f("ix_test_cases_project_id"), "test_cases", ["project_id"])
    op.create_index(op.f("ix_test_cases_folder_id"), "test_cases", ["folder_id"])
    op.create_index(op.f("ix_test_cases_is_template"), "test_cases", ["is_template"])
    op.create_table(
        "test_case_versions",
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("change_note", sa.Text(), server_default="", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_test_case_versions_test_case_version_number")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_test_case_versions_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"],
            ["test_cases.id"],
            name=op.f("fk_test_case_versions_test_case_id_test_cases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_case_versions")),
        sa.UniqueConstraint("test_case_id", "version", name="uq_test_case_versions_case_version"),
    )
    op.create_index(
        op.f("ix_test_case_versions_test_case_id"), "test_case_versions", ["test_case_id"]
    )


def _create_test_suite_tables() -> None:
    op.create_table(
        "test_suites",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("folder_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("tags", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("draft_definition", sa.JSON(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "current_version IS NULL OR current_version >= 1",
            name=op.f("ck_test_suites_test_suite_current_version"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_test_suites_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["folders.id"],
            name=op.f("fk_test_suites_folder_id_folders"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_test_suites_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_suites")),
        sa.UniqueConstraint("project_id", "name", name="uq_test_suites_project_name"),
    )
    op.create_index(op.f("ix_test_suites_project_id"), "test_suites", ["project_id"])
    op.create_index(op.f("ix_test_suites_folder_id"), "test_suites", ["folder_id"])
    op.create_table(
        "test_suite_versions",
        sa.Column("test_suite_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("change_note", sa.Text(), server_default="", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_test_suite_versions_test_suite_version_number")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_test_suite_versions_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["test_suite_id"],
            ["test_suites.id"],
            name=op.f("fk_test_suite_versions_test_suite_id_test_suites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_suite_versions")),
        sa.UniqueConstraint(
            "test_suite_id", "version", name="uq_test_suite_versions_suite_version"
        ),
    )
    op.create_index(
        op.f("ix_test_suite_versions_test_suite_id"),
        "test_suite_versions",
        ["test_suite_id"],
    )
    op.create_table(
        "test_suite_version_items",
        sa.Column("test_suite_version_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_version", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "position >= 0",
            name=op.f("ck_test_suite_version_items_test_suite_version_item_position"),
        ),
        sa.CheckConstraint(
            "test_case_version >= 1",
            name=op.f("ck_test_suite_version_items_test_suite_item_case_version"),
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"],
            ["test_cases.id"],
            name=op.f("fk_test_suite_version_items_test_case_id_test_cases"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["test_suite_version_id"],
            ["test_suite_versions.id"],
            name=op.f("fk_test_suite_version_items_test_suite_version_id_test_suite_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_suite_version_items")),
        sa.UniqueConstraint(
            "test_suite_version_id",
            "position",
            name="uq_test_suite_version_items_version_position",
        ),
    )
    op.create_index(
        op.f("ix_test_suite_version_items_test_suite_version_id"),
        "test_suite_version_items",
        ["test_suite_version_id"],
    )
    op.create_index(
        op.f("ix_test_suite_version_items_test_case_id"),
        "test_suite_version_items",
        ["test_case_id"],
    )


def _upgrade_test_plan_items() -> None:
    op.drop_constraint(
        op.f("ck_test_plan_items_test_plan_item_workflow_version"),
        "test_plan_items",
        type_="check",
    )
    op.alter_column("test_plan_items", "workflow_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("test_plan_items", "environment_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column(
        "test_plan_items", "workflow_version", existing_type=sa.Integer(), nullable=True
    )
    op.add_column(
        "test_plan_items",
        sa.Column("target_type", sa.String(length=16), server_default="workflow", nullable=False),
    )
    op.add_column("test_plan_items", sa.Column("target_id", sa.Uuid(), nullable=True))
    op.add_column("test_plan_items", sa.Column("target_version", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE test_plan_items SET target_id = workflow_id, target_version = workflow_version"
    )
    op.alter_column("test_plan_items", "target_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("test_plan_items", "target_version", existing_type=sa.Integer(), nullable=False)
    op.create_index(op.f("ix_test_plan_items_target_id"), "test_plan_items", ["target_id"])
    op.create_check_constraint(
        op.f("ck_test_plan_items_test_plan_item_target_type"),
        "test_plan_items",
        "target_type IN ('workflow', 'case', 'suite')",
    )
    op.create_check_constraint(
        op.f("ck_test_plan_items_test_plan_item_target_version"),
        "test_plan_items",
        "target_version >= 1",
    )
    op.create_check_constraint(
        op.f("ck_test_plan_items_test_plan_item_workflow_target"),
        "test_plan_items",
        "target_type != 'workflow' OR "
        "(workflow_id IS NOT NULL AND environment_id IS NOT NULL AND workflow_version >= 1)",
    )


def _upgrade_test_plan_run_items() -> None:
    op.add_column(
        "test_plan_run_items",
        sa.Column("target_type", sa.String(length=16), server_default="workflow", nullable=False),
    )
    op.add_column("test_plan_run_items", sa.Column("target_id", sa.Uuid(), nullable=True))
    op.add_column("test_plan_run_items", sa.Column("target_version", sa.Integer(), nullable=True))
    op.add_column(
        "test_plan_run_items",
        sa.Column("target_snapshot", sa.JSON(), server_default="{}", nullable=False),
    )
    op.execute(
        "UPDATE test_plan_run_items SET target_id = workflow_id, target_version = workflow_version"
    )
    op.alter_column("test_plan_run_items", "target_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column(
        "test_plan_run_items", "target_version", existing_type=sa.Integer(), nullable=False
    )
    op.create_index(op.f("ix_test_plan_run_items_target_id"), "test_plan_run_items", ["target_id"])
    op.create_check_constraint(
        op.f("ck_test_plan_run_items_test_plan_run_item_target_type"),
        "test_plan_run_items",
        "target_type IN ('workflow', 'case')",
    )
    op.create_check_constraint(
        op.f("ck_test_plan_run_items_test_plan_run_item_target_version"),
        "test_plan_run_items",
        "target_version >= 1",
    )


def _downgrade_test_plan_run_items() -> None:
    op.drop_constraint(
        op.f("ck_test_plan_run_items_test_plan_run_item_target_version"),
        "test_plan_run_items",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_test_plan_run_items_test_plan_run_item_target_type"),
        "test_plan_run_items",
        type_="check",
    )
    op.drop_index(op.f("ix_test_plan_run_items_target_id"), table_name="test_plan_run_items")
    op.drop_column("test_plan_run_items", "target_snapshot")
    op.drop_column("test_plan_run_items", "target_version")
    op.drop_column("test_plan_run_items", "target_id")
    op.drop_column("test_plan_run_items", "target_type")


def _downgrade_test_plan_items() -> None:
    op.execute("DELETE FROM test_plan_items WHERE target_type != 'workflow'")
    op.drop_constraint(
        op.f("ck_test_plan_items_test_plan_item_workflow_target"),
        "test_plan_items",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_test_plan_items_test_plan_item_target_version"),
        "test_plan_items",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_test_plan_items_test_plan_item_target_type"),
        "test_plan_items",
        type_="check",
    )
    op.drop_index(op.f("ix_test_plan_items_target_id"), table_name="test_plan_items")
    op.drop_column("test_plan_items", "target_version")
    op.drop_column("test_plan_items", "target_id")
    op.drop_column("test_plan_items", "target_type")
    op.alter_column(
        "test_plan_items", "workflow_version", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column("test_plan_items", "environment_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("test_plan_items", "workflow_id", existing_type=sa.Uuid(), nullable=False)
    op.create_check_constraint(
        op.f("ck_test_plan_items_test_plan_item_workflow_version"),
        "test_plan_items",
        "workflow_version >= 1",
    )
