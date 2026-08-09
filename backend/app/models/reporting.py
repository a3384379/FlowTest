from datetime import datetime
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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class NotificationWebhook(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_webhooks"

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    url: Mapped[str] = mapped_column(String(2048))
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    secret_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    events: Mapped[list[str]] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class NotificationDelivery(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'delivered', 'failed')",
            name="notification_delivery_status",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    webhook_id: Mapped[UUID] = mapped_column(
        ForeignKey("notification_webhooks.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[UUID] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    response_status: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
