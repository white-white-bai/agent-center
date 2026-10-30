from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AC_", env_file=".env", extra="ignore")

    app_name: str = "agent-center"
    database_url: str = "sqlite+aiosqlite:///./agent_center.db"
    db_echo: bool = False
    auto_create_tables: bool = True
    model_provider: str = "stub"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "deepseek/deepseek-v4.1-flash"
    llm_fallback_model: str = "deepseek/deepseek-v4-flash"
    llm_timeout_ms: int = 30000
    embedding_model: str = ""
    embedding_dim: int = 1024
    redis_url: str = ""
    milvus_uri: str = ""
    milvus_collection: str = "agent_center_knowledge"
    vector_top_k: int = 20
    memory_extraction_enabled: bool = False
    sse_heartbeat_seconds: float = 15.0
    trace_retention_days: int = 90
    otel_enabled: bool = False
    otel_endpoint: str = ""
    otel_service_name: str = "agent-center"
    otel_sample_ratio: float = 1.0
    otel_timeout_ms: int = 5000
    alert_webhook_url: str = ""
    alert_tool_success_rate_min: float = 0.9
    alert_run_failure_rate_max: float = 0.2
    alert_badcase_open_max: int = 50
    alert_model_success_rate_min: float = 0.9
    publish_require_eval: bool = False
    publish_eval_min_accuracy: float = 0.8
    credential_key: str = ""
    sensitive_words: str = ""
    moderation_url: str | None = None
    moderation_timeout_ms: int = 2000
    stub_reply: str = '{"type":"final","answer":"这是桩模型的回复"}'


@lru_cache
def get_settings() -> Settings:
    return Settings()
