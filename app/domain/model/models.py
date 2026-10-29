from sqlalchemy import JSON, BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, TenantMixin, TimestampMixin


class ModelProvider(Base, TenantMixin, TimestampMixin):
    __tablename__ = "model_provider"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_code: Mapped[str] = mapped_column(String(50), nullable=False)
    model_alias: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    capabilities_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ModelRoutePolicy(Base, TenantMixin, TimestampMixin):
    __tablename__ = "model_route_policy"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    policy_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    primary_model: Mapped[str] = mapped_column(String(100), nullable=False)
    fallback_model: Mapped[str | None] = mapped_column(String(100))
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=30000)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    temperature: Mapped[float] = mapped_column(nullable=False, default=0.2)
    extra_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ModelUsageLog(Base, TenantMixin, TimestampMixin):
    __tablename__ = "model_usage_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    model_alias: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_code: Mapped[str | None] = mapped_column(String(50))
    prompt_version_id: Mapped[int | None] = mapped_column(BigInteger)
    token_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_cached: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_token_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[float] = mapped_column(nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SUCCESS")
    detail: Mapped[str | None] = mapped_column(Text)
