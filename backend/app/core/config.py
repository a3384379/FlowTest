import re
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENVIRONMENT_IMAGE_DIGEST = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?/"
    r"[a-z0-9]+(?:[._/-][a-z0-9]+)*"
    r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?@sha256:[0-9a-f]{64}$"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FLOWTEST_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "FlowTest API"
    app_version: str = "3.0.0-beta.2-dev.28"
    environment: str = "local"
    debug: bool = False
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://flowtest:flowtest@localhost:5432/flowtest"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    scheduler_poll_seconds: int = Field(default=15, ge=5, le=300)
    retention_cleanup_interval_seconds: int = Field(default=86_400, ge=300, le=604_800)
    retention_default_days: int = Field(default=90, ge=1, le=3650)
    retention_max_days: int = Field(default=3650, ge=30, le=3650)
    test_plan_concurrency: int = Field(default=5, ge=1, le=20)
    webhook_signature_tolerance_seconds: int = Field(default=300, ge=30, le=3600)
    rate_limit_enabled: bool = False
    auth_rate_limit_per_minute: int = Field(default=10, ge=1, le=1000)
    execution_rate_limit_per_minute: int = Field(default=30, ge=1, le=1000)
    write_rate_limit_per_minute: int = Field(default=120, ge=1, le=5000)
    workflow_event_retention_seconds: int = Field(default=86_400, ge=60, le=604_800)
    secret_key: str = "change-me-before-production-at-least-32-bytes"  # noqa: S105
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_days: int = Field(default=7, ge=1, le=30)
    bootstrap_admin_email: str = "admin@flowtest.dev"
    bootstrap_admin_password: str = "FlowTest-Change-Me-123!"  # noqa: S105
    secure_cookies: bool = False
    data_encryption_key: str = "Zmxvd3Rlc3QtbG9jYWwtZW5jcnlwdGlvbi1rZXktMzI="
    cors_origins: list[str] = ["http://localhost:5173"]
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "flowtest"
    s3_secret_key: str = "flowtest-local-secret"  # noqa: S105
    s3_bucket: str = "flowtest-artifacts"
    request_timeout_seconds: int = Field(default=30, ge=1, le=300)
    inline_body_limit_bytes: int = Field(default=2 * 1024 * 1024, ge=1024)
    artifact_limit_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)
    feature_teams_enabled: bool = False
    feature_test_assets_enabled: bool = False
    feature_advanced_workflows_enabled: bool = False
    feature_data_nodes_enabled: bool = False
    feature_contract_testing_enabled: bool = False
    feature_quality_center_enabled: bool = False
    feature_oidc_enabled: bool = False
    feature_ai_enabled: bool = False
    feature_capability_sdk_enabled: bool = False
    feature_plugin_registry_enabled: bool = False
    feature_runner_fabric_enabled: bool = False
    feature_multi_protocol_enabled: bool = False
    feature_event_protocols_enabled: bool = False
    feature_performance_lab_enabled: bool = False
    feature_environment_lab_enabled: bool = False
    feature_contract_hub_enabled: bool = False
    feature_impact_engine_enabled: bool = False
    performance_max_vus: int = Field(default=100, ge=1, le=1000)
    performance_max_duration_seconds: int = Field(default=1800, ge=1, le=3600)
    performance_runner_timeout_seconds: int = Field(default=2100, ge=60, le=3900)
    environment_image_allowlist: list[str] = Field(default_factory=list)
    environment_runtime_host: str = "environment-docker"
    environment_max_ttl_seconds: int = Field(default=86400, ge=60, le=86400)
    environment_provision_timeout_seconds: int = Field(default=300, ge=30, le=1800)
    environment_cleanup_timeout_seconds: int = Field(default=120, ge=10, le=600)
    environment_health_request_timeout_seconds: int = Field(default=5, ge=1, le=30)
    environment_reconcile_interval_seconds: int = Field(default=30, ge=10, le=300)
    pact_broker_base_url: str = ""
    pact_broker_token: str = ""
    pact_broker_request_timeout_seconds: int = Field(default=15, ge=1, le=60)
    pact_provider_request_timeout_seconds: int = Field(default=10, ge=1, le=60)
    ai_base_url: str = ""
    ai_model: str = ""
    ai_api_key: str = ""
    ai_request_timeout_seconds: int = Field(default=30, ge=1, le=300)
    ai_max_suggestions: int = Field(default=20, ge=1, le=50)
    oidc_provider_name: str = "default"
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = "http://localhost:8000/api/v1/auth/oidc/callback"
    oidc_frontend_success_url: str = "http://localhost:5173/dashboard"
    oidc_allowed_email_domains: list[str] = []
    oidc_scopes: list[str] = ["openid", "profile", "email"]
    oidc_allowed_algorithms: list[str] = ["RS256"]
    oidc_transaction_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    oidc_request_timeout_seconds: int = Field(default=10, ge=1, le=60)
    vault_kv2_enabled: bool = False
    vault_address: str = ""
    vault_token: str = ""
    vault_namespace: str = ""
    vault_kv2_mount: str = "secret"
    vault_kv2_prefix: str = "flowtest"
    vault_request_timeout_seconds: int = Field(default=10, ge=1, le=60)
    vault_tls_verify: bool = True
    otel_enabled: bool = False
    otel_service_name: str = "flowtest-api"
    otel_worker_service_name: str = "flowtest-worker"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    otel_exporter_headers: dict[str, str] = {}
    otel_trace_sample_ratio: float = Field(default=0.1, ge=0, le=1)
    otel_export_timeout_seconds: int = Field(default=10, ge=1, le=60)

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if self.retention_default_days > self.retention_max_days:
            raise ValueError("默认保留天数不能超过系统保留上限")
        self._validate_oidc()
        self._validate_vault()
        self._validate_ai()
        self._validate_environment_lab()
        self._validate_pact_broker()
        self._validate_production()
        return self

    def _validate_environment_lab(self) -> None:
        if not self.feature_environment_lab_enabled:
            return
        if not self.environment_image_allowlist:
            raise ValueError("启用环境实验室时必须配置镜像白名单")
        if any(
            _ENVIRONMENT_IMAGE_DIGEST.fullmatch(image) is None
            for image in self.environment_image_allowlist
        ):
            raise ValueError("环境实验室镜像白名单必须固定 OCI Digest")

    def _validate_ai(self) -> None:
        if not self.feature_ai_enabled:
            return
        if not self.ai_base_url.strip() or not self.ai_model.strip() or not self.ai_api_key.strip():
            raise ValueError("启用 AI 时必须配置 Base URL、Model 和 API Key")

    def _validate_pact_broker(self) -> None:
        if not self.pact_broker_base_url:
            return
        parsed = urlsplit(self.pact_broker_base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Pact Broker 必须是无凭据、Query 和路径的 HTTP/HTTPS Origin")
        if self.environment == "production" and parsed.scheme != "https":
            raise ValueError("生产环境 Pact Broker 必须使用 HTTPS")

    def _validate_oidc(self) -> None:
        if not self.feature_oidc_enabled:
            return
        required = (
            self.oidc_issuer_url,
            self.oidc_client_id,
            self.oidc_redirect_uri,
            self.oidc_frontend_success_url,
        )
        if any(not value.strip() for value in required):
            raise ValueError("启用 OIDC 时必须配置 Issuer、Client ID 和回调地址")
        if not self.oidc_allowed_email_domains:
            raise ValueError("启用 OIDC 时必须配置允许的邮箱域名")
        if "openid" not in self.oidc_scopes:
            raise ValueError("OIDC Scope 必须包含 openid")
        if not self.oidc_allowed_algorithms:
            raise ValueError("OIDC 必须配置至少一种允许的签名算法")

    def _validate_production(self) -> None:
        if self.environment.lower() not in {"production", "prod"}:
            return
        unsafe = (
            self.secret_key == "change-me-before-production-at-least-32-bytes"  # noqa: S105
            or self.bootstrap_admin_password == "FlowTest-Change-Me-123!"  # noqa: S105
            or self.data_encryption_key == "Zmxvd3Rlc3QtbG9jYWwtZW5jcnlwdGlvbi1rZXktMzI="
            or self.s3_secret_key == "flowtest-local-secret"  # noqa: S105
        )
        if unsafe or not self.secure_cookies:
            raise ValueError("生产环境必须替换默认密钥、管理员密码并启用安全 Cookie")
        if self.feature_oidc_enabled:
            oidc_urls = (
                self.oidc_issuer_url,
                self.oidc_redirect_uri,
                self.oidc_frontend_success_url,
            )
            if any(urlsplit(url).scheme != "https" for url in oidc_urls):
                raise ValueError("生产环境 OIDC 地址必须使用 HTTPS")
        if self.vault_kv2_enabled and urlsplit(self.vault_address).scheme != "https":
            raise ValueError("生产环境 Vault 地址必须使用 HTTPS")
        if self.feature_ai_enabled and urlsplit(self.ai_base_url).scheme != "https":
            raise ValueError("生产环境 AI 网关必须使用 HTTPS")

    def _validate_vault(self) -> None:
        if not self.vault_kv2_enabled:
            return
        if not self.vault_address.strip() or not self.vault_token.strip():
            raise ValueError("启用 Vault KV v2 时必须配置地址和 Token")
        if not self.vault_kv2_mount.strip() or not self.vault_kv2_prefix.strip():
            raise ValueError("Vault KV v2 的 Mount 和 Prefix 不能为空")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
