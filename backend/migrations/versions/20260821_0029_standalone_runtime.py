"""Register the Standalone runtime baseline metadata table."""

from alembic import op

revision = "20260821_0029"
down_revision = "20260813_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    op.execute(
        "CREATE TABLE IF NOT EXISTS flowtest_standalone_meta "
        "(key VARCHAR(100) PRIMARY KEY, value VARCHAR(500) NOT NULL)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    op.execute("DROP TABLE IF EXISTS flowtest_standalone_meta")
