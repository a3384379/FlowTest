"""Bounded SDK/metadata evidence with an explicit owned-asset disposal requirement."""

from typing import Literal

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator
from scripts.selftest.contracts import Contract, Identity, Sha256
from scripts.selftest.mcp_governance_contracts import Evidence as GovernanceEvidence
from scripts.selftest.mcp_negative_contracts import ProtocolEvidence
from scripts.selftest.mcp_probe_contracts import ProbeSnapshot


class StackSnapshot(Contract):
    schema_version: Literal["flowtest-selftest-binding-v1"]
    project_name: str = Field(pattern=r"^flowtest-selftest-[0-9a-f]{12}$")
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    runtime_profile: Literal["full", "compact", "standalone"]
    runner_url: Identity
    target_url: Identity
    observer_url: Identity
    target_internal_url: Literal["http://target:8000"]
    fixture_internal_url: Literal["http://mock-target:8080"]
    private_subnet: Identity
    candidate_image: Identity
    candidate_image_digest: Identity
    fixture_image: Identity
    fixture_image_digest: Identity
    source_digest: Sha256
    candidate_source: str | None
    dependency_digest: Sha256
    runner_container_id: Identity
    target_container_id: Identity
    observer_container_id: Identity
    runner_volume: Identity
    target_volume: Identity


class DisposalReceipt(Contract):
    project_name: str = Field(pattern=r"^flowtest-selftest-[0-9a-f]{12}$")
    binding_nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    runner_volume: Identity
    target_volume: Identity
    candidate_image_digest: Identity
    removed_at: AwareDatetime
    containers_absent: Literal[True]
    volumes_absent: Literal[True]
    networks_absent: Literal[True]


class ScenarioSnapshots(Contract):
    scenario_id: Identity
    before: ProbeSnapshot
    after: ProbeSnapshot


class DeployedEvidence(Contract):
    schema_version: Literal["flowtest-mcp-negative-deployed-v1"] = (
        "flowtest-mcp-negative-deployed-v1"
    )
    pack_kind: Literal["protocol34", "governance42"]
    manifest_digest: Sha256
    authority_digest: Sha256
    stack: StackSnapshot
    protocol: ProtocolEvidence | None
    governance: GovernanceEvidence | None
    snapshots: tuple[ScenarioSnapshots, ...] = Field(max_length=50)
    gateway_cleanup_complete: StrictBool
    disposal_receipt: DisposalReceipt | None
    collected_at: AwareDatetime
    request_budget_mode: Literal["conservative_outbound_plus_candidate_rpc"]
    http_outbound_admitted: StrictInt = Field(ge=0, le=500)
    candidate_rpc_admitted: StrictInt = Field(ge=0, le=500)
    candidate_rpc_rejected: StrictInt = Field(ge=0)
    claim: Literal["governance_negative_only"] = "governance_negative_only"
    trust: Literal["local_untrusted"] = "local_untrusted"

    @model_validator(mode="after")
    def one_raw_contract(self) -> "DeployedEvidence":
        if self.pack_kind == "protocol34":
            valid = self.protocol is not None and self.governance is None
        else:
            valid = self.governance is not None and self.protocol is None
        if not valid:
            raise ValueError("部署证据必须匹配精确的协议或治理pack")
        return self
