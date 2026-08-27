"""API response schemas for the read-only MCP gateway."""

from app.domain.mcp_read import MCPReadEnvelope


class MCPReadResponse(MCPReadEnvelope):
    """Stable response envelope shared with MCP clients."""
