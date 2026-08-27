"""Add immutable test contexts and external evidence snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0046"
down_revision: str | None = "20260823_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_contexts",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("target_environment_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="collecting", nullable=False),
        sa.Column("current_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_type", sa.String(length=24), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('collecting', 'ready', 'incomplete', 'conflicted', 'expired', 'closed')",
            name=op.f("ck_test_contexts_test_context_status"),
        ),
        sa.CheckConstraint(
            "current_revision >= 1",
            name=op.f("ck_test_contexts_test_context_current_revision_positive"),
        ),
        sa.CheckConstraint(
            "created_by_type IN ('user', 'service_account')",
            name=op.f("ck_test_contexts_test_context_creator_type"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_test_contexts_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_test_contexts_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_environment_id"],
            ["environments.id"],
            name=op.f("fk_test_contexts_target_environment_id_environments"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_contexts")),
    )
    _create_context_indexes()
    op.create_table(
        "test_context_revisions",
        sa.Column("context_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("repository_revisions", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("contract_revisions", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("data_profile_revisions", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("existing_test_revision", sa.JSON(), nullable=True),
        sa.Column("knowledge_snapshot", sa.JSON(), nullable=False),
        sa.Column("completeness", sa.JSON(), nullable=False),
        sa.Column("conflict_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_fingerprints", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by_type", sa.String(length=24), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "revision >= 1", name=op.f("ck_test_context_revisions_test_context_revision_positive")
        ),
        sa.CheckConstraint(
            "created_by_type IN ('user', 'service_account')",
            name=op.f("ck_test_context_revisions_test_context_revision_creator_type"),
        ),
        sa.ForeignKeyConstraint(
            ["context_id"],
            ["test_contexts.id"],
            name=op.f("fk_test_context_revisions_context_id_test_contexts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_context_revisions")),
        sa.UniqueConstraint(
            "context_id",
            "revision",
            name="uq_test_context_revisions_context_revision",
        ),
    )
    op.create_index(
        op.f("ix_test_context_revisions_context_id"),
        "test_context_revisions",
        ["context_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_test_context_revisions_fingerprint"),
        "test_context_revisions",
        ["fingerprint"],
        unique=False,
    )
    op.create_index(
        op.f("ix_test_context_revisions_created_by_id"),
        "test_context_revisions",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_test_context_revisions_context_fingerprint",
        "test_context_revisions",
        ["context_id", "fingerprint"],
        unique=False,
    )
    op.create_table(
        "context_evidence_items",
        sa.Column("context_revision_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("provider_name", sa.String(length=160), nullable=False),
        sa.Column("provider_version", sa.String(length=80), nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=False),
        sa.Column("source_revision", sa.String(length=160), nullable=False),
        sa.Column("subject_ref", sa.String(length=512), nullable=False),
        sa.Column("finding_payload", sa.JSON(), nullable=False),
        sa.Column("semantic_role", sa.String(length=24), nullable=False),
        sa.Column("deterministic", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("redactions", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("warnings", sa.JSON(), server_default="[]", nullable=False),
        sa.Column(
            "data_classification",
            sa.String(length=32),
            server_default="internal_redacted",
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_context_evidence_items_context_evidence_confidence"),
        ),
        sa.CheckConstraint(
            "source_type IN ('repository', 'contract', 'data_profile', 'existing_test', "
            "'workflow', 'runtime', 'database')",
            name=op.f("ck_context_evidence_items_context_evidence_source_type"),
        ),
        sa.CheckConstraint(
            "semantic_role IN ('normative', 'observed', 'mixed', 'coverage', "
            "'supporting', 'conflict')",
            name=op.f("ck_context_evidence_items_context_evidence_semantic_role"),
        ),
        sa.CheckConstraint(
            "data_classification = 'internal_redacted'",
            name=op.f("ck_context_evidence_items_context_evidence_classification"),
        ),
        sa.ForeignKeyConstraint(
            ["context_revision_id"],
            ["test_context_revisions.id"],
            name=op.f("fk_context_evidence_items_context_revision_id_test_context_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_context_evidence_items")),
        sa.UniqueConstraint(
            "context_revision_id",
            "fingerprint",
            name="uq_context_evidence_revision_fingerprint",
        ),
    )
    _create_evidence_indexes()


def downgrade() -> None:
    op.drop_table("context_evidence_items")
    op.drop_table("test_context_revisions")
    op.drop_table("test_contexts")


def _create_context_indexes() -> None:
    for column in (
        "organization_id",
        "project_id",
        "target_environment_id",
        "status",
        "created_by_id",
        "expires_at",
        "closed_at",
    ):
        op.create_index(op.f(f"ix_test_contexts_{column}"), "test_contexts", [column])
    op.create_index(
        "ix_test_contexts_project_status",
        "test_contexts",
        ["project_id", "status"],
        unique=False,
    )


def _create_evidence_indexes() -> None:
    for column in (
        "context_revision_id",
        "source_type",
        "source_ref",
        "subject_ref",
        "semantic_role",
        "fingerprint",
        "expires_at",
    ):
        op.create_index(
            op.f(f"ix_context_evidence_items_{column}"), "context_evidence_items", [column]
        )
    op.create_index(
        "ix_context_evidence_source",
        "context_evidence_items",
        ["source_ref", "source_revision"],
        unique=False,
    )
