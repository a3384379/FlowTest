"""Stable response alias for the S42 controlled-write gateway."""

from app.schemas.test_design import MCPControlledWriteEnvelope


class MCPControlledWriteResponse(MCPControlledWriteEnvelope):
    pass
