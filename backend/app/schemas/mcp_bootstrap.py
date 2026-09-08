"""Strict, secret-free contracts for the S61B MCP bootstrap surface."""

import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

MCP_BOOTSTRAP_SCHEMA_VERSION: Literal["s61-mcp-bootstrap-v1"] = "s61-mcp-bootstrap-v1"
MCP_BOOTSTRAP_OPERATION = Literal["created", "reused", "dry_run"]
_EXTERNAL_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


class _BootstrapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dry_run: bool = False


class MCPEnsureProjectRequest(_BootstrapRequest):
    project_id: UUID | None = None
    external_key: str | None = Field(default=None, min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("项目名称不能为空")
        return normalized

    @field_validator("external_key")
    @classmethod
    def validate_external_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not _EXTERNAL_KEY_PATTERN.fullmatch(normalized):
            raise ValueError("external_key 格式无效")
        return normalized


class MCPEnsureEnvironmentRequest(_BootstrapRequest):
    project_id: UUID
    name: str = Field(min_length=1, max_length=160)
    base_url: HttpUrl
    classification: Literal["test", "sandbox"]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("环境名称不能为空")
        return normalized

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: HttpUrl) -> HttpUrl:
        parsed = urlsplit(str(value))
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("环境地址不能包含凭据")
        if parsed.query or parsed.fragment:
            raise ValueError("环境地址不能包含查询参数或片段")
        return value


class MCPEnsureServiceTargetRequest(_BootstrapRequest):
    project_id: UUID
    environment_id: UUID
    service_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    name: str = Field(min_length=1, max_length=200)
    service_type: Literal["http", "https", "grpc", "graphql", "other"] = "http"
    variant: str = Field(
        default="default",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$",
    )
    base_url: HttpUrl
    tls_verify: Literal[True] = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Service 名称不能为空")
        return normalized

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: HttpUrl) -> HttpUrl:
        parsed = urlsplit(str(value))
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Service Endpoint 地址不能包含凭据")
        if parsed.query or parsed.fragment:
            raise ValueError("Service Endpoint 地址不能包含查询参数或片段")
        return value


class _BootstrapResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["s61-mcp-bootstrap-v1"] = MCP_BOOTSTRAP_SCHEMA_VERSION
    operation: MCP_BOOTSTRAP_OPERATION
    organization_id: UUID
    idempotency_replayed: bool = False
    trace_id: str = Field(min_length=1, max_length=128)


class MCPEnsureProjectResponse(_BootstrapResponse):
    project_id: UUID | None = None
    project_name: str | None = None
    external_key: str | None = None


class MCPEnsureEnvironmentResponse(_BootstrapResponse):
    project_id: UUID
    environment_id: UUID | None = None
    environment_name: str | None = None
    classification: Literal["test", "sandbox"]
    base_url: str | None = None


class MCPEnsureServiceTargetResponse(_BootstrapResponse):
    project_id: UUID
    environment_id: UUID
    service_id: UUID | None = None
    endpoint_id: UUID | None = None
    service_key: str
    variant: str
    base_url: str | None = None
