from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.governance import QuotaDimension, QuotaMode

type RunnerType = Literal["general", "data", "protocol", "performance", "environment", "plugin"]
type RunnerRuntime = Literal["docker", "kubernetes"]
_DEFAULT_RUNNER_TYPES: tuple[RunnerType, ...] = (
    "general",
    "data",
    "protocol",
    "performance",
    "environment",
)
_DEFAULT_RUNTIMES: tuple[RunnerRuntime, ...] = ("docker", "kubernetes")


class QuotaRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: QuotaMode = QuotaMode.OBSERVE
    limit: int | None = Field(default=None, ge=1)
    warn_at: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_threshold(self) -> "QuotaRule":
        if self.limit is not None and self.warn_at is not None and self.warn_at > self.limit:
            raise ValueError("预警阈值不能超过配额上限")
        if self.mode is not QuotaMode.OBSERVE and self.limit is None:
            raise ValueError("启用配额限制时必须设置上限")
        return self


class RunnerGovernancePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_runner_types: list[RunnerType] = Field(
        default_factory=lambda: list(_DEFAULT_RUNNER_TYPES)
    )
    allowed_runtimes: list[RunnerRuntime] = Field(default_factory=lambda: list(_DEFAULT_RUNTIMES))
    max_pools: int = Field(default=20, ge=1, le=500)
    registration_requires_approval: bool = False

    @model_validator(mode="after")
    def validate_unique_lists(self) -> "RunnerGovernancePolicy":
        if len(self.allowed_runner_types) != len(set(self.allowed_runner_types)):
            raise ValueError("Runner 类型不能重复")
        if len(self.allowed_runtimes) != len(set(self.allowed_runtimes)):
            raise ValueError("Runner Runtime 不能重复")
        return self


class OrganizationGovernanceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_retention_days: int | None = Field(default=None, ge=1, le=3650)
    quota_policies: dict[QuotaDimension, QuotaRule] | None = None
    runner_policy: RunnerGovernancePolicy | None = None


class OrganizationGovernanceResponse(BaseModel):
    organization_id: UUID
    audit_retention_days: int
    quota_policies: dict[str, QuotaRule]
    runner_policy: RunnerGovernancePolicy
    active_key_version: int
    updated_at: datetime


class OrganizationAuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_user_id: UUID | None
    organization_id: UUID | None
    project_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    details: dict[str, object]
    created_at: datetime


class OrganizationKeyRotationPrepare(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_reference: str = Field(default="external:data-encryption-key", min_length=1, max_length=200)
    key_fingerprint: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class OrganizationKeyVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    version: int
    key_reference: str
    key_fingerprint: str
    status: Literal["pending", "active", "retiring", "retired", "rolled_back"]
    migration_status: Literal["planned", "migrating", "migrated", "rolled_back"]
    previous_version: int | None
    created_by_id: UUID
    activated_at: datetime | None
    migrated_at: datetime | None
    rolled_back_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OrganizationSecurityResponse(BaseModel):
    organization_id: UUID
    active_key_version: int
    key_versions: list[OrganizationKeyVersionResponse]
    capability_name: Literal["Organization Data Encryption Key Rotation"] = (
        "Organization Data Encryption Key Rotation"
    )
    capability_mode: Literal["reencrypt_verify_activate_rollback"] = (
        "reencrypt_verify_activate_rollback"
    )
    ciphertext_reencryption_available: Literal[True] = True
    ga_blocker: None = None


class RunnerGovernancePoolSummary(BaseModel):
    id: UUID
    name: str
    runner_type: str
    runtime: str
    enabled: bool
    max_concurrency: int
    current_load: int
    runner_count: int


class RunnerGovernanceSummary(BaseModel):
    organization_id: UUID
    pool_count: int
    runner_count: int
    current_load: int
    capacity: int
    pools: list[RunnerGovernancePoolSummary]


class SupportBundleRedactionResponse(BaseModel):
    organization_id: UUID
    schema_version: str
    data_classification: str
    included_sections: list[str]
    redacted_fields: list[str]
    excluded_fields: list[str]
