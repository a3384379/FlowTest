from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

SchemaName = Annotated[str, Field(min_length=1, max_length=160)]


class GraphQLSchemaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    name: SchemaName
    description: str = Field(default="", max_length=4000)
    source_format: Literal["graphql_sdl", "graphql_introspection"]
    sdl: str | None = None
    introspection: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "GraphQLSchemaCreate":
        if self.source_format == "graphql_sdl" and (not self.sdl or self.introspection is not None):
            raise ValueError("SDL 导入必须且只能提供 sdl")
        if self.source_format == "graphql_introspection" and (
            self.introspection is None or self.sdl is not None
        ):
            raise ValueError("Introspection 导入必须且只能提供 introspection")
        return self


class ProtoFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1)


class GrpcDescriptorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    name: SchemaName
    description: str = Field(default="", max_length=4000)
    source_format: Literal["proto_source", "proto_descriptor_set"]
    entrypoint: str | None = Field(default=None, max_length=240)
    files: list[ProtoFileInput] | None = Field(default=None, max_length=50)
    descriptor_set_base64: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "GrpcDescriptorCreate":
        if self.source_format == "proto_source":
            if not self.entrypoint or not self.files or self.descriptor_set_base64 is not None:
                raise ValueError("Proto 导入必须提供 entrypoint 和 files")
        elif self.descriptor_set_base64 is None or self.entrypoint is not None or self.files:
            raise ValueError("Descriptor Set 导入必须且只能提供 descriptor_set_base64")
        return self


class GrpcReflectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    name: SchemaName
    description: str = Field(default="", max_length=4000)
    endpoint: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$", min_length=3, max_length=512)
    tls_mode: Literal["plaintext", "tls", "mtls"] = "plaintext"
    credential_id: UUID | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=300)

    @model_validator(mode="after")
    def validate_tls(self) -> "GrpcReflectionCreate":
        if self.tls_mode == "mtls" and self.credential_id is None:
            raise ValueError("mTLS Reflection 必须提供 Credential")
        if self.tls_mode != "mtls" and self.credential_id is not None:
            raise ValueError("只有 mTLS Reflection 可以提供 Credential")
        return self


class SchemaArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    protocol: Literal["graphql", "grpc", "kafka"]
    name: str
    description: str
    version: int
    source_format: str
    content_sha256: str
    summary: dict[str, JsonValue]
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class GraphQLDebugRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    schema_id: UUID
    endpoint: str = Field(min_length=1, max_length=2048)
    operation: str = Field(min_length=1, max_length=2 * 1024 * 1024)
    operation_name: str | None = Field(default=None, min_length=1, max_length=160)
    variables: dict[str, JsonValue] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class GrpcDebugRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    descriptor_id: UUID
    endpoint: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$", min_length=3, max_length=512)
    service: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.]*$", max_length=512)
    method: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=160)
    request: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, str] = Field(default_factory=dict)
    call_type: Literal["unary", "server_streaming"]
    tls_mode: Literal["plaintext", "tls", "mtls"] = "plaintext"
    credential_id: UUID | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=300)

    @model_validator(mode="after")
    def validate_tls(self) -> "GrpcDebugRequest":
        if self.tls_mode == "mtls" and self.credential_id is None:
            raise ValueError("mTLS 调用必须提供 Credential")
        if self.tls_mode != "mtls" and self.credential_id is not None:
            raise ValueError("只有 mTLS 调用可以提供 Credential")
        return self


class ProtocolDebugResponse(BaseModel):
    output: JsonValue
    schema_id: UUID
    schema_version: int
    schema_hash: str
    duration_ms: int = Field(ge=0)
