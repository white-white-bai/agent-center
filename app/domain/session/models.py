from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, BigIntPK, TenantMixin, TimestampMixin


class Conversation(Base, TenantMixin, TimestampMixin):
    __tablename__ = "conversation"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    current_agent_code: Mapped[str | None] = mapped_column(String(100))
    agent_group_code: Mapped[str | None] = mapped_column(String(100))
    context_summary: Mapped[str | None] = mapped_column(Text)
    session_state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(3))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(3))


class ConversationTurn(Base, TenantMixin, TimestampMixin):
    __tablename__ = "conversation_turn"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    turn_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    user_message_id: Mapped[int | None] = mapped_column(BigInteger)
    assistant_message_id: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(3))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(3))


class Message(Base, TenantMixin, TimestampMixin):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    turn_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_json: Mapped[dict | None] = mapped_column(JSON)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safety_status: Mapped[str | None] = mapped_column(String(20))
    client_message_id: Mapped[str | None] = mapped_column(String(100), index=True)


class Run(Base, TenantMixin):
    __tablename__ = "run"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    turn_id: Mapped[int | None] = mapped_column(BigInteger)
    agent_version_id: Mapped[int | None] = mapped_column(BigInteger)
    agent_code: Mapped[str | None] = mapped_column(String(100))
    parent_run_id: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="QUEUED")
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=32000)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_input: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    token_output: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(3))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(3))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)


class RunStep(Base, TenantMixin):
    __tablename__ = "run_step"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SUCCESS")
    input_summary: Mapped[str | None] = mapped_column(Text)
    output_summary: Mapped[str | None] = mapped_column(Text)
    tool_code: Mapped[str | None] = mapped_column(String(100))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_input: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    token_output: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(3), default=datetime.utcnow)


class RunCheckpoint(Base, TenantMixin):
    __tablename__ = "run_checkpoint"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    checkpoint_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    step_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(3), default=datetime.utcnow)


class Citation(Base, TenantMixin):
    __tablename__ = "citation"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    section: Mapped[str | None] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text)
    effective_status: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(3), default=datetime.utcnow)
