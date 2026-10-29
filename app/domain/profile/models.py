from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, TenantMixin, TimestampMixin


class UserProfile(Base, TenantMixin, TimestampMixin):
    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    identity_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    style_preferences_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class UserProfileTag(Base, TenantMixin, TimestampMixin):
    __tablename__ = "user_profile_tag"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tag_key: Mapped[str] = mapped_column(String(100), nullable=False)
    tag_value: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)


class UserEvent(Base, TenantMixin):
    __tablename__ = "user_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(3), default=datetime.utcnow)
