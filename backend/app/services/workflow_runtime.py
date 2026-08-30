import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from time import perf_counter
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

import httpx
from pydantic import JsonValue

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import redact
from app.domain.api_assets import BodyKind
from app.domain.expressions import SafeExpressionError, evaluate_bounded_array
from app.domain.network import OutboundNetworkPolicy
from app.domain.scopes import HeaderScope
from app.engine.capabilities import legacy_node_adapter
from app.engine.contracts import (
    ApiNodeConfig,
    FieldMapping,
    ForEachNodeConfig,
    MappingTargetLocation,
    NodeStatus,
    NodeType,
    RedisNodeConfig,
    RetryCategory,
    SqlNodeConfig,
    SubFlowNodeConfig,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowPhase,
    parse_node_config,
)
from app.engine.control_nodes import execute_control_node
from app.engine.event_nodes import (
    KafkaConsumeCapabilityConfig,
    KafkaProduceCapabilityConfig,
    PreparedEventNode,
    WebSocketAwaitCapabilityConfig,
    WebSocketCloseCapabilityConfig,
    WebSocketConnectCapabilityConfig,
    WebSocketExchangeCapabilityConfig,
    WebSocketSendCapabilityConfig,
    resolve_event_config,
)
from app.engine.mappings import MappingResolutionError, ResolvedFieldMapping, resolve_field_mappings
from app.engine.node_sdk import NodeHandlerRegistration, NodeHandlerRegistry
from app.engine.protocol_nodes import (
    GraphQLCapabilityConfig,
    PreparedProtocolNode,
    resolve_protocol_config,
)
from app.engine.results import (
    HttpRequestSnapshot,
    HttpResponseSnapshot,
    NodeInputMapping,
    NodeObservation,
    NodeResult,
)
from app.engine.scheduler import (
    NESTED_CHECKPOINT_PREFIX,
    CancellationToken,
    ExecutionContext,
    NodeExecutionError,
    NodeRunRecord,
    NodeStatusCallback,
    NodeStatusUpdate,
    RequestBudget,
    WorkflowRunResult,
    WorkflowScheduler,
    node_type_consumes_request,
)
from app.services.api_assets import PreparedHeader, PreparedRequest
from app.services.data_nodes import (
    DataNodeRunner,
    InfrastructureDataNodeRunner,
    PreparedDataNode,
)
from app.services.event_runtime import EventProtocolRunner
from app.services.executions import (
    PreparedMultipart,
    _redact_request_url,
    _redact_response_headers,
    _response_body,
    _send_request,
)
from app.services.outbound import OutboundRequestGuard, outbound_request_guard
from app.services.protocol_runtime import ProtocolRunner

_DATA_VARIABLE = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}$")


@dataclass(frozen=True, slots=True)
class PreparedWorkflowRequest:
    request: PreparedRequest
    redacted_request: PreparedRequest
    body_kind: BodyKind
    multipart: PreparedMultipart | None


@dataclass(frozen=True, slots=True)
class PreparedSubflow:
    workflow_id: UUID
    workflow_version: int
    fingerprint: str
    definition: WorkflowDefinition
    requests: dict[str, PreparedWorkflowRequest]
    subflows: dict[str, "PreparedSubflow"]
    snapshot: dict[str, JsonValue]
    data_nodes: dict[str, PreparedDataNode] = dataclass_field(default_factory=dict)
    protocol_nodes: dict[str, PreparedProtocolNode] = dataclass_field(default_factory=dict)
    event_nodes: dict[str, PreparedEventNode] = dataclass_field(default_factory=dict)


