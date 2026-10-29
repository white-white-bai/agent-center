from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AC_", env_file=".env", extra="ignore")

    app_name: str = "agent-center"
    database_url: str = "sqlite+aiosqlite:///./agent_center.db"
    db_echo: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
