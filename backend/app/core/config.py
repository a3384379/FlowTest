from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FLOWTEST_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "FlowTest API"
    app_version: str = "0.2.0"
    environment: str = "local"
    debug: bool = False
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://flowtest:flowtest@localhost:5432/flowtest"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "change-me-before-production-at-least-32-bytes"
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_days: int = Field(default=7, ge=1, le=30)
    bootstrap_admin_email: str = "admin@flowtest.dev"
    bootstrap_admin_password: str = "FlowTest-Change-Me-123!"
    secure_cookies: bool = False
    data_encryption_key: str = "Zmxvd3Rlc3QtbG9jYWwtZW5jcnlwdGlvbi1rZXktMzI="
    cors_origins: list[str] = ["http://localhost:5173"]
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "flowtest"
    s3_secret_key: str = "flowtest-local-secret"
    s3_bucket: str = "flowtest-artifacts"
    request_timeout_seconds: int = Field(default=30, ge=1, le=300)
    inline_body_limit_bytes: int = Field(default=2 * 1024 * 1024, ge=1024)
    artifact_limit_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
