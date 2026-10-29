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
    llm_fallback_model: str = "deepseek/deepseek-v4.1"
    llm_timeout_ms: int = 30000
    embedding_model: str = ""
    embedding_dim: int = 1024
    redis_url: str = ""
    memory_extraction_enabled: bool = False
    sensitive_words: str = ""
    moderation_url: str | None = None
    moderation_timeout_ms: int = 2000
    stub_reply: str = '{"type":"final","answer":"这是桩模型的回复"}'


@lru_cache
def get_settings() -> Settings:
    return Settings()
