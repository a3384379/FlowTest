"""Deployment-owned authority for bounded governance-negative observations."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.self_tests import BuildIdentity, Digest, Identity, SelfTestDTO


class ProbeFixture(SelfTestDTO):
    project_id: UUID
    organization_id: UUID


class NegativeProbeGrant(SelfTestDTO):
    id: UUID
    purpose: Literal["mcp_governance_negative"] = "mcp_governance_negative"
    principal_id: Identity
    binding_id: UUID
    binding_fingerprint: Digest
    fixtures: tuple[ProbeFixture, ...] = Field(min_length=2, max_length=2)
    owner_user_id: UUID
    reviewer_user_id: UUID
    machine_account_ids: tuple[UUID, ...] = Field(min_length=1, max_length=20)
    nonce_hash: Digest
    manifest_digest: Digest
    source_digest: Digest
    runtime_profile: Literal["full", "compact", "compose", "standalone"]
    builds: BuildIdentity
    issued_at: datetime
    expires_at: datetime
    enabled: bool = True

    @model_validator(mode="after")
    def bounded_authority(self) -> "NegativeProbeGrant":
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("探针授权时间必须包含时区")
        if not 0 < (self.expires_at - self.issued_at).total_seconds() <= 600:
            raise ValueError("探针授权期限必须为 1 至 600 秒")
        if len({item.project_id for item in self.fixtures}) != 2:
            raise ValueError("探针必须冻结两个不同项目")
        if len({item.organization_id for item in self.fixtures}) != 2:
            raise ValueError("跨组织探针必须冻结两个不同组织")
        if self.owner_user_id == self.reviewer_user_id:
            raise ValueError("探针所有者与审核者必须为不同身份")
        if len(set(self.machine_account_ids)) != len(self.machine_account_ids):
            raise ValueError("探针机器身份不能重复")
        return self
