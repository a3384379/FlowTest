"""Add resolved document URL for Swagger UI imports.

Revision ID: 20260816_0031
Revises: 20260816_0030
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0031"
down_revision: str | None = "20260816_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("import_runs", sa.Column("document_url", sa.String(length=2048)))
    op.execute(
        sa.text(
            "UPDATE import_runs SET document_url = source_url "
            "WHERE source_kind = 'url' AND source_url IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("import_runs", "document_url")
