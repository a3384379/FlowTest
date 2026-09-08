"""Add stable project identity and organization-scoped bootstrap receipts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_0052"
down_revision: str | None = "20260831_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("external_key", sa.String(length=160), nullable=True))
        batch.create_unique_constraint(
            op.f("uq_projects_organization_external_key"),
            ["organization_id", "external_key"],
        )
    op.create_index(op.f("ix_projects_external_key"), "projects", ["external_key"], unique=False)
    op.create_table(
        "organization_idempotency_records",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("actor_key", sa.String(length=160), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
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
            name=op.f("ck_organization_idempotency_records_org_idempotency_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
            name=op.f("fk_organization_idempotency_records_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_idempotency_records")),
        sa.UniqueConstraint(
            "organization_id",
            "actor_key",
            "operation",
            "idempotency_key",
            name=op.f("uq_org_idempotency_operation_key"),
        ),
    )
    for column in ("organization_id", "expires_at"):
        op.create_index(
            op.f(f"ix_organization_idempotency_records_{column}"),
            "organization_idempotency_records",
            [column],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_organization_idempotency_records_expires_at"),
        table_name="organization_idempotency_records",
    )
    op.drop_index(
        op.f("ix_organization_idempotency_records_organization_id"),
        table_name="organization_idempotency_records",
    )
    op.drop_table("organization_idempotency_records")
    op.drop_index(op.f("ix_projects_external_key"), table_name="projects")
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint(op.f("uq_projects_organization_external_key"), type_="unique")
        batch.drop_column("external_key")
