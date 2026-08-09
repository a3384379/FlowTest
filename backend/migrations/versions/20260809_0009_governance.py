"""Add governance, import merge, network policy, and idempotency state.

Revision ID: 20260809_0009
Revises: 20260809_0008
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0009"
down_revision: str | None = "20260809_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("outbound_allowed_hosts", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "projects",
        sa.Column("outbound_allowed_private_cidrs", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "api_definitions",
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
    )
    op.create_index(op.f("ix_api_definitions_is_active"), "api_definitions", ["is_active"])
    op.add_column(
        "import_runs",
        sa.Column("status", sa.String(length=16), server_default="applied", nullable=False),
    )
    op.add_column(
        "import_runs", sa.Column("applied_keys", sa.JSON(), server_default="[]", nullable=False)
    )
    op.add_column("import_runs", sa.Column("payload_ciphertext", sa.LargeBinary()))
    op.add_column("import_runs", sa.Column("payload_nonce", sa.LargeBinary()))
    op.add_column("import_runs", sa.Column("applied_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        op.f("ck_import_runs_import_run_status"),
        "import_runs",
        "status IN ('applied', 'preview')",
    )
    op.execute("UPDATE import_runs SET applied_at = updated_at")

    op.create_table(
        "idempotency_records",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("actor_key", sa.String(length=160), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_body", sa.JSON()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed')",
            name=op.f("ck_idempotency_records_idempotency_status"),
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "actor_key",
            "operation",
            "idempotency_key",
            name="uq_idempotency_operation_key",
        ),
    )
    op.create_index(
        op.f("ix_idempotency_records_project_id"), "idempotency_records", ["project_id"]
    )
    op.create_index(
        op.f("ix_idempotency_records_expires_at"), "idempotency_records", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_constraint(op.f("ck_import_runs_import_run_status"), "import_runs", type_="check")
    for column in (
        "applied_at",
        "payload_nonce",
        "payload_ciphertext",
        "applied_keys",
        "status",
    ):
        op.drop_column("import_runs", column)
    op.drop_index(op.f("ix_api_definitions_is_active"), table_name="api_definitions")
    op.drop_column("api_definitions", "is_active")
    op.drop_column("projects", "outbound_allowed_private_cidrs")
    op.drop_column("projects", "outbound_allowed_hosts")
