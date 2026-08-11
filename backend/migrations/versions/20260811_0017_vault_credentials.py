"""Add Vault KV v2 credential storage metadata.

Revision ID: 20260811_0017
Revises: 20260811_0016
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0017"
down_revision: str | None = "20260811_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "credentials",
        sa.Column("secret_provider", sa.String(length=32), server_default="local", nullable=False),
    )
    op.add_column("credentials", sa.Column("provider_reference", sa.String(length=1024)))
    op.alter_column("credentials", "ciphertext", existing_type=sa.LargeBinary(), nullable=True)
    op.alter_column("credentials", "nonce", existing_type=sa.LargeBinary(length=12), nullable=True)
    op.create_index(
        op.f("ix_credentials_secret_provider"),
        "credentials",
        ["secret_provider"],
    )
    op.create_check_constraint(
        op.f("ck_credentials_credential_secret_storage"),
        "credentials",
        "(secret_provider = 'local' AND ciphertext IS NOT NULL "
        "AND nonce IS NOT NULL AND provider_reference IS NULL) OR "
        "(secret_provider = 'vault_kv_v2' AND ciphertext IS NULL "
        "AND nonce IS NULL AND provider_reference IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM credentials WHERE secret_provider = 'vault_kv_v2'
            ) THEN
                RAISE EXCEPTION
                    'Migrate Vault credentials to local storage before downgrading';
            END IF;
        END $$
        """
    )
    op.drop_constraint(
        op.f("ck_credentials_credential_secret_storage"),
        "credentials",
        type_="check",
    )
    op.drop_index(op.f("ix_credentials_secret_provider"), table_name="credentials")
    op.alter_column("credentials", "nonce", existing_type=sa.LargeBinary(length=12), nullable=False)
    op.alter_column("credentials", "ciphertext", existing_type=sa.LargeBinary(), nullable=False)
    op.drop_column("credentials", "provider_reference")
    op.drop_column("credentials", "secret_provider")
