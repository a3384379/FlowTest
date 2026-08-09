from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FLOWTEST_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "FlowTest API"
    app_version: str = "0.1.0"
    environment: str = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://flowtest:flowtest@localhost:5432/flowtest"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "change-me-before-production"
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
