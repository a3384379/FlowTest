"""Independent negative-purpose metadata DTOs; no candidate product imports."""

from typing import Literal, get_args
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator
from scripts.selftest.contracts import Builds, Contract, Identity, Sha256, canonical_digest

ProbeKind = Literal[
    "workflow",
    "workflow_version",
    "test_case",
    "test_case_version",
    "test_plan",
    "test_plan_run",
    "workflow_execution",
    "ai_change_set",
    "test_design",
    "change_set_approval",
]


class ProbeFixture(Contract):
    project_id: UUID
    organization_id: UUID


class ProbeOracle(Contract):
    id: Identity
    kind: Identity
    expression_digest: Sha256
    operator: Identity
    expected_digest: Sha256


class ProbeDesign(Contract):
    document_digest: Sha256
    intent_key_digest: Sha256
    objective_digest: Sha256
    oracles: tuple[ProbeOracle, ...] = Field(max_length=200)


class ProbeItem(Contract):
    id: UUID
    item_type: Identity
    action: Identity
    review_status: Identity
    reviewed_by_id: UUID | None
    materialized_resource_type: Identity | None
    materialized_resource_id: UUID | None
    proposed_document_digest: Sha256 | None = None
    design: ProbeDesign | None = None


class ProbeResource(Contract):
    kind: ProbeKind
    id: UUID
    project_id: UUID
    parent_id: UUID | None = None
    source_change_set_id: UUID | None = None
    version: StrictInt | None = Field(default=None, ge=1)
    status: Identity
    fingerprint: Sha256 | None = None
    created_by_id: UUID | None = None
    reviewed_by_id: UUID | None = None
    actor_type: Identity | None = None
    items: tuple[ProbeItem, ...] = Field(default=(), max_length=500)
    design: ProbeDesign | None = None


class ProbeAuthority(Contract):
    probe_id: UUID
    binding_id: UUID
    binding_fingerprint: Sha256
    manifest_digest: Sha256
    source_digest: Sha256
    runtime_profile: Literal["full", "compact", "compose", "standalone"]
    builds: Builds
    fixtures: tuple[ProbeFixture, ...] = Field(min_length=2, max_length=2)
    owner_user_id: UUID
    reviewer_user_id: UUID
    machine_account_ids: tuple[UUID, ...] = Field(min_length=1, max_length=20)
    issued_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def fixed_scope(self) -> "ProbeAuthority":
        if len({item.project_id for item in self.fixtures}) != 2:
            raise ValueError("探针必须冻结两个项目")
        if len({item.organization_id for item in self.fixtures}) != 2:
            raise ValueError("探针必须冻结两个组织")
        if self.owner_user_id == self.reviewer_user_id:
            raise ValueError("探针独立评审者必须与机器所属用户分离")
        if len(set(self.machine_account_ids)) != len(self.machine_account_ids):
            raise ValueError("机器集合不能重复")
        if not 0 < (self.expires_at - self.issued_at).total_seconds() <= 600:
            raise ValueError("探针冻结期限必须小于等于600秒")
        return self


class ProbePage(Contract):
    probe_id: UUID
    purpose: Literal["mcp_governance_negative"]
    execution_scope: Literal["governance_negative_only"]
    provenance: Literal["local_untrusted"]
    binding_id: UUID
    binding_fingerprint: Sha256
    manifest_digest: Sha256
    source_digest: Sha256
    runtime_profile: Literal["full", "compact", "compose", "standalone"]
    builds: Builds
    covered_projects: tuple[ProbeFixture, ...] = Field(min_length=2, max_length=2)
    covered_kinds: tuple[ProbeKind, ...] = Field(min_length=10, max_length=10)
    items: tuple[ProbeResource, ...] = Field(max_length=100)
    total: StrictInt = Field(ge=0)
    next_cursor: str | None = Field(pattern=r"^[0-9a-f]{64}\.[0-9]{1,3}$")
    has_more: StrictBool
    complete: StrictBool
    reason_codes: tuple[Identity, ...] = Field(max_length=10)
    snapshot_digest: Sha256
    observed_at: AwareDatetime
    expires_at: AwareDatetime


class ProbeSnapshot(Contract):
    """All raw pages retained, so O can repeat every completeness and digest check."""

    pages: tuple[ProbePage, ...] = Field(min_length=1, max_length=5)

    @property
    def resources(self) -> tuple[ProbeResource, ...]:
        return tuple(item for page in self.pages for item in page.items)


class SnapshotIdentity(Contract):
    probe_id: UUID
    binding_id: UUID
    binding_fingerprint: Sha256
    manifest_digest: Sha256
    source_digest: Sha256
    runtime_profile: str
    builds: Builds
    covered_projects: tuple[ProbeFixture, ...]
    total: StrictInt
    rows: tuple[ProbeResource, ...]
    reasons: tuple[Identity, ...]


def snapshot_digest(authority: ProbeAuthority, rows: tuple[ProbeResource, ...]) -> str:
    value = SnapshotIdentity(
        probe_id=authority.probe_id,
        binding_id=authority.binding_id,
        binding_fingerprint=authority.binding_fingerprint,
        manifest_digest=authority.manifest_digest,
        source_digest=authority.source_digest,
        runtime_profile=authority.runtime_profile,
        builds=authority.builds,
        covered_projects=authority.fixtures,
        total=len(rows),
        rows=rows,
        reasons=(),
    )
    return canonical_digest(value.model_dump(mode="json"))


def probe_kinds() -> frozenset[str]:
    return frozenset(get_args(ProbeKind))
