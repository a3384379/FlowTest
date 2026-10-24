"""Deployment-owned self-test targets and external principal allowlists."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.self_test_probes import NegativeProbeGrant
from app.schemas.self_tests import (
    AgentCapability,
    BuildIdentity,
    Digest,
    Identity,
    SelfTestDTO,
    TemplateResponse,
)


class SelfTestPrincipal(SelfTestDTO):
    id: Identity
    issuer: Identity
    subject: Identity
    audience: Identity
    public_key: str = Field(min_length=100, max_length=16384)
    algorithm: Literal["RS256", "ES256", "EdDSA"] = "RS256"
    allowed_project_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    allowed_binding_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    capabilities: tuple[AgentCapability, ...] = Field(min_length=1, max_length=5)
    trusted_verifier: bool = False
    authorized_host_budget_digests: tuple[Digest, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def verifier_is_separate(self) -> "SelfTestPrincipal":
        if "verify" in self.capabilities and set(self.capabilities) != {"verify"}:
            raise ValueError("独立核验身份只能具有 verify 权限")
        return self


class SelfTestBinding(SelfTestDTO):
    id: UUID
    name: Identity
    allowed_project_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    runner_instance_id: Identity
    target_instance_id: Identity
    target_display: Identity
    fixture_display: Identity
    target_base_url: str = Field(min_length=1, max_length=2048)
    fixture_base_url: str = Field(min_length=1, max_length=2048)
    target_project_id: UUID
    target_organization_id: UUID
    target_user_id: UUID
    builds: BuildIdentity
    environment_fingerprint: Digest
    isolation_fingerprint: Digest
    non_production: bool
    isolated: bool
    outbound_authorized: bool
    runtime_profile: Literal["full", "compact", "compose", "standalone"] = "standalone"
    agent_id: Identity | None = None
    observer_id: Identity | None = None
    ci_run_id: Identity | None = None
    ci_attempt: int | None = Field(default=None, ge=1, strict=True)
    enabled: bool = True

    @model_validator(mode="after")
    def complete_ci_identity(self) -> "SelfTestBinding":
        if (self.ci_run_id is None) != (self.ci_attempt is None):
            raise ValueError("部署 CI run 与 attempt 必须同时提供")
        return self


class SelfTestSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FLOWTEST_SELFTEST_", case_sensitive=False, extra="ignore"
    )

    bindings: tuple[SelfTestBinding, ...] = Field(default=(), max_length=100)
    principals: tuple[SelfTestPrincipal, ...] = Field(default=(), max_length=100)
    extra_templates: tuple[TemplateResponse, ...] = Field(default=(), max_length=20)
    probe_grants: tuple[NegativeProbeGrant, ...] = Field(default=(), max_length=20)
    lease_seconds: int = Field(default=120, ge=30, le=600)
    registration_seconds: int = Field(default=300, ge=30, le=1800)
    preview_seconds: int = Field(default=300, ge=30, le=600)
    artifact_limit_bytes: int = Field(default=1048576, ge=1024, le=2097152)
    fixture_run_depth: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def unique_configuration(self) -> "SelfTestSettings":
        if len({item.id for item in self.probe_grants}) != len(self.probe_grants):
            raise ValueError("探针授权 ID 不能重复")
        if len({item.id for item in self.bindings}) != len(self.bindings):
            raise ValueError("自测 binding ID 不能重复")
        identities = [(item.issuer, item.subject, item.audience) for item in self.principals]
        if len({item.id for item in self.principals}) != len(self.principals) or len(
            set(identities)
        ) != len(identities):
            raise ValueError("自测 principal 身份不能重复")
        return self


def get_self_test_settings() -> SelfTestSettings:
    return SelfTestSettings()
