from dataclasses import dataclass
from typing import cast

from pydantic import JsonValue

from app.domain.capabilities import (
    CapabilityCategory,
    CapabilityManifest,
    NetworkAccess,
    NetworkPolicy,
    RedactionPolicy,
    RunnerType,
    SnapshotPolicy,
    TimeoutPolicy,
)
from app.engine.contracts import (
    CAPABILITY_LEGACY_NODE_TYPES,
    ApiNodeConfig,
    AssertNodeConfig,
    ConditionNodeConfig,
    DatasetNodeConfig,
    DelayNodeConfig,
    ExtractNodeConfig,
    ForEachNodeConfig,
    NodeType,
    RedisNodeConfig,
    SqlNodeConfig,
    StartNodeConfig,
    SubFlowNodeConfig,
    WorkflowNode,
)
from app.engine.event_nodes import (
    KafkaConsumeCapabilityConfig,
    KafkaProduceCapabilityConfig,
    WebSocketAwaitCapabilityConfig,
    WebSocketCloseCapabilityConfig,
    WebSocketConnectCapabilityConfig,
    WebSocketExchangeCapabilityConfig,
    WebSocketSendCapabilityConfig,
)
from app.engine.protocol_nodes import GraphQLCapabilityConfig, GrpcCapabilityConfig

_LEGACY_CAPABILITIES: dict[NodeType, tuple[str, str]] = {
    NodeType.START: ("flow.start", "2.0.0"),
    NodeType.API: ("http.request", "2.0.0"),
    NodeType.EXTRACT: ("data.extract", "2.0.0"),
    NodeType.ASSERT: ("assertion.evaluate", "2.0.0"),
    NodeType.CONDITION: ("flow.condition", "2.0.0"),
    NodeType.DELAY: ("flow.delay", "2.0.0"),
    NodeType.DATASET: ("data.dataset", "2.0.0"),
    NodeType.SUBFLOW: ("flow.subflow", "2.0.0"),
    NodeType.FOR_EACH: ("flow.foreach", "2.0.0"),
    NodeType.SQL: ("sql.query", "2.0.0"),
    NodeType.REDIS: ("redis.read", "2.0.0"),
    NodeType.END: ("flow.end", "2.0.0"),
}


@dataclass(frozen=True, slots=True)
class CapabilityInvocation:
    node_id: str
    capability_id: str
    capability_version: str
    configuration: dict[str, JsonValue]
    bindings: tuple[tuple[str, str], ...]
    source: str


class CapabilityRegistry:
    """Immutable manifest registry used while planning and running a snapshot."""

    def __init__(self, manifests: tuple[CapabilityManifest, ...]) -> None:
        by_key: dict[tuple[str, str], CapabilityManifest] = {}
        for manifest in manifests:
            key = (manifest.id, manifest.version)
            if key in by_key:
                raise ValueError(f"Duplicate capability manifest {manifest.id}@{manifest.version}")
            by_key[key] = manifest
        self._by_key = by_key

    def get(self, capability_id: str, version: str) -> CapabilityManifest | None:
        return self._by_key.get((capability_id, version))

    def require(self, capability_id: str, version: str) -> CapabilityManifest:
        manifest = self.get(capability_id, version)
        if manifest is None:
            raise ValueError(f"Unknown capability {capability_id}@{version}")
        return manifest

    def list(self) -> tuple[CapabilityManifest, ...]:
        return tuple(sorted(self._by_key.values(), key=lambda item: (item.category, item.id)))


class LegacyNodeAdapter:
    """Compiles V2 nodes into pinned V3 invocations without rewriting stored workflows."""

    def compile(self, node: WorkflowNode) -> CapabilityInvocation:
        if node.type is NodeType.CAPABILITY:
            if (
                node.capability_id is None
                or node.capability_version is None
                or node.configuration is None
                or node.bindings is None
            ):
                raise ValueError("Capability node contract is incomplete")
            return CapabilityInvocation(
                node_id=node.id,
                capability_id=node.capability_id,
                capability_version=node.capability_version,
                configuration=node.configuration,
                bindings=tuple((binding.input, binding.expression) for binding in node.bindings),
                source="v3",
            )
        capability_id, capability_version = _LEGACY_CAPABILITIES[node.type]
        return CapabilityInvocation(
            node_id=node.id,
            capability_id=capability_id,
            capability_version=capability_version,
            configuration=node.config,
            bindings=(),
            source="legacy",
        )

    def as_legacy_node(self, node: WorkflowNode) -> WorkflowNode:
        if node.type is not NodeType.CAPABILITY:
            return node
        if (
            node.capability_id is None
            or node.capability_version is None
            or node.configuration is None
        ):
            raise ValueError("Capability node contract is incomplete")
        node_type = CAPABILITY_LEGACY_NODE_TYPES.get((node.capability_id, node.capability_version))
        if node_type is None:
            raise ValueError(
                f"Capability {node.capability_id}@{node.capability_version} has no legacy adapter"
            )
        return WorkflowNode(
            id=node.id,
            type=node_type,
            name=node.name,
            position=node.position,
            config=node.configuration,
        )