class WorkflowNodeExecutor:
    def __init__(
        self,
        client: httpx.AsyncClient,
        requests: dict[str, PreparedWorkflowRequest],
        definition: WorkflowDefinition,
        network_policy: OutboundNetworkPolicy,
        subflows: dict[str, PreparedSubflow] | None = None,
        outbound_guard: OutboundRequestGuard = outbound_request_guard,
        data_nodes: dict[str, PreparedDataNode] | None = None,
        data_runner: DataNodeRunner | None = None,
        protocol_nodes: dict[str, PreparedProtocolNode] | None = None,
        event_nodes: dict[str, PreparedEventNode] | None = None,
    ) -> None:
        self._client = client
        self._requests = requests
        self._mappings = _mappings_by_target(definition)
        self._network_policy = network_policy
        self._subflows = subflows or {}
        self._data_nodes = data_nodes or {}
        self._outbound_guard = outbound_guard
        self._protocol_nodes = protocol_nodes or {}
        self._event_nodes = event_nodes or {}
        self._protocol_runner = ProtocolRunner(
            client,
            network_policy,
            outbound_guard=outbound_guard,
        )
        self._event_runner = EventProtocolRunner(
            network_policy,
            outbound_guard=outbound_guard,
        )
        self._data_runner = data_runner or InfrastructureDataNodeRunner(
            network_policy,
            outbound_guard=outbound_guard,
        )
        control_types = frozenset(NodeType) - {
            NodeType.API,
            NodeType.SUBFLOW,
            NodeType.FOR_EACH,
            NodeType.SQL,
            NodeType.REDIS,
            NodeType.CAPABILITY,
        }
        self._handlers = NodeHandlerRegistry(
            [
                NodeHandlerRegistration(NodeType.API, self._execute_api),
                NodeHandlerRegistration(NodeType.SUBFLOW, self._execute_subflow),
                NodeHandlerRegistration(NodeType.FOR_EACH, self._execute_for_each),
                NodeHandlerRegistration(NodeType.SQL, self._execute_sql),
                NodeHandlerRegistration(NodeType.REDIS, self._execute_redis),
                NodeHandlerRegistration(NodeType.CAPABILITY, self._execute_capability),
                *[
                    NodeHandlerRegistration(node_type, execute_control_node)
                    for node_type in control_types
                ],
            ]
        )

    async def execute(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        return await self._handlers.execute(node, context)

    async def close(self) -> None:
        await self._event_runner.close_all()

    async def _execute_capability(
        self,
        node: WorkflowNode,
        context: ExecutionContext,
    ) -> JsonValue:
        if node.capability_id in {"graphql.request", "grpc.call"}:
            return await self._execute_protocol(node, context)
        if node.capability_id and node.capability_id.startswith(("kafka.", "websocket.")):
            return await self._execute_event_protocol(node, context)
        try:
            legacy_node = legacy_node_adapter.as_legacy_node(node)
        except ValueError as error:
            raise NodeExecutionError(
                code="CAPABILITY_RUNTIME_UNAVAILABLE",
                message="当前 Runner 不支持该能力版本",
            ) from error
        return await self._handlers.execute(legacy_node, context)

    async def _execute_protocol(
        self,
        node: WorkflowNode,
        context: ExecutionContext,
    ) -> JsonValue:
        prepared = self._protocol_nodes.get(node.id)
        if prepared is None:
            raise NodeExecutionError(
                code="PROTOCOL_SNAPSHOT_MISSING",
                message=f"节点 {node.name} 缺少固定协议 Schema 快照",
            )
        config = resolve_protocol_config(node, context)
        if isinstance(config, GraphQLCapabilityConfig):
            result = await self._protocol_runner.execute_graphql(prepared, config)
        else:
            result = await self._protocol_runner.execute_grpc(prepared, config)
        if isinstance(result.output, dict):
            return {**result.output, "duration_ms": result.duration_ms}
        return result.output

    async def _execute_event_protocol(
        self,
        node: WorkflowNode,
        context: ExecutionContext,
    ) -> JsonValue:
        config = resolve_event_config(node, context)
        prepared = self._event_nodes.get(node.id)
        if isinstance(config, KafkaProduceCapabilityConfig):
            result = await self._event_runner.execute_kafka_produce(
                self._require_event_snapshot(node, prepared), config
            )
        elif isinstance(config, KafkaConsumeCapabilityConfig):
            result = await self._event_runner.execute_kafka_consume(
                self._require_event_snapshot(node, prepared), config
            )
        elif isinstance(config, WebSocketConnectCapabilityConfig):
            result = await self._event_runner.execute_websocket_connect(
                self._require_event_snapshot(node, prepared), config
            )
        elif isinstance(config, WebSocketSendCapabilityConfig):
            result = await self._event_runner.execute_websocket_send(config)
        elif isinstance(config, WebSocketAwaitCapabilityConfig):
            result = await self._event_runner.execute_websocket_await(config)
        elif isinstance(config, WebSocketCloseCapabilityConfig):
            result = await self._event_runner.execute_websocket_close(config)
        elif isinstance(config, WebSocketExchangeCapabilityConfig):
            result = await self._event_runner.execute_websocket_exchange(
                self._require_event_snapshot(node, prepared), config
            )
        else:
            raise NodeExecutionError(
                code="CAPABILITY_RUNTIME_UNAVAILABLE",
                message="当前 Runner 不支持该事件能力版本",
            )
        if isinstance(result.output, dict):
            return {**result.output, "duration_ms": result.duration_ms}
        return result.output

    @staticmethod
    def _require_event_snapshot(
        node: WorkflowNode,
        prepared: PreparedEventNode | None,
    ) -> PreparedEventNode:
        if prepared is None:
            raise NodeExecutionError(
                code="EVENT_SOURCE_SNAPSHOT_MISSING",
                message=f"节点 {node.name} 缺少固定事件源 Snapshot",
            )
        return prepared

    async def _execute_api(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        config = parse_node_config(node)
        if not isinstance(config, ApiNodeConfig):
            raise NodeExecutionError(
                code="INVALID_API_CONFIG", message=f"节点 {node.name} 的 API 配置无效"
            )
        prepared = self._requests[node.id]
        try:
            resolved_mappings = resolve_field_mappings(
                self._mappings.get(node.id, ()),
                context,
            )
            request, mapping_trace = _apply_mappings(
                prepared.request,
                resolved_mappings,
                context,
            )
            redacted_request = _apply_redacted_mappings(
                prepared.redacted_request,
                resolved_mappings,
            )
        except MappingResolutionError as error:
            raise NodeExecutionError(code=error.code, message=error.message) from error
        attempt = len(context.observations_of(node.id)) + 1
        started_at = datetime.now(UTC)
        started = perf_counter()
        try:
            await self._outbound_guard.enforce(request.url, self._network_policy)
        except AppError as error:
            _record_http_observation(
                context,
                node_id=node.id,
                attempt=attempt,
                request=redacted_request,
                mappings=mapping_trace,
                started_at=started_at,
                started=started,
                error_code=error.code,
                error_message=error.message,
            )
            raise NodeExecutionError(code=error.code, message=error.message) from error
        try:
            response = await _send_request(
                self._client,
                request,
                body_kind=prepared.body_kind,
                timeout_seconds=300,
                multipart=prepared.multipart,
            )
        except httpx.TimeoutException as error:
            _record_http_observation(
                context,
                node_id=node.id,
                attempt=attempt,
                request=redacted_request,
                mappings=mapping_trace,
                started_at=started_at,
                started=started,
                error_code="NETWORK_TIMEOUT",
                error_message="目标接口请求超时",
            )
            raise NodeExecutionError(
                code="NETWORK_TIMEOUT",
                message="目标接口请求超时",
                category=RetryCategory.NETWORK_ERROR,
            ) from error
        except httpx.HTTPError as error:
            _record_http_observation(
                context,
                node_id=node.id,
                attempt=attempt,
                request=redacted_request,
                mappings=mapping_trace,
                started_at=started_at,
                started=started,
                error_code="NETWORK_ERROR",
                error_message="无法连接目标接口",
            )
            raise NodeExecutionError(
                code="NETWORK_ERROR",
                message="无法连接目标接口",
                category=RetryCategory.NETWORK_ERROR,
            ) from error

        duration_ms = (perf_counter() - started) * 1000
        _record_http_observation(
            context,
            node_id=node.id,
            attempt=attempt,
            request=redacted_request,
            mappings=mapping_trace,
            started_at=started_at,
            started=started,
            response=response,
        )
        output = _response_output(response)
        output["duration_ms"] = duration_ms
        output["input_mappings"] = cast(
            JsonValue,
            [item.model_dump(mode="json") for item in mapping_trace],
        )
        if config.expected_statuses is not None:
            if response.status_code in config.expected_statuses:
                return output
            raise NodeExecutionError(
                code="HTTP_UNEXPECTED_STATUS",
                message=f"目标接口返回未预期状态 {response.status_code}",
                category=(RetryCategory.SERVER_ERROR if response.status_code >= 500 else None),
                output=output,
            )
        if response.status_code >= 500:
            raise NodeExecutionError(
                code="HTTP_5XX",
                message=f"目标接口返回 {response.status_code}",
                category=RetryCategory.SERVER_ERROR,
                output=output,
            )
        if response.status_code >= 400:
            raise NodeExecutionError(
                code="HTTP_4XX",
                message=f"目标接口返回 {response.status_code}",
                output=output,
            )
        return output

    async def _execute_subflow(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        config = parse_node_config(node)
        if not isinstance(config, SubFlowNodeConfig) or isinstance(config, ForEachNodeConfig):
            raise NodeExecutionError(
                code="INVALID_SUBFLOW_CONFIG",
                message=f"节点 {node.name} 的子流程配置无效",
            )
        prepared = self._prepared_subflow(node)
        result = await self._run_subflow(
            prepared,
            context.resolved_variables(),
            context.request_budget,
            status_callback=context.status_callback,
            checkpoint_scope=_nested_scope(context.checkpoint_scope, "subflow", node.id),
            checkpoint_phase=context.checkpoint_phase or node.phase,
            checkpoint_best_effort=(
                context.checkpoint_best_effort
                if context.checkpoint_phase is not None
                else node.best_effort
            ),
            checkpoint_records=context.nested_checkpoint_records,
            reset_retry_budget=context.reset_retry_budget,
            parent_cancellation=context.cancellation,
        )
        output = _subflow_output(prepared, result)
        if result.status.value != "passed":
            raise NodeExecutionError(
                code="SUBFLOW_FAILED",
                message=f"子流程 {node.name} 执行失败",
                output=output,
            )
        return output

    async def _execute_for_each(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        config = parse_node_config(node)
        if not isinstance(config, ForEachNodeConfig):
            raise NodeExecutionError(
                code="INVALID_FOR_EACH_CONFIG",
                message=f"节点 {node.name} 的循环配置无效",
            )
        try:
            items = evaluate_bounded_array(
                config.expression,
                context.output_of(config.source_node_id),
            )
        except SafeExpressionError as error:
            raise NodeExecutionError(code=error.code, message=error.message) from error

        prepared = self._prepared_subflow(node)
        completed = await self._run_for_each_items(node, prepared, config, context, items)
        output = _for_each_output(config, items, completed)
        if _for_each_failed(completed):
            raise NodeExecutionError(
                code="FOR_EACH_ITEM_FAILED",
                message=f"循环节点 {node.name} 包含失败项",
                output=output,
            )
        return output

    async def _execute_sql(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        config = parse_node_config(node)
        if not isinstance(config, SqlNodeConfig):
            raise NodeExecutionError(code="INVALID_SQL_CONFIG", message="SQL 节点配置无效")
        prepared = self._prepared_data_node(node)
        parameters = {
            name: _resolve_data_value(value, context) for name, value in config.parameters.items()
        }
        return await self._data_runner.execute_sql(
            prepared.credential,
            config.query,
            parameters,
            config.timeout_seconds,
        )

    async def _execute_redis(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        config = parse_node_config(node)
        if not isinstance(config, RedisNodeConfig):
            raise NodeExecutionError(code="INVALID_REDIS_CONFIG", message="Redis 节点配置无效")
        prepared = self._prepared_data_node(node)
        arguments = [
            _data_argument(_resolve_data_value(argument, context)) for argument in config.arguments
        ]
        return await self._data_runner.execute_redis(
            prepared.credential,
            config.command,
            arguments,
            config.timeout_seconds,
        )

    async def _run_for_each_items(
        self,
        node: WorkflowNode,
        prepared: PreparedSubflow,
        config: ForEachNodeConfig,
        context: ExecutionContext,
        items: list[JsonValue],
    ) -> list[dict[str, JsonValue]]:
        semaphore = asyncio.Semaphore(config.concurrency)
        tasks = [
            asyncio.create_task(
                self._run_for_each_item(
                    node,
                    prepared,
                    config,
                    context,
                    semaphore,
                    index,
                    item,
                )
            )
            for index, item in enumerate(items)
        ]
        return await _collect_for_each_tasks(tasks, fail_fast=config.fail_fast)

    async def _run_for_each_item(
        self,
        node: WorkflowNode,
        prepared: PreparedSubflow,
        config: ForEachNodeConfig,
        context: ExecutionContext,
        semaphore: asyncio.Semaphore,
        index: int,
        item: JsonValue,
    ) -> dict[str, JsonValue]:
        async with semaphore:
            checkpoint_scope = _nested_scope(
                context.checkpoint_scope,
                "for_each",
                node.id,
                index=index,
            )
            _require_preview_for_each_request_reservation(
                prepared,
                context.request_budget,
                checkpoint_scope=checkpoint_scope,
                checkpoint_records=context.nested_checkpoint_records,
            )
            variables = {
                **context.resolved_variables(),
                config.item_variable: item,
                config.index_variable: index,
            }
            result = await self._run_subflow(
                prepared,
                variables,
                context.request_budget,
                status_callback=context.status_callback,
                checkpoint_scope=checkpoint_scope,
                checkpoint_phase=context.checkpoint_phase or node.phase,
                checkpoint_best_effort=(
                    context.checkpoint_best_effort
                    if context.checkpoint_phase is not None
                    else node.best_effort
                ),
                checkpoint_records=context.nested_checkpoint_records,
                reset_retry_budget=context.reset_retry_budget,
                parent_cancellation=context.cancellation,
            )
            return {
                "index": index,
                "item": item,
                "result": _subflow_output(prepared, result),
            }

    async def _run_subflow(
        self,
        prepared: PreparedSubflow,
        runtime_variables: dict[str, JsonValue],
        request_budget: RequestBudget | None,
        *,
        status_callback: NodeStatusCallback | None,
        checkpoint_scope: tuple[str, ...],
        checkpoint_phase: WorkflowPhase,
        checkpoint_best_effort: bool,
        checkpoint_records: dict[str, NodeRunRecord],
        reset_retry_budget: bool,
        parent_cancellation: CancellationToken | None,
    ) -> WorkflowRunResult:
        executor = WorkflowNodeExecutor(
            self._client,
            prepared.requests,
            prepared.definition,
            self._network_policy,
            subflows=prepared.subflows,
            outbound_guard=self._outbound_guard,
            data_nodes=prepared.data_nodes,
            data_runner=self._data_runner,
            protocol_nodes=prepared.protocol_nodes,
            event_nodes=prepared.event_nodes,
        )
        resume_records = _nested_resume_records(
            prepared.definition,
            checkpoint_scope,
            checkpoint_records,
        )
        resume_attempts = {record.node_id: record.attempts for record in resume_records}

        async def publish_nested(update: NodeStatusUpdate) -> None:
            nested_node = next(
                (node for node in prepared.definition.nodes if node.id == update.node_id),
                None,
            )
            if nested_node is None:
                return
            consumes_request = node_type_consumes_request(nested_node.effective_type)
            should_checkpoint = update.status.is_terminal or (
                consumes_request and update.status is NodeStatus.RUNNING and update.request_reserved
            )
            if not should_checkpoint:
                return
            nested_id = _nested_checkpoint_id(checkpoint_scope, update.node_id)
            mapped = replace(
                update,
                node_id=nested_id,
                node_type=nested_node.effective_type,
                phase=checkpoint_phase,
                best_effort=checkpoint_best_effort,
            )
            checkpoint_records[nested_id] = _checkpoint_record(mapped)
            if status_callback is not None:
                await status_callback(mapped)

        nested_cancellation = CancellationToken()
        force_forwarder = (
            asyncio.create_task(
                _forward_force_cancellation(parent_cancellation, nested_cancellation)
            )
            if parent_cancellation is not None
            else None
        )
        run_task = asyncio.create_task(
            WorkflowScheduler(executor).run(
                prepared.definition,
                context=ExecutionContext(
                    workflow_variables=dict(prepared.definition.variables),
                    runtime_variables=runtime_variables,
                    status_callback=status_callback,
                    checkpoint_scope=checkpoint_scope,
                    checkpoint_phase=checkpoint_phase,
                    checkpoint_best_effort=checkpoint_best_effort,
                    nested_checkpoint_records=checkpoint_records,
                    reset_retry_budget=reset_retry_budget,
                ),
                cancellation=nested_cancellation,
                on_node_status=publish_nested,
                resume_records=resume_records,
                resume_attempts=resume_attempts,
                reset_retry_budget=reset_retry_budget,
                shared_request_budget=request_budget,
            )
        )
        try:
            return await asyncio.shield(run_task)
        except asyncio.CancelledError:
            nested_cancellation.cancel(
                force=(
                    parent_cancellation.force_cancelled
                    if parent_cancellation is not None
                    else False
                )
            )
            await asyncio.shield(run_task)
            raise
        finally:
            if force_forwarder is not None:
                force_forwarder.cancel()
                await asyncio.gather(force_forwarder, return_exceptions=True)
            await executor.close()

    def _prepared_subflow(self, node: WorkflowNode) -> PreparedSubflow:
        prepared = self._subflows.get(node.id)
        if prepared is None:
            raise NodeExecutionError(
                code="SUBFLOW_SNAPSHOT_MISSING",
                message=f"节点 {node.name} 缺少固定子流程快照",
            )
        return prepared

    def _prepared_data_node(self, node: WorkflowNode) -> PreparedDataNode:
        prepared = self._data_nodes.get(node.id)
        if prepared is None:
            raise NodeExecutionError(
                code="DATA_NODE_SNAPSHOT_MISSING",
                message=f"节点 {node.name} 缺少固定 Credential 快照",
            )
        return prepared


def _require_preview_for_each_request_reservation(
    prepared: PreparedSubflow,
    request_budget: RequestBudget | None,
    *,
    checkpoint_scope: tuple[str, ...] = (),
    checkpoint_records: dict[str, NodeRunRecord] | None = None,
) -> None:
    reservation = prepared.snapshot.get("preview_request_reservation")
    if not isinstance(reservation, int) or reservation <= 0 or request_budget is None:
        return
    remaining_reservation = _remaining_preview_request_reservation(
        prepared,
        reservation,
        checkpoint_scope,
        checkpoint_records or {},
    )
    if not request_budget.can_claim(remaining_reservation):
        raise NodeExecutionError(
            code="PREVIEW_REQUEST_BUDGET_EXHAUSTED",
            message="Sandbox Preview 剩余请求预算不足以安全执行下一次循环及其 Cleanup",
        )


def _remaining_preview_request_reservation(
    prepared: PreparedSubflow,
    reservation: int,
    checkpoint_scope: tuple[str, ...],
    checkpoint_records: dict[str, NodeRunRecord],
) -> int:
    completed_reservation = 0
    nodes = {node.id: node for node in prepared.definition.nodes}
    for record in _nested_resume_records(
        prepared.definition,
        checkpoint_scope,
        checkpoint_records,
    ):
        resumed_node = nodes[record.node_id]
        maximum_attempts = _preview_node_request_attempts(resumed_node)
        if maximum_attempts == 0:
            continue
        completed_reservation += (
            maximum_attempts
            if record.status in {NodeStatus.PASSED, NodeStatus.SKIPPED}
            else min(record.attempts, maximum_attempts)
        )
    for node_id, subflow in prepared.subflows.items():
        subflow_node = nodes.get(node_id)
        if subflow_node is None or isinstance(parse_node_config(subflow_node), ForEachNodeConfig):
            continue
        nested_reservation = subflow.snapshot.get("preview_request_reservation")
        if not isinstance(nested_reservation, int) or nested_reservation <= 0:
            continue
        nested_remaining = _remaining_preview_request_reservation(
            subflow,
            nested_reservation,
            _nested_scope(checkpoint_scope, "subflow", node_id),
            checkpoint_records,
        )
        completed_reservation += nested_reservation - nested_remaining
    return max(reservation - completed_reservation, 0)


def _preview_node_request_attempts(node: WorkflowNode) -> int:
    if not node_type_consumes_request(node.effective_type):
        return 0
    if node.phase is WorkflowPhase.CLEANUP:
        return node.cleanup_retry_budget + 1
    config = parse_node_config(node)
    return config.max_retries + 1 if isinstance(config, ApiNodeConfig) else 1


def _subflow_output(prepared: PreparedSubflow, result: WorkflowRunResult) -> dict[str, JsonValue]:
    return {
        "workflow_id": str(prepared.workflow_id),
        "workflow_version": prepared.workflow_version,
        "fingerprint": prepared.fingerprint,
        "status": result.status.value,
        "nodes": [
            {
                "node_id": record.node_id,
                "node_type": record.node_type.value,
                "name": record.name,
                "status": record.status.value,
                "attempts": record.attempts,
                "output": record.output,
                "error_code": record.error_code,
                "error_message": record.error_message,
            }
            for record in result.records
        ],
        "context": result.context,
    }


def _nested_scope(
    parent: tuple[str, ...],
    kind: str,
    node_id: str,
    *,
    index: int | None = None,
) -> tuple[str, ...]:
    segment = (kind, node_id) if index is None else (kind, node_id, str(index))
    return (*parent, *segment)


def _nested_checkpoint_id(scope: tuple[str, ...], node_id: str) -> str:
    encoded = json.dumps((*scope, node_id), ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    return f"{NESTED_CHECKPOINT_PREFIX}{digest}"


def _nested_resume_records(
    definition: WorkflowDefinition,
    scope: tuple[str, ...],
    records: dict[str, NodeRunRecord],
) -> tuple[NodeRunRecord, ...]:
    restored: list[NodeRunRecord] = []
    for node in definition.nodes:
        checkpoint = records.get(_nested_checkpoint_id(scope, node.id))
        if checkpoint is not None:
            restored.append(
                replace(
                    checkpoint,
                    node_id=node.id,
                    node_type=node.type,
                    phase=node.phase,
                    best_effort=node.best_effort,
                )
            )
    return tuple(restored)


def _checkpoint_record(update: NodeStatusUpdate) -> NodeRunRecord:
    result = update.result or NodeResult(status=NodeStatus.CANCELLED)
    return NodeRunRecord(
        node_id=update.node_id,
        node_type=update.node_type,
        name=update.name,
        status=update.status,
        attempts=update.attempts,
        output=result.output,
        result=result,
        error_code=update.error_code,
        error_message=update.error_message,
        started_at=update.started_at,
        completed_at=update.occurred_at,
        input_hash=update.input_hash,
        phase=update.phase,
        best_effort=update.best_effort,
    )


async def _forward_force_cancellation(
    parent: CancellationToken,
    nested: CancellationToken,
) -> None:
    await parent.wait(force_only=True)
    nested.cancel(force=True)


async def _collect_for_each_tasks(
    tasks: list[asyncio.Task[dict[str, JsonValue]]],
    *,
    fail_fast: bool,
) -> list[dict[str, JsonValue]]:
    completed: list[dict[str, JsonValue]] = []
    try:
        for finished in asyncio.as_completed(tasks):
            item_result = await finished
            completed.append(item_result)
            if fail_fast and _for_each_failed([item_result]):
                break
    finally:
        for pending in tasks:
            if not pending.done():
                pending.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    completed.sort(key=lambda item: cast(int, item["index"]))
    return completed


def _for_each_failed(items: list[dict[str, JsonValue]]) -> bool:
    return any(
        isinstance(item["result"], dict) and item["result"].get("status") != "passed"
        for item in items
    )


def _for_each_output(
    config: ForEachNodeConfig,
    items: list[JsonValue],
    completed: list[dict[str, JsonValue]],
) -> dict[str, JsonValue]:
    return {
        "total": len(items),
        "completed": len(completed),
        "concurrency": config.concurrency,
        "fail_fast": config.fail_fast,
        "items": cast(JsonValue, completed),
    }


def _response_output(response: httpx.Response) -> dict[str, JsonValue]:
    size_bytes = len(response.content)
    if size_bytes > settings.inline_body_limit_bytes:
        raise NodeExecutionError(
            code="WORKFLOW_RESPONSE_TOO_LARGE",
            message="工作流节点响应超过 2 MB 内联上限",
            output={
                "status_code": response.status_code,
                "size_bytes": size_bytes,
            },
        )
    return {
        "status_code": response.status_code,
        # Runtime context keeps the raw response so downstream mappings can consume
        # tokens and cookies. WorkflowService redacts node records and context before
        # either value crosses the persistence boundary.
        "headers": cast(JsonValue, dict(response.headers)),
        "body": _response_body(response),
        "size_bytes": size_bytes,
    }


def _mappings_by_target(
    definition: WorkflowDefinition,
) -> dict[str, tuple[FieldMapping, ...]]:
    grouped: dict[str, list[FieldMapping]] = {}
    for edge in definition.edges:
        if edge.mappings:
            grouped.setdefault(edge.target, []).extend(edge.mappings)
    return {node_id: tuple(items) for node_id, items in grouped.items()}


def _apply_mappings(
    request: PreparedRequest,
    mappings: tuple[ResolvedFieldMapping, ...],
    context: ExecutionContext,
) -> tuple[PreparedRequest, list[NodeInputMapping]]:
    changed = request
    trace: list[NodeInputMapping] = []
    for mapping in mappings:
        changed = _apply_request_mapping(changed, mapping)
        if mapping.location is MappingTargetLocation.VARIABLE:
            context.record_variable(
                mapping.key,
                mapping.value,
                node_id=mapping.source_node_id,
                path=mapping.source_path,
            )
        trace.append(
            NodeInputMapping(
                source_node_id=mapping.source_node_id,
                source_path=mapping.source_path,
                target_location=mapping.location.value,
                target_key=mapping.key,
                value=_redacted_mapping_value(mapping),
            )
        )
    return changed, trace


def _apply_redacted_mappings(
    request: PreparedRequest,
    mappings: tuple[ResolvedFieldMapping, ...],
) -> PreparedRequest:
    changed = request
    for mapping in mappings:
        safe_mapping = replace(mapping, value=_redacted_mapping_value(mapping))
        changed = _apply_request_mapping(changed, safe_mapping)
    return changed


def _apply_request_mapping(
    request: PreparedRequest,
    mapping: ResolvedFieldMapping,
) -> PreparedRequest:
    if mapping.location is MappingTargetLocation.QUERY:
        return replace(request, url=_set_query(request.url, mapping.key, mapping.value))
    if mapping.location is MappingTargetLocation.HEADER:
        return replace(
            request,
            headers=_set_header(request.headers, mapping.key, mapping.value),
        )
    if mapping.location is MappingTargetLocation.BODY:
        return replace(request, body=_set_body(request.body, mapping.key, mapping.value))
    return request


def _redacted_mapping_value(mapping: ResolvedFieldMapping) -> JsonValue:
    safe = redact({mapping.key: mapping.value})
    return cast(JsonValue, safe[mapping.key])


def _record_http_observation(
    context: ExecutionContext,
    *,
    node_id: str,
    attempt: int,
    request: PreparedRequest,
    mappings: list[NodeInputMapping],
    started_at: datetime,
    started: float,
    response: httpx.Response | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    context.record_observation(
        node_id,
        NodeObservation(
            attempt=attempt,
            request=_http_request_snapshot(request),
            response=_http_response_snapshot(response) if response is not None else None,
            mappings=tuple(mappings),
            duration_ms=(perf_counter() - started) * 1000,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            error_code=error_code,
            error_message=error_message,
        ),
    )


def _http_request_snapshot(request: PreparedRequest) -> HttpRequestSnapshot:
    service_key = request.target_snapshot.get("service_key")
    endpoint_variant = request.target_snapshot.get("endpoint_variant")
    return HttpRequestSnapshot(
        method=request.method.value,
        url=_redact_request_url(request.url),
        headers=cast(
            dict[str, str],
            redact({item.name: item.value for item in request.headers}),
        ),
        body=cast(JsonValue, redact(request.body)),
        service_key=service_key if isinstance(service_key, str) else None,
        endpoint_variant=endpoint_variant if isinstance(endpoint_variant, str) else None,
    )


def _http_response_snapshot(response: httpx.Response) -> HttpResponseSnapshot:
    size_bytes = len(response.content)
    body = _response_body(response) if size_bytes <= settings.inline_body_limit_bytes else None
    return HttpResponseSnapshot(
        status_code=response.status_code,
        headers=_redact_response_headers(dict(response.headers)),
        body=cast(JsonValue, redact(body)),
        size_bytes=size_bytes,
    )


def _set_query(url: str, key: str, value: JsonValue) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[key] = _string_value(value)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _set_header(
    headers: tuple[PreparedHeader, ...], key: str, value: JsonValue
) -> tuple[PreparedHeader, ...]:
    lowered = key.lower()
    remaining = tuple(header for header in headers if header.name.lower() != lowered)
    return (
        *remaining,
        PreparedHeader(name=key, value=_string_value(value), source=HeaderScope.RUNTIME),
    )


def _set_body(body: JsonValue, path: str, value: JsonValue) -> JsonValue:
    if not isinstance(body, dict):
        raise MappingResolutionError(
            code="MAPPING_TARGET_INVALID",
            message="Body 映射要求目标请求体为 JSON 对象",
        )
    root = _copy_json_object(body)
    current = root
    parts = path.split(".")
    for part in parts[:-1]:
        nested = current.get(part)
        if nested is None:
            nested = {}
            current[part] = nested
        if not isinstance(nested, dict):
            raise MappingResolutionError(
                code="MAPPING_TARGET_INVALID",
                message=f"Body 映射路径 {path} 与现有值冲突",
            )
        current = nested
    current[parts[-1]] = value
    return cast(JsonValue, root)


def _copy_json_object(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], json.loads(json.dumps(value)))


def _string_value(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _resolve_data_value(value: JsonValue, context: ExecutionContext) -> JsonValue:
    if isinstance(value, dict):
        return {name: _resolve_data_value(item, context) for name, item in value.items()}
    if isinstance(value, list):
        return [_resolve_data_value(item, context) for item in value]
    if not isinstance(value, str):
        return value
    match = _DATA_VARIABLE.fullmatch(value)
    if match is None:
        return value
    variables = context.resolved_variables()
    name = match.group(1)
    if name not in variables:
        raise NodeExecutionError(
            code="DATA_NODE_VARIABLE_MISSING",
            message=f"数据节点变量不存在: {name}",
        )
    return variables[name]


def _data_argument(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
