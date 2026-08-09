from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class TestCase(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_cases"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_cases_project_name"),
        CheckConstraint(
            "current_version IS NULL OR current_version >= 1",
            name="test_case_current_version",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    folder_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    is_template: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True
    )
    draft_definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    current_version: Mapped[int | None] = mapped_column(Integer)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class TestCaseVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_case_versions"
    __table_args__ = (
        UniqueConstraint("test_case_id", "version", name="uq_test_case_versions_case_version"),
        CheckConstraint("version >= 1", name="test_case_version_number"),
    )

    test_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_cases.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    change_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class TestSuite(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_suites"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_suites_project_name"),
        CheckConstraint(
            "current_version IS NULL OR current_version >= 1",
            name="test_suite_current_version",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    folder_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    draft_definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    current_version: Mapped[int | None] = mapped_column(Integer)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class TestSuiteVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_suite_versions"
    __table_args__ = (
        UniqueConstraint("test_suite_id", "version", name="uq_test_suite_versions_suite_version"),
        CheckConstraint("version >= 1", name="test_suite_version_number"),
    )

    test_suite_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_suites.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    change_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class TestSuiteVersionItem(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_suite_version_items"
    __table_args__ = (
        UniqueConstraint(
            "test_suite_version_id",
            "position",
            name="uq_test_suite_version_items_version_position",
        ),
        CheckConstraint("position >= 0", name="test_suite_version_item_position"),
        CheckConstraint("test_case_version >= 1", name="test_suite_item_case_version"),
    )

    test_suite_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_suite_versions.id", ondelete="CASCADE"), index=True
    )
    test_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_cases.id", ondelete="RESTRICT"), index=True
    )
    test_case_version: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
