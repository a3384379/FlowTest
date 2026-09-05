"""Origin is determined by server-written provenance, never a caller supplied URI."""

from collections.abc import Mapping
from typing import Final, Literal

FlowSpecProposalOrigin = Literal["mcp", "repair", "maintenance", "import"]
MCP_PROPOSAL_SCHEMA: Final = "v6-flow-proposal-source-v1"
REPAIR_PROPOSAL_SCHEMA: Final = "v6-repair-proposal-source-v1"
MAINTENANCE_PROPOSAL_SCHEMA: Final = "v6-maintenance-proposal-source-v1"


def proposal_origin(snapshot: Mapping[str, object]) -> FlowSpecProposalOrigin:
    """Only application-generated source snapshots may be passed to this reader."""
    schema = snapshot.get("proposal_schema_version")
    if schema == MCP_PROPOSAL_SCHEMA:
        return "mcp"
    if schema == REPAIR_PROPOSAL_SCHEMA:
        return "repair"
    if schema == MAINTENANCE_PROPOSAL_SCHEMA:
        return "maintenance"
    return "import"
