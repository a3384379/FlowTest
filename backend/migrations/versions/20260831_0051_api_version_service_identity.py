"""Persist immutable service identity on each API version."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0051"
down_revision: str | None = "20260830_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("api_versions") as batch:
        batch.add_column(sa.Column("service_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_api_versions_service_id_services"),
            "services",
            ["service_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.execute(
        sa.text(
            "UPDATE api_versions SET service_id = ("
            "SELECT api_definitions.service_id FROM api_definitions "
            "WHERE api_definitions.id = api_versions.api_definition_id"
            ")"
        )
    )
    op.create_index(
        op.f("ix_api_versions_service_id"),
        "api_versions",
        ["service_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_api_versions_service_id"), table_name="api_versions")
    with op.batch_alter_table("api_versions") as batch:
        batch.drop_constraint(
            op.f("fk_api_versions_service_id_services"),
            type_="foreignkey",
        )
        batch.drop_column("service_id")
