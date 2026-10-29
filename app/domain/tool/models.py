from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, BigIntPK, TenantMixin, TimestampMixin


class ToolDefinition(Base, TenantMixin, TimestampMixin):
    __tablename__ = "tool_definition"
    __table_args__ = (
        UniqueConstraint("tenant_id", "tool_code", "version_no", name="uk_tool_tenant_code_version"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    tool_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="FUNCTION")
    endpoint: Mapped[str | None] = mapped_column(String(500))
    input_schema_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_schema_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    auth_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    retry_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    rate_limit_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    write_operation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    require_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    idempotent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    audit_level: Mapped[str] = mapped_column(String(20), nullable=False, default="BASIC")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ENABLED")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ToolBinding(Base, TenantMixin, TimestampMixin):
    __tablename__ = "tool_binding"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    agent_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    tool_code: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ToolInvokeLog(Base, TenantMixin):
    __tablename__ = "tool_invoke_log"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    tool_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    arguments_json: Mapped[dict | None] = mapped_column(JSON)
    result_summary: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(3), default=datetime.utcnow)


class ToolIdempotencyRecord(Base, TenantMixin, TimestampMixin):
    __tablename__ = "tool_idempotency_record"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    tool_code: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="EXECUTING")
    response_json: Mapped[dict | None] = mapped_column(JSON)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(3))


class ToolCredential(Base, TenantMixin, TimestampMixin):
    __tablename__ = "tool_credential"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    tool_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[str] = mapped_column(String(20), nullable=False, default="v1")


class ToolConfirmation(Base, TenantMixin, TimestampMixin):
    __tablename__ = "tool_confirmation"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    confirmation_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tool_code: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(3))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(3))
