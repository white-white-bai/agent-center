from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, BigIntPK, TenantMixin, TimestampMixin


class EvalDataset(Base, TenantMixin, TimestampMixin):
    __tablename__ = "eval_dataset"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uk_eval_dataset_tenant_code"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain_code: Mapped[str | None] = mapped_column(String(100))


class EvalCase(Base, TenantMixin, TimestampMixin):
    __tablename__ = "eval_case"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text)
    expected_doc_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tags_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class EvalRun(Base, TenantMixin, TimestampMixin):
    __tablename__ = "eval_run"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    prompt_version_id: Mapped[int | None] = mapped_column(BigInteger)
    agent_version_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    metrics_json: Mapped[dict | None] = mapped_column(JSON)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(3))


class EvalResult(Base, TenantMixin, TimestampMixin):
    __tablename__ = "eval_result"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    eval_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    passed: Mapped[bool | None] = mapped_column()
    actual_answer: Mapped[str | None] = mapped_column(Text)
    detail_json: Mapped[dict | None] = mapped_column(JSON)


class Feedback(Base, TenantMixin, TimestampMixin):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(100))
    comment: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(String(64))


class Badcase(Base, TenantMixin, TimestampMixin):
    __tablename__ = "badcase"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    feedback_id: Mapped[int | None] = mapped_column(BigInteger)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    description: Mapped[str | None] = mapped_column(Text)
    eval_case_id: Mapped[int | None] = mapped_column(BigInteger)


class AuditLog(Base, TenantMixin):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(100))
    detail_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(3), default=datetime.utcnow)
