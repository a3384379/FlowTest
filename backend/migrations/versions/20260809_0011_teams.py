"""Add teams and project team grants.

Revision ID: 20260809_0011
Revises: 20260809_0010
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0011"
down_revision: str | None = "20260809_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "api_versions",
        sa.Column("extraction_rules", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "api_versions",
        sa.Column("assertions", sa.JSON(), server_default="[]", nullable=False),
    )
    op.drop_constraint(
        op.f("ck_import_runs_import_run_source_type"),
        "import_runs",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_import_runs_import_run_source_type"),
        "import_runs",
        "source_type IN ('openapi3', 'swagger2', 'postman', 'har', 'curl', 'bruno', 'excel')",
    )
    op.create_table(
        "teams",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_teams_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teams")),
    )
    op.create_index(op.f("ix_teams_name"), "teams", ["name"], unique=True)
    op.create_table(
        "team_members",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_team_members_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_team_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_members")),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),
    )
    op.create_index(op.f("ix_team_members_team_id"), "team_members", ["team_id"], unique=False)
    op.create_index(op.f("ix_team_members_user_id"), "team_members", ["user_id"], unique=False)
    op.create_table(
        "project_team_grants",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('editor', 'viewer')", name=op.f("ck_project_team_grants_team_grant_role")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_project_team_grants_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_team_grants_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_project_team_grants_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_team_grants")),
        sa.UniqueConstraint("project_id", "team_id", name="uq_project_team_grants_project_team"),
    )
    op.create_index(
        op.f("ix_project_team_grants_project_id"),
        "project_team_grants",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_project_team_grants_role"), "project_team_grants", ["role"], unique=False
    )
    op.create_index(
        op.f("ix_project_team_grants_team_id"),
        "project_team_grants",
        ["team_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_project_team_grants_team_id"), table_name="project_team_grants")
    op.drop_index(op.f("ix_project_team_grants_role"), table_name="project_team_grants")
    op.drop_index(op.f("ix_project_team_grants_project_id"), table_name="project_team_grants")
    op.drop_table("project_team_grants")
    op.drop_index(op.f("ix_team_members_user_id"), table_name="team_members")
    op.drop_index(op.f("ix_team_members_team_id"), table_name="team_members")
    op.drop_table("team_members")
    op.drop_index(op.f("ix_teams_name"), table_name="teams")
    op.drop_table("teams")
    op.drop_constraint(
        op.f("ck_import_runs_import_run_source_type"),
        "import_runs",
        type_="check",
    )
    # V1 cannot represent the four V2 import provenance labels. The normalized
    # diff/results remain usable, so map only the source label before restoring
    # the narrower V1 constraint.
    op.execute(
        "UPDATE import_runs SET source_type = 'postman' "
        "WHERE source_type IN ('har', 'curl', 'bruno', 'excel')"
    )
    op.create_check_constraint(
        op.f("ck_import_runs_import_run_source_type"),
        "import_runs",
        "source_type IN ('openapi3', 'swagger2', 'postman')",
    )
    op.drop_column("api_versions", "assertions")
    op.drop_column("api_versions", "extraction_rules")
