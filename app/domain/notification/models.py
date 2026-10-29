from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, BigIntPK, TenantMixin, TimestampMixin


class Notification(Base, TenantMixin, TimestampMixin):
    __tablename__ = "notification"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(3), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(3))