def capability_snapshot(
    node: WorkflowNode,
    *,
    registry: CapabilityRegistry,
) -> dict[str, JsonValue]:
    invocation = legacy_node_adapter.compile(node)
    manifest = registry.require(invocation.capability_id, invocation.capability_version)
    return {
        "node_id": node.id,
        "capability_id": manifest.id,
        "capability_version": manifest.version,
        "schema_hash": manifest.schema_hash,
        "runner_type": manifest.runner_type.value,
        "source": invocation.source,
        "plugin_id": manifest.plugin_id,
        "plugin_digest": manifest.plugin_digest,
    }


def _schema(model: type[object] | None) -> dict[str, JsonValue]:
    if model is None:
        return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
    schema = model.model_json_schema()  # type: ignore[attr-defined]
    schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
    return cast(dict[str, JsonValue], schema)


def _manifest(
    capability_id: str,
    display_name: str,
    category: CapabilityCategory,
    config_model: type[object] | None,
    *,
    runner_type: RunnerType = RunnerType.GENERAL,
    network_policy: NetworkPolicy | None = None,
    credential_types: tuple[str, ...] = (),
    sensitive_paths: tuple[str, ...] = (),
) -> CapabilityManifest:
    return CapabilityManifest(
        id=capability_id,
        version="2.0.0",
        category=category,
        display_name=display_name,
        description="由 Legacy Adapter 固定的 FlowTest V2 内置能力",
        input_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": True,
        },
        output_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
        },
        configuration_schema=_schema(config_model),
        credential_types=credential_types,
        network_policy=network_policy or NetworkPolicy(),
        runner_type=runner_type,
        timeout_policy=TimeoutPolicy(),
        snapshot_policy=SnapshotPolicy(),
        redaction_policy=RedactionPolicy(sensitive_paths=sensitive_paths),
    )


def _v3_protocol_manifest(
    capability_id: str,
    display_name: str,
    config_model: type[object],
    *,
    protocols: tuple[str, ...],
    credential_types: tuple[str, ...] = (),
    sensitive_paths: tuple[str, ...] = (),
) -> CapabilityManifest:
    return CapabilityManifest(
        id=capability_id,
        version="3.0.0",
        category=CapabilityCategory.PROTOCOL,
        display_name=display_name,
        description="FlowTest V3 多协议工作台内置能力",
        input_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": True,
        },
        output_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["protocol", "schema_version", "schema_hash"],
        },
        configuration_schema=_schema(config_model),
        credential_types=credential_types,
        network_policy=NetworkPolicy(
            access=NetworkAccess.PROJECT_ALLOWLIST,
            protocols=protocols,
        ),
        runner_type=RunnerType.PROTOCOL,
        timeout_policy=TimeoutPolicy(),
        snapshot_policy=SnapshotPolicy(),
        redaction_policy=RedactionPolicy(sensitive_paths=sensitive_paths),
    )


def _v3_event_manifest(
    capability_id: str,
    display_name: str,
    config_model: type[object],
    *,
    protocols: tuple[str, ...],
    sensitive_paths: tuple[str, ...] = (),
) -> CapabilityManifest:
    return CapabilityManifest(
        id=capability_id,
        version="3.0.0",
        category=CapabilityCategory.PROTOCOL,
        display_name=display_name,
        description="FlowTest V3 有界事件协议内置能力",
        input_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": True,
        },
        output_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["protocol", "operation"],
        },
        configuration_schema=_schema(config_model),
        network_policy=NetworkPolicy(
            access=NetworkAccess.PROJECT_ALLOWLIST,
            protocols=protocols,
        ),
        runner_type=RunnerType.PROTOCOL,
        timeout_policy=TimeoutPolicy(),
        snapshot_policy=SnapshotPolicy(),
        redaction_policy=RedactionPolicy(sensitive_paths=sensitive_paths),
    )


