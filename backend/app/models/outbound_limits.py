"""Standalone outbound admission state."""

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OutboundPermit(Base):
    __tablename__ = "outbound_permits"
    __table_args__ = (Index("ix_outbound_permits_project_expiry", "project_id", "expires_at_ms"),)

    permit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner: Mapped[str] = mapped_column(String(100), nullable=False)
    expires_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)


class OutboundRateWindow(Base):
    __tablename__ = "outbound_rate_windows"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    used: Mapped[int] = mapped_column(Integer, nullable=False)
