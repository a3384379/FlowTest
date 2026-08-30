from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class Workflow(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflows"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_workflows_project_name"),)

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    folder_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    draft_definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    draft_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    current_version: Mapped[int | None] = mapped_column(Integer)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class WorkflowVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_version"),
    )

    workflow_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class WorkflowExecution(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'passed', 'failed', 'cancelled')",
            name="workflow_execution_status",
        ),
        CheckConstraint(
            "(run_purpose = 'standard' AND workflow_id IS NOT NULL "
            "AND workflow_version_id IS NOT NULL AND source_change_set_id IS NULL "
            "AND preview_approval_id IS NULL) OR "
            "(run_purpose = 'preview' AND source_change_set_id IS NOT NULL "
            "AND preview_approval_id IS NOT NULL)",
            name="workflow_execution_run_purpose",
        ),
        CheckConstraint(
            "main_status IS NULL OR main_status IN ('passed', 'failed', 'cancelled')",
            name="workflow_execution_main_status",
        ),
        CheckConstraint(
            "cleanup_status IS NULL OR cleanup_status IN ('passed', 'failed', 'cancelled')",
            name="workflow_execution_cleanup_status",
        ),
        CheckConstraint(
            "(parent_execution_id IS NULL AND dataset_row_index IS NULL) OR "
            "(parent_execution_id IS NOT NULL AND dataset_row_index IS NOT NULL "
            "AND dataset_row_index >= 0)",
            name="workflow_execution_dataset_child",
        ),
        UniqueConstraint(
            "parent_execution_id",
            "dataset_row_index",
            name="uq_workflow_executions_parent_dataset_row",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    workflow_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="RESTRICT"), index=True
    )
    workflow_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_versions.id", ondelete="RESTRICT"), index=True
    )
    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), index=True
    )
    triggered_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    parent_execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), index=True
    )
    dataset_row_index: Mapped[int | None] = mapped_column(Integer)
    run_purpose: Mapped[str] = mapped_column(
        String(16), default="standard", server_default="standard", index=True
    )
    source_change_set_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_change_sets.id", ondelete="RESTRICT"), index=True
    )
    preview_approval_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sandbox_preview_approvals.id", ondelete="RESTRICT"), index=True
    )
    preview_budget: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    preview_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    main_status: Mapped[str | None] = mapped_column(String(16))
    cleanup_status: Mapped[str | None] = mapped_column(String(16))
    cleanup_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    force_cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    force_cancel_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    run_payload_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    run_payload_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)


class WorkflowNodeExecution(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_node_executions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_execution_id",
            "node_id",
            name="uq_workflow_node_executions_execution_node",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'passed', 'failed', 'skipped', 'cancelled')",
            name="workflow_node_execution_status",
        ),
        CheckConstraint("phase IN ('main', 'cleanup')", name="workflow_node_execution_phase"),
    )

    workflow_execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), index=True
    )
    node_id: Mapped[str] = mapped_column(String(128))
    node_type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    phase: Mapped[str] = mapped_column(String(16), default="main", server_default="main")
    best_effort: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(16), index=True)
    attempts: Mapped[int] = mapped_column(Integer)
    output: Mapped[Any | None] = mapped_column(JSON)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
