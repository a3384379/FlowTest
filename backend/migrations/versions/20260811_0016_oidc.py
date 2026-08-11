"""Add OIDC identities and one-time login transactions.

Revision ID: 20260811_0016
Revises: 20260811_0015
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0016"
down_revision: str | None = "20260811_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("oidc_provider", sa.String(length=120)))
    op.add_column("users", sa.Column("oidc_subject", sa.String(length=255)))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True)))
    op.create_index(op.f("ix_users_oidc_provider"), "users", ["oidc_provider"])
    op.create_unique_constraint(
        "uq_users_oidc_identity",
        "users",
        ["oidc_provider", "oidc_subject"],
    )
    op.create_table(
        "oidc_login_transactions",
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("verifier_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("verifier_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_oidc_login_transactions_provider"),
        "oidc_login_transactions",
        ["provider"],
    )
    op.create_index(
        op.f("ix_oidc_login_transactions_state_hash"),
        "oidc_login_transactions",
        ["state_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_oidc_login_transactions_expires_at"),
        "oidc_login_transactions",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_table("oidc_login_transactions")
    op.drop_constraint("uq_users_oidc_identity", "users", type_="unique")
    op.drop_index(op.f("ix_users_oidc_provider"), table_name="users")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "oidc_subject")
    op.drop_column("users", "oidc_provider")
