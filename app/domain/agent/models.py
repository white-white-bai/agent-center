from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, TenantMixin, TimestampMixin


class AgentDefinition(Base, TenantMixin, TimestampMixin):
    __tablename__ = "agent_definition"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    lifecycle: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", index=True)
    current_version_id: Mapped[int | None] = mapped_column(BigInteger)


class AgentVersion(Base, TenantMixin, TimestampMixin):
    __tablename__ = "agent_version"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(nullable=False)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    prompt_version_id: Mapped[int | None] = mapped_column(BigInteger)
    model_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    tool_bindings_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    knowledge_scopes_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(3))
