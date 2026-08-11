from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.access import ProjectRole, TeamGrantRole
from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


def _project_role_values(role_type: type[ProjectRole] | type[TeamGrantRole]) -> list[str]:
    return [role.value for role in role_type]


class User(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("oidc_provider", "oidc_subject", name="uq_users_oidc_identity"),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_system_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    requires_password_change: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    oidc_provider: Mapped[str | None] = mapped_column(String(120), index=True)
    oidc_subject: Mapped[str | None] = mapped_column(String(255))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OIDCLoginTransaction(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "oidc_login_transactions"

    provider: Mapped[str] = mapped_column(String(120), index=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nonce_hash: Mapped[str] = mapped_column(String(64))
    verifier_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    verifier_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshSession(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refresh_sessions"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("refresh_sessions.id", ondelete="SET NULL")
    )
    user: Mapped[User] = relationship()


class Project(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("retention_days BETWEEN 1 AND 3650", name="retention_days"),
        CheckConstraint(
            "execution_concurrency_limit BETWEEN 1 AND 100",
            name="project_execution_concurrency_limit",
        ),
        CheckConstraint(
            "queued_run_limit BETWEEN 1 AND 5000",
            name="project_queued_run_limit",
        ),
    )

    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    variables: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, server_default="{}")
    headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, server_default="{}")
    outbound_allowed_hosts: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    outbound_allowed_private_cidrs: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    retention_days: Mapped[int] = mapped_column(Integer, default=90, server_default="90")
    execution_concurrency_limit: Mapped[int] = mapped_column(
        Integer, default=20, server_default="20"
    )
    queued_run_limit: Mapped[int] = mapped_column(Integer, default=1000, server_default="1000")
    ai_sample_sharing_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class ProjectMember(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
        CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="project_role"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[ProjectRole] = mapped_column(
        Enum(
            ProjectRole,
            native_enum=False,
            length=16,
            values_callable=_project_role_values,
        ),
        index=True,
    )


class Team(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class TeamMember(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),)

    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class ProjectTeamGrant(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_team_grants"
    __table_args__ = (
        UniqueConstraint("project_id", "team_id", name="uq_project_team_grants_project_team"),
        CheckConstraint("role IN ('editor', 'viewer')", name="team_grant_role"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    role: Mapped[TeamGrantRole] = mapped_column(
        Enum(
            TeamGrantRole,
            native_enum=False,
            length=16,
            values_callable=_project_role_values,
        ),
        index=True,
    )
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class Folder(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "folders"
    __table_args__ = (
        Index("ix_folders_project_parent", "project_id", "parent_id"),
        UniqueConstraint(
            "project_id",
            "parent_id",
            "name",
            name="uq_folders_project_parent_name",
            postgresql_nulls_not_distinct=True,
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("folders.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class AuditLog(UuidPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"

    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(100), index=True)
    resource_id: Mapped[UUID | None] = mapped_column(nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