BUILTIN_CAPABILITY_MANIFESTS = (
    _manifest("flow.start", "开始", CapabilityCategory.CONTROL, StartNodeConfig),
    _manifest(
        "http.request",
        "HTTP 请求",
        CapabilityCategory.PROTOCOL,
        ApiNodeConfig,
        network_policy=NetworkPolicy(
            access=NetworkAccess.PROJECT_ALLOWLIST,
            protocols=("http", "https"),
        ),
        sensitive_paths=("headers.authorization", "headers.cookie", "body.password"),
    ),
    _manifest("data.extract", "提取变量", CapabilityCategory.DATA, ExtractNodeConfig),
    _manifest(
        "assertion.evaluate",
        "断言",
        CapabilityCategory.ASSERTION,
        AssertNodeConfig,
    ),
    _manifest("flow.condition", "条件", CapabilityCategory.CONTROL, ConditionNodeConfig),
    _manifest("flow.delay", "延迟", CapabilityCategory.CONTROL, DelayNodeConfig),
    _manifest("data.dataset", "数据集", CapabilityCategory.DATA, DatasetNodeConfig),
    _manifest("flow.subflow", "子流程", CapabilityCategory.CONTROL, SubFlowNodeConfig),
    _manifest("flow.foreach", "循环", CapabilityCategory.CONTROL, ForEachNodeConfig),
    _manifest(
        "sql.query",
        "只读 SQL",
        CapabilityCategory.DATA,
        SqlNodeConfig,
        runner_type=RunnerType.DATA,
        network_policy=NetworkPolicy(
            access=NetworkAccess.PROJECT_ALLOWLIST,
            protocols=("postgresql", "mysql"),
        ),
        credential_types=("postgresql", "mysql"),
        sensitive_paths=("credential",),
    ),
    _manifest(
        "redis.read",
        "Redis 只读",
        CapabilityCategory.DATA,
        RedisNodeConfig,
        runner_type=RunnerType.DATA,
        network_policy=NetworkPolicy(
            access=NetworkAccess.PROJECT_ALLOWLIST,
            protocols=("redis", "rediss"),
        ),
        credential_types=("redis",),
        sensitive_paths=("credential",),
    ),
    _manifest("flow.end", "结束", CapabilityCategory.CONTROL, None),
    _v3_protocol_manifest(
        "graphql.request",
        "GraphQL Query / Mutation",
        GraphQLCapabilityConfig,
        protocols=("http", "https"),
        sensitive_paths=("headers.authorization", "headers.cookie"),
    ),
    _v3_protocol_manifest(
        "grpc.call",
        "gRPC Unary / Server Streaming",
        GrpcCapabilityConfig,
        protocols=("grpc", "grpcs"),
        credential_types=("grpc_mtls",),
        sensitive_paths=("metadata.authorization", "credential"),
    ),
    _v3_event_manifest(
        "kafka.produce",
        "Kafka Produce",
        KafkaProduceCapabilityConfig,
        protocols=("kafka",),
        sensitive_paths=("headers.authorization", "headers.token"),
    ),
    _v3_event_manifest(
        "kafka.consume",
        "Kafka Consume",
        KafkaConsumeCapabilityConfig,
        protocols=("kafka",),
    ),
    _v3_event_manifest(
        "websocket.connect",
        "WebSocket Connect",
        WebSocketConnectCapabilityConfig,
        protocols=("ws", "wss"),
        sensitive_paths=("headers.authorization", "headers.cookie"),
    ),
    _v3_event_manifest(
        "websocket.send",
        "WebSocket Send",
        WebSocketSendCapabilityConfig,
        protocols=("ws", "wss"),
    ),
    _v3_event_manifest(
        "websocket.await",
        "WebSocket Await",
        WebSocketAwaitCapabilityConfig,
        protocols=("ws", "wss"),
    ),
    _v3_event_manifest(
        "websocket.close",
        "WebSocket Close",
        WebSocketCloseCapabilityConfig,
        protocols=("ws", "wss"),
    ),
    _v3_event_manifest(
        "websocket.exchange",
        "WebSocket Exchange",
        WebSocketExchangeCapabilityConfig,
        protocols=("ws", "wss"),
        sensitive_paths=("headers.authorization", "headers.cookie"),
    ),
)

builtin_capability_registry = CapabilityRegistry(BUILTIN_CAPABILITY_MANIFESTS)
legacy_node_adapter = LegacyNodeAdapter()
