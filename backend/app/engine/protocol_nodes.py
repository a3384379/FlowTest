import copy
import re
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.data_nodes import CredentialKind
from app.domain.expressions import SafeExpressionError, evaluate_safe_expression
from app.domain.protocols import GrpcCallType, GrpcTlsMode, ProtocolKind
from app.engine.contracts import WorkflowNode
from app.engine.scheduler import ExecutionContext, NodeExecutionError

_BINDING_INPUT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*$")


class GraphQLCapabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: UUID
    endpoint: str = Field(pattern=r"^https?://", min_length=8, max_length=2048)
    operation: str = Field(min_length=1, max_length=2 * 1024 * 1024)
    operation_name: str | None = Field(default=None, min_length=1, max_length=160)
    variables: dict[str, JsonValue] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class GrpcCapabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    descriptor_id: UUID
    endpoint: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$", min_length=3, max_length=512)
    service: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.]*$", max_length=512)
    method: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=160)
    request: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, str] = Field(default_factory=dict)
    call_type: GrpcCallType
    tls_mode: GrpcTlsMode = GrpcTlsMode.PLAINTEXT
    credential_id: UUID | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=300)

    @model_validator(mode="after")
    def validate_tls(self) -> "GrpcCapabilityConfig":
        if self.tls_mode is GrpcTlsMode.MTLS and self.credential_id is None:
            raise ValueError("mTLS 调用必须提供 Credential")
        if self.tls_mode is not GrpcTlsMode.MTLS and self.credential_id is not None:
            raise ValueError("只有 mTLS 调用可以提供 Credential")
        return self


ProtocolCapabilityConfig = GraphQLCapabilityConfig | GrpcCapabilityConfig


@dataclass(frozen=True, slots=True)
class PreparedProtocolNode:
    protocol: ProtocolKind
    schema_id: UUID
    schema_version: int
    schema_hash: str
    canonical_content: bytes
    credential: "ProtocolCredentialMaterial | None" = None


@dataclass(frozen=True, slots=True)
class ProtocolCredentialMaterial:
    id: UUID
    project_id: UUID
    name: str
    kind: CredentialKind
    host: str
    port: int
    secret: str


def parse_protocol_config(node: WorkflowNode) -> ProtocolCapabilityConfig:
    configuration = resolve_capability_configuration(node, None)
    if node.capability_id == "graphql.request" and node.capability_version == "3.0.0":
        return GraphQLCapabilityConfig.model_validate(configuration)
    if node.capability_id == "grpc.call" and node.capability_version == "3.0.0":
        return GrpcCapabilityConfig.model_validate(configuration)
    raise ValueError("Node is not a supported protocol capability")


def resolve_protocol_config(
    node: WorkflowNode,
    context: ExecutionContext,
) -> ProtocolCapabilityConfig:
    configuration = resolve_capability_configuration(node, context)
    try:
        if node.capability_id == "graphql.request" and node.capability_version == "3.0.0":
            return GraphQLCapabilityConfig.model_validate(configuration)
        if node.capability_id == "grpc.call" and node.capability_version == "3.0.0":
            return GrpcCapabilityConfig.model_validate(configuration)
    except ValueError as error:
        raise NodeExecutionError(
            code="INVALID_PROTOCOL_CONFIG",
            message="协议节点绑定后的配置无效",
        ) from error
    raise NodeExecutionError(
        code="CAPABILITY_RUNTIME_UNAVAILABLE",
        message="当前 Runner 不支持该协议能力版本",
    )


def resolve_capability_configuration(
    node: WorkflowNode,
    context: ExecutionContext | None,
) -> dict[str, JsonValue]:
    if node.configuration is None:
        raise ValueError("Capability configuration is missing")
    configuration = copy.deepcopy(node.configuration)
    if not node.bindings:
        return configuration
    if context is None:
        return configuration
    source = context.snapshot()
    for binding in node.bindings:
        if _BINDING_INPUT.fullmatch(binding.input) is None or not _binding_target_allowed(
            node, binding.input
        ):
            raise NodeExecutionError(
                code="INVALID_CAPABILITY_BINDING",
                message=f"绑定目标 {binding.input} 无效",
            )
        try:
            value = evaluate_safe_expression(binding.expression, source)
        except SafeExpressionError as error:
            raise NodeExecutionError(code=error.code, message=error.message) from error
        if value is None:
            raise NodeExecutionError(
                code="CAPABILITY_BINDING_SOURCE_MISSING",
                message=f"绑定表达式 {binding.expression} 未找到值",
            )
        _set_path(configuration, binding.input.split("."), value)
    return configuration


def _binding_target_allowed(node: WorkflowNode, target: str) -> bool:
    if node.capability_id == "graphql.request":
        return target.startswith("variables.")
    if node.capability_id == "grpc.call":
        return target.startswith("request.")
    return False


def _set_path(target: dict[str, JsonValue], path: list[str], value: JsonValue) -> None:
    current = target
    for part in path[:-1]:
        nested = current.get(part)
        if nested is None:
            created: dict[str, JsonValue] = {}
            current[part] = created
            current = created
            continue
        if not isinstance(nested, dict):
            raise NodeExecutionError(
                code="INVALID_CAPABILITY_BINDING",
                message=f"绑定目标 {'.'.join(path)} 与现有配置冲突",
            )
        current = nested
    current[path[-1]] = value
