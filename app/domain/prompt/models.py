from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, BigIntPK, TenantMixin, TimestampMixin


class PromptTemplate(Base, TenantMixin, TimestampMixin):
    __tablename__ = "prompt_template"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    layer: Mapped[str] = mapped_column(String(20), nullable=False, default="AGENT")
    current_version_id: Mapped[int | None] = mapped_column(BigInteger)


class PromptVersion(Base, TenantMixin, TimestampMixin):
    __tablename__ = "prompt_version"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    template_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    variables_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    output_schema_json: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="dev")
    eval_result_json: Mapped[dict | None] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(3))


class PromptBinding(Base, TenantMixin, TimestampMixin):
    __tablename__ = "prompt_binding"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    agent_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    prompt_template_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    prompt_version_id: Mapped[int | None] = mapped_column(BigInteger)
