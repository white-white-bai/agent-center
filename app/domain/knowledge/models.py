from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, BigIntPK, TenantMixin, TimestampMixin


class KnowledgeSpace(Base, TenantMixin, TimestampMixin):
    __tablename__ = "knowledge_space"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    layer: Mapped[str] = mapped_column(String(20), nullable=False, default="DOMAIN")
    domain_code: Mapped[str | None] = mapped_column(String(100))
    agent_id: Mapped[int | None] = mapped_column(BigInteger)


class KnowledgeDocument(Base, TenantMixin, TimestampMixin):
    __tablename__ = "knowledge_document"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    document_code: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    region_code: Mapped[str | None] = mapped_column(String(20))
    authority_level: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime)
    source_url: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))


class KnowledgeChunk(Base, TenantMixin, TimestampMixin):
    __tablename__ = "knowledge_chunk"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    section: Mapped[str | None] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    domain_code: Mapped[str | None] = mapped_column(String(100), index=True)
    region_code: Mapped[str | None] = mapped_column(String(20), index=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime)
    authority_level: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    source_url: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    embedding_ref: Mapped[str | None] = mapped_column(String(64))


class KnowledgeRouteRule(Base, TenantMixin, TimestampMixin):
    __tablename__ = "knowledge_route_rule"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    domain_code: Mapped[str] = mapped_column(String(100), nullable=False)
    intent_keywords_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    space_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class KnowledgeSyncTask(Base, TenantMixin, TimestampMixin):
    __tablename__ = "knowledge_sync_task"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="UPLOAD")
    source_ref: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    checkpoint_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(3))
