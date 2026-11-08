"""Quick/FlowSpec review stops at an unpublished native draft, with no execution."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from scripts.selftest.contracts import Contract, McpCallReceipt, Sha256
from scripts.selftest.initialization_contracts import InstallationInventory


class DraftBoundaryObservation(Contract):
    transport: Literal["stdio", "streamable-http"]
    route: Literal["quick", "flow_spec"]
    project_id: UUID
    api_id: UUID
    api_version: Literal[1]
    proposal_id: UUID
    proposal_status_before: str
    proposal_review_before: str
    proposal_applied_before: datetime | None
    proposal_status_after: str
    proposal_review_after: str
    applied_at: datetime | None
    reviewer_id: UUID
    expected_reviewer_id: UUID
    reviewer_is_admin: Literal[False]
    workflow_id: UUID
    workflow_project_id: UUID
    current_version: int | None
    published_version_count: int
    proposed_digest: Sha256
    draft_digest: Sha256
    api_references: tuple[UUID, ...]
    api_versions: tuple[int, ...]
    before: InstallationInventory
    proposed: InstallationInventory
    after: InstallationInventory
    proposal_ids_before: tuple[UUID, ...]
    proposal_ids_after: tuple[UUID, ...]
    call: McpCallReceipt
    completed_at: datetime
    review_mode: Literal["ci_fixture"] = "ci_fixture"


def draft_keys() -> tuple[str, ...]:
    return tuple(
        transport + "/" + route + "_draft"
        for transport in ("stdio", "streamable-http")
        for route in ("quick", "flow_spec")
    )
