"""Strict contracts for the S61C MCP contract import loop."""

import re
from typing import Literal
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    JsonValue,
    field_validator,
    model_validator,
)

from app.domain.api_assets import HttpMethod
from app.importers.contracts import ImportSourceType

MCP_CONTRACT_IMPORT_SCOPE = "mcp:contract:import"
MCP_CONTRACT_IMPORT_SCHEMA_VERSION: Literal["s61-mcp-contract-import-v1"] = (
    "s61-mcp-contract-import-v1"
)
MCP_CONTRACT_IMPORT_OPERATION = Literal["preview", "commit"]
MCP_CONTRACT_IMPORT_CHANGE = Literal["added", "changed", "deleted", "unchanged"]


class MCPContractParameter(BaseModel):
    """A structural operation parameter; it deliberately has no request value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=160)
    location: Literal["path", "query", "header", "cookie"]
    required: bool = False
    schema_: dict[str, JsonValue] = Field(default_factory=dict, alias="schema", max_length=80)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("参数名称不能为空")
        return value


class MCPContractRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required: bool = False
    content_type: str = Field(default="application/json", min_length=1, max_length=160)
    schema_: dict[str, JsonValue] = Field(default_factory=dict, alias="schema", max_length=80)


class MCPContractResponseShape(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = Field(default="", max_length=2000)
    content_type: str | None = Field(default=None, min_length=1, max_length=160)
    schema_: dict[str, JsonValue] | None = Field(default=None, alias="schema", max_length=80)


class MCPContractOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    method: HttpMethod
    path: str = Field(min_length=1, max_length=2048)
    target_base_url: HttpUrl | None = None
    parameters: list[MCPContractParameter] = Field(default_factory=list, max_length=100)
    request_body: MCPContractRequestBody | None = None
    responses: dict[str, MCPContractResponseShape] = Field(default_factory=dict, max_length=100)

    @field_validator("name", "description")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("/") or any(ord(character) < 32 for character in value):
            raise ValueError("接口路径必须是以 / 开头的安全路径")
        if "#" in value:
            raise ValueError("接口路径不能包含片段")
        return value

    @field_validator("target_base_url")
    @classmethod
    def validate_target_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is None:
            return None
        parsed = urlsplit(str(value))
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("目标地址不能包含凭据、查询参数或片段")
        return value

    @model_validator(mode="after")
    def validate_parameters(self) -> "MCPContractOperation":
        names = [(item.location, item.name.lower()) for item in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("同一接口不能包含重复位置和参数名称")
        path_names = {
            part[1:-1]
            for part in self.path.split("/")
            if part.startswith("{") and part.endswith("}")
        }
        declared_path_names = {item.name for item in self.parameters if item.location == "path"}
        if path_names - declared_path_names:
            raise ValueError("路径参数必须有对应的结构化声明")
        if any(item.location == "path" and not item.required for item in self.parameters):
            raise ValueError("路径参数必须标记为 required")
        return self

    @field_validator("responses")
    @classmethod
    def validate_response_statuses(
        cls, value: dict[str, MCPContractResponseShape]
    ) -> dict[str, MCPContractResponseShape]:
        if any(re.fullmatch(r"[1-5][0-9]{2}|default", status) is None for status in value):
            raise ValueError("响应状态必须是 HTTP 状态码或 default")
        return value


class MCPPreviewContractImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    source_kind: Literal["url", "document", "operations"]
    source_url: HttpUrl | None = None
    document_id: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$"
    )
    document_name: str | None = Field(default=None, min_length=1, max_length=255)
    document_content: str | None = Field(default=None, max_length=50 * 1024 * 1024)
    source_type: ImportSourceType = ImportSourceType.AUTO
    operations: list[MCPContractOperation] = Field(default_factory=list, max_length=100)
    persist: bool = True
    service_id: UUID | None = None
    environment_id: UUID | None = None
    endpoint_variant: str = Field(
        default="default", min_length=1, max_length=80, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$"
    )

    @field_validator("document_name")
    @classmethod
    def normalize_document_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().replace("\\", "/").rsplit("/", 1)[-1]
        return normalized or None

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is None:
            return None
        parsed = urlsplit(str(value))
        if parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise ValueError("契约地址不能包含凭据或片段")
        sensitive_keys = {"token", "key", "secret", "password", "api_key", "apikey"}
        if any(
            key.lower() in sensitive_keys
            for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
        ):
            raise ValueError("契约地址查询参数不能携带凭据")
        return value

    @model_validator(mode="after")
    def validate_source(self) -> "MCPPreviewContractImportRequest":
        if self.source_kind == "url" and self.source_url is None:
            raise ValueError("url 来源必须提供 source_url")
        if self.source_kind != "url" and self.source_url is not None:
            raise ValueError("非 url 来源不能提供 source_url")
        if self.source_kind != "url" and self.document_id is not None:
            raise ValueError("非 url 来源不能提供 document_id")
        if self.source_kind == "document" and not self.document_content:
            raise ValueError("document 来源必须提供有界文档内容")
        if self.source_kind != "document" and self.document_content is not None:
            raise ValueError("非 document 来源不能提供 document_content")
        if self.source_kind == "operations" and not self.operations:
            raise ValueError("operations 来源必须提供至少一个强类型接口")
        if self.source_kind != "operations" and self.operations:
            raise ValueError("非 operations 来源不能提供 operations")
        if self.source_kind == "document" and not self.document_name:
            raise ValueError("document 来源必须提供 document_name")
        return self


class MCPCommitContractImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    preview_id: UUID
    preview_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    selected_operations: list[str] = Field(min_length=1, max_length=100)
    expected_current_versions: dict[str, int] = Field(default_factory=dict, max_length=100)
    confirm_existing_changes: bool = False
    service_id: UUID | None = None
    environment_id: UUID | None = None
    endpoint_variant: str = Field(
        default="default", min_length=1, max_length=80, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$"
    )

    @field_validator("selected_operations")
    @classmethod
    def validate_selected_operations(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item or len(item) > 255 for item in normalized):
            raise ValueError("selected_operations 包含空值或过长标识")
        if len(normalized) != len(set(normalized)):
            raise ValueError("selected_operations 不能重复")
        return normalized

    @field_validator("expected_current_versions")
    @classmethod
    def validate_versions(cls, value: dict[str, int]) -> dict[str, int]:
        if any(version < 0 for version in value.values()):
            raise ValueError("期望版本不能为负数")
        return value


class MCPContractImportItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    import_key: str
    name: str
    method: str
    path: str
    change: MCP_CONTRACT_IMPORT_CHANGE
    definition_id: UUID | None = None
    version: int = Field(ge=0)
    server_url: str | None = None


class MCPPreviewContractImportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["s61-mcp-contract-import-v1"] = MCP_CONTRACT_IMPORT_SCHEMA_VERSION
    operation: Literal["preview"] = "preview"
    organization_id: UUID
    project_id: UUID
    persisted: bool
    preview_id: UUID | None = None
    source_kind: Literal["file", "url"]
    source_type: ImportSourceType
    source_name: str
    source_url: str | None = None
    document_url: str | None = None
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    items: list[MCPContractImportItem] = Field(default_factory=list, max_length=200)
    added: int = Field(ge=0)
    changed: int = Field(ge=0)
    deleted: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    target_service_id: UUID | None = None
    target_environment_id: UUID | None = None
    target_fingerprint: str | None = None
    warnings: list[str] = Field(default_factory=list, max_length=50)
    trace_id: str = Field(min_length=1, max_length=128)
    next_action: Literal["commit", "review_required", "none"]


class MCPCommitContractImportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["s61-mcp-contract-import-v1"] = MCP_CONTRACT_IMPORT_SCHEMA_VERSION
    operation: Literal["commit"] = "commit"
    organization_id: UUID
    project_id: UUID
    import_run_id: UUID
    status: Literal["applied"]
    applied_keys: list[str] = Field(default_factory=list, max_length=100)
    created_definition_ids: list[UUID] = Field(default_factory=list, max_length=100)
    changed_definition_ids: list[UUID] = Field(default_factory=list, max_length=100)
    deleted_definition_ids: list[UUID] = Field(default_factory=list, max_length=100)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    results: list[MCPContractImportItem] = Field(default_factory=list, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=50)
    idempotency_replayed: bool = False
    trace_id: str = Field(min_length=1, max_length=128)
    next_action: Literal["inspect_contract", "none"] = "inspect_contract"
