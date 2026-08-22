"""Pure contracts for the read-only FlowTest MCP surface."""

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, JsonValue

MCP_SERVER_NAME = "flowtest"
MCP_SERVER_VERSION = "s41-read-v1"
MCP_READ_SCOPE = "mcp:read"
MCP_READ_SCHEMA_VERSION = "flowtest-mcp-read-schema-v1"


class MCPCallType(StrEnum):
    TOOL = "tool"
    RESOURCE = "resource"
    PROMPT = "prompt"


@dataclass(frozen=True, slots=True)
class MCPReadCall:
    operation: str
    call_type: MCPCallType
    input_schema_hash: str
    client_version: str
    resource_uri: str | None = None


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uri: str = Field(min_length=1, max_length=2048)
    kind: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=160)


class MCPReadEnvelope(BaseModel):
    """A safe, traceable result shared by REST and MCP transports."""

    model_config = ConfigDict(extra="forbid")

    data: JsonValue
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=200)
    confidence: float = Field(ge=0, le=1)
    redactions: list[str] = Field(default_factory=list, max_length=100)
    trace_id: str = Field(min_length=1, max_length=128)
    warnings: list[str] = Field(default_factory=list, max_length=100)


def input_schema_hash(operation: str) -> str:
    """Return a stable hash without including request values."""

    payload = f"{MCP_READ_SCHEMA_VERSION}:{operation}"
    return sha256(payload.encode("utf-8")).hexdigest()
