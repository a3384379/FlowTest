"""Persist self-test installations, frozen batches and independent result projections."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261023_0066"
down_revision: str | None = "20261021_0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "self_test_installations",
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.String(200), nullable=False),
        sa.Column("template_version", sa.String(200), nullable=False),
        sa.Column("pack_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason_codes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("binding_fingerprint", sa.String(64), nullable=False),
        sa.Column("environment_fingerprint", sa.String(64), nullable=False),
        sa.Column("resource_mapping", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(200), nullable=True),
        sa.Column("host_id", sa.String(200), nullable=True),
        sa.Column("registration_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(200), nullable=True),
        sa.Column("lease_hash", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nonce_hash", sa.String(64), nullable=True),
        sa.Column("receipt_digest", sa.String(64), nullable=True),
        sa.Column(
            "created_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "revision >= 0", name=op.f("ck_self_test_installations_self_test_installation_revision")
        ),
        sa.CheckConstraint(
            "status IN ('needs_input','queued','installing','ready','blocked','archived')",
            name=op.f("ck_self_test_installations_self_test_installation_status"),
        ),
        sa.UniqueConstraint(
            "project_id", "binding_id", "pack_digest", name="uq_self_test_installation_binding_pack"
        ),
        sa.UniqueConstraint(
            "project_id", "idempotency_key", name="uq_self_test_installation_idempotency"
        ),
    )
    op.create_index(
        op.f("ix_self_test_installations_binding_id"),
        "self_test_installations",
        ["binding_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_self_test_installations_project_id"),
        "self_test_installations",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_self_test_installations_status"),
        "self_test_installations",
        ["status"],
        unique=False,
    )
    op.create_table(
        "self_test_batches",
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "installation_id",
            sa.Uuid(),
            sa.ForeignKey("self_test_installations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("batch_key", sa.String(200), nullable=False),
        sa.Column("batch_kind", sa.String(24), nullable=False),
        sa.Column("generation_mode", sa.String(24), nullable=True),
        sa.Column("generation_stage", sa.String(32), nullable=False),
        sa.Column("readiness", sa.String(24), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("phase", sa.String(24), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("verification_scope", sa.String(24), nullable=False),
        sa.Column("provenance", sa.String(24), nullable=False, server_default="local_untrusted"),
        sa.Column("evidence_integrity", sa.String(16), nullable=False, server_default="missing"),
        sa.Column("cleanup_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("expected_count", sa.Integer(), nullable=False),
        sa.Column("frozen_manifest", sa.JSON(), nullable=False),
        sa.Column("manifest_digest", sa.String(64), nullable=False),
        sa.Column("resource_digest", sa.String(64), nullable=True),
        sa.Column("expected_set_digest", sa.String(64), nullable=False),
        sa.Column("required_set_digest", sa.String(64), nullable=False),
        sa.Column("policy_digest", sa.String(64), nullable=False),
        sa.Column("binding_fingerprint", sa.String(64), nullable=False),
        sa.Column("environment_fingerprint", sa.String(64), nullable=False),
        sa.Column("builds", sa.JSON(), nullable=False),
        sa.Column("generation_summary", sa.JSON(), nullable=True),
        sa.Column("artifact_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("plan_run_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "execution_plan_id",
            sa.Uuid(),
            sa.ForeignKey("test_plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("suite_ref", sa.JSON(), nullable=True),
        sa.Column("resource_snapshot", sa.JSON(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("host_id", sa.String(200), nullable=True),
        sa.Column("lease_owner", sa.String(200), nullable=True),
        sa.Column("lease_hash", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nonce_hash", sa.String(64), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ci_run_id", sa.String(200), nullable=True),
        sa.Column("ci_attempt", sa.Integer(), nullable=True),
        sa.Column("receipt_digest", sa.String(64), nullable=True),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "expected_count > 0 AND expected_count <= 100",
            name=op.f("ck_self_test_batches_self_test_batch_expected_count"),
        ),
        sa.CheckConstraint(
            "evidence_integrity IN ('complete','missing','expired')",
            name=op.f("ck_self_test_batches_self_test_batch_integrity"),
        ),
        sa.CheckConstraint(
            "batch_kind IN ('fixed_baseline','mcp_generated')",
            name=op.f("ck_self_test_batches_self_test_batch_kind"),
        ),
        sa.CheckConstraint(
            "phase IN ('pending','generating','awaiting_review','ready','running',"
            "'collecting','completed','cancelled','expired')",
            name=op.f("ck_self_test_batches_self_test_batch_phase"),
        ),
        sa.CheckConstraint(
            "provenance IN ('local_untrusted','trusted_ci')",
            name=op.f("ck_self_test_batches_self_test_batch_provenance"),
        ),
        sa.CheckConstraint(
            "revision >= 0", name=op.f("ck_self_test_batches_self_test_batch_revision")
        ),
        sa.CheckConstraint(
            "readiness IN ('ready','needs_input','needs_review','unsupported','blocked')",
            name=op.f("ck_self_test_batches_self_test_batch_readiness"),
        ),
        sa.CheckConstraint(
            "verification_scope IN ('full_pack','selected_suites','diagnostic_subset')",
            name=op.f("ck_self_test_batches_self_test_batch_scope"),
        ),
        sa.CheckConstraint(
            "cleanup_status IN ('pending','completed','failed','needs_review')",
            name=op.f("ck_self_test_batches_self_test_batch_cleanup"),
        ),
        sa.CheckConstraint(
            "generation_stage IN ('discovering','reading_contract','designing','compiling',"
            "'proposing','awaiting_review','publishing','ready','blocked','cancelled')",
            name=op.f("ck_self_test_batches_self_test_batch_generation_stage"),
        ),
        sa.CheckConstraint(
            "verdict IN ('pending','passed','failed','blocked')",
            name=op.f("ck_self_test_batches_self_test_batch_verdict"),
        ),
        sa.CheckConstraint(
            "generation_mode IS NULL OR generation_mode IN ('deterministic_mcp','host_llm_mcp')",
            name=op.f("ck_self_test_batches_self_test_generation_mode"),
        ),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_self_test_batch_idempotency"),
        sa.UniqueConstraint("batch_key", name="uq_self_test_batches_batch_key"),
    )
    op.create_index(
        op.f("ix_self_test_batches_binding_id"), "self_test_batches", ["binding_id"], unique=False
    )
    op.create_index(
        op.f("ix_self_test_batches_deadline"), "self_test_batches", ["deadline"], unique=False
    )
    op.create_index(
        op.f("ix_self_test_batches_installation_id"),
        "self_test_batches",
        ["installation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_self_test_batches_phase"), "self_test_batches", ["phase"], unique=False
    )
    op.create_index(
        op.f("ix_self_test_batches_project_id"), "self_test_batches", ["project_id"], unique=False
    )
    op.create_table(
        "self_test_scenario_results",
        sa.Column(
            "batch_id",
            sa.Uuid(),
            sa.ForeignKey("self_test_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scenario_id", sa.String(160), nullable=False),
        sa.Column("variant_key", sa.String(200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("frozen_scenario", sa.JSON(), nullable=False),
        sa.Column("generation_attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.JSON(), nullable=True),
        sa.Column("published_assets", sa.JSON(), nullable=True),
        sa.Column(
            "test_plan_run_id",
            sa.Uuid(),
            sa.ForeignKey("test_plan_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "run_item_id",
            sa.Uuid(),
            sa.ForeignKey("test_plan_run_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "execution_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_executions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("execution_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("observed_status", sa.String(24), nullable=True),
        sa.Column("verification_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("reason_codes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "generation_attempt >= 0 AND generation_attempt <= 10",
            name=op.f("ck_self_test_scenario_results_self_test_scenario_generation_attempt"),
        ),
        sa.CheckConstraint(
            "verification_status IN ('pending','matched','mismatched','incomplete',"
            "'error','unsupported')",
            name=op.f("ck_self_test_scenario_results_self_test_scenario_verification"),
        ),
        sa.CheckConstraint(
            "observed_status IS NULL OR observed_status IN "
            "('queued','running','passed','failed','cancelled','quarantined')",
            name=op.f("ck_self_test_scenario_results_self_test_scenario_observed_status"),
        ),
        sa.UniqueConstraint(
            "batch_id", "scenario_id", "variant_key", name="uq_self_test_scenario_variant"
        ),
    )
    op.create_index(
        op.f("ix_self_test_scenario_results_batch_id"),
        "self_test_scenario_results",
        ["batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_self_test_scenario_results_execution_id"),
        "self_test_scenario_results",
        ["execution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_self_test_scenario_results_run_item_id"),
        "self_test_scenario_results",
        ["run_item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_self_test_scenario_results_test_plan_run_id"),
        "self_test_scenario_results",
        ["test_plan_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("self_test_scenario_results")
    op.drop_table("self_test_batches")
    op.drop_table("self_test_installations")
