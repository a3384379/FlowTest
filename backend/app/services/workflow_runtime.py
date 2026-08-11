import asyncio
import json
import re
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

import httpx
from pydantic import JsonValue

from app.core.config import settings
from app.core.errors import AppError
from app.domain.api_assets import BodyKind
from app.domain.expressions import SafeExpressionError, evaluate_bounded_array
from app.domain.network import OutboundNetworkPolicy
from app.domain.scopes import HeaderScope
from app.engine.capabilities import legacy_node_adapter
from app.engine.contracts import (
    FieldMapping,
    ForEachNodeConfig,
    MappingTargetLocation,
    NodeType,
    RedisNodeConfig,
    RetryCategory,
    SqlNodeConfig,
    SubFlowNodeConfig,
    WorkflowDefinition,
    WorkflowNode,
    parse_node_config,
)
from app.engine.control_nodes import execute_control_node
from app.engine.mappings import MappingResolutionError, ResolvedFieldMapping, resolve_field_mappings
from app.engine.node_sdk import NodeHandlerRegistration, NodeHandlerRegistry
from app.engine.scheduler import (
    ExecutionContext,
    NodeExecutionError,
    WorkflowRunResult,
    WorkflowScheduler,
)
from app.services.api_assets import PreparedHeader, PreparedRequest
from app.services.data_nodes import (
    DataNodeRunner,
    InfrastructureDataNodeRunner,
    PreparedDataNode,
)
from app.services.executions import (
    PreparedMultipart,
    _response_body,
    _send_request,
)
from app.services.outbound import OutboundRequestGuard, outbound_request_guard

_DATA_VARIABLE = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}$")


@dataclass(frozen=True, slots=True)
class PreparedWorkflowRequest:
    request: PreparedRequest
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
    ) -> None:
        self._client = client
        self._requests = requests
        self._mappings = _mappings_by_target(definition)
        self._network_policy = network_policy
        self._subflows = subflows or {}
        self._data_nodes = data_nodes or {}
        self._outbound_guard = outbound_guard
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

    async def _execute_capability(
        self,
        node: WorkflowNode,
        context: ExecutionContext,
    ) -> JsonValue:
        try:
            legacy_node = legacy_node_adapter.as_legacy_node(node)
        except ValueError as error:
            raise NodeExecutionError(
                code="CAPABILITY_RUNTIME_UNAVAILABLE",
                message="当前 Runner 不支持该能力版本",
            ) from error
        return await self._handlers.execute(legacy_node, context)

    async def _execute_api(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        prepared = self._requests[node.id]
        try:
            request, mapping_trace = _apply_mappings(
                prepared.request,
                resolve_field_mappings(self._mappings.get(node.id, ()), context),
                context,
            )
        except MappingResolutionError as error:
            raise NodeExecutionError(code=error.code, message=error.message) from error
        try:
            await self._outbound_guard.enforce(request.url, self._network_policy)
        except AppError as error:
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
            raise NodeExecutionError(
                code="NETWORK_TIMEOUT",
                message="目标接口请求超时",
                category=RetryCategory.NETWORK_ERROR,
            ) from error
        except httpx.HTTPError as error:
            raise NodeExecutionError(
                code="NETWORK_ERROR",
                message="无法连接目标接口",
                category=RetryCategory.NETWORK_ERROR,
            ) from error

        output = _response_output(response)
        output["input_mappings"] = cast(JsonValue, mapping_trace)
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
        result = await self._run_subflow(prepared, context.resolved_variables())
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
        completed = await self._run_for_each_items(prepared, config, context, items)
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
        prepared: PreparedSubflow,
        config: ForEachNodeConfig,
        context: ExecutionContext,
        items: list[JsonValue],
    ) -> list[dict[str, JsonValue]]:
        semaphore = asyncio.Semaphore(config.concurrency)
        tasks = [
            asyncio.create_task(
                self._run_for_each_item(prepared, config, context, semaphore, index, item)
            )
            for index, item in enumerate(items)
        ]
        return await _collect_for_each_tasks(tasks, fail_fast=config.fail_fast)

    async def _run_for_each_item(
        self,
        prepared: PreparedSubflow,
        config: ForEachNodeConfig,
        context: ExecutionContext,
        semaphore: asyncio.Semaphore,
        index: int,
        item: JsonValue,
    ) -> dict[str, JsonValue]:
        async with semaphore:
            variables = {
                **context.resolved_variables(),
                config.item_variable: item,
                config.index_variable: index,
            }
            result = await self._run_subflow(prepared, variables)
            return {
                "index": index,
                "item": item,
                "result": _subflow_output(prepared, result),
            }

    async def _run_subflow(
        self,
        prepared: PreparedSubflow,
        runtime_variables: dict[str, JsonValue],
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
        )
        return await WorkflowScheduler(executor).run(
            prepared.definition,
            context=ExecutionContext(
                workflow_variables=dict(prepared.definition.variables),
                runtime_variables=runtime_variables,
            ),
        )

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
) -> tuple[PreparedRequest, list[dict[str, str]]]:
    changed = request
    trace: list[dict[str, str]] = []
    for mapping in mappings:
        if mapping.location is MappingTargetLocation.QUERY:
            changed = replace(changed, url=_set_query(changed.url, mapping.key, mapping.value))
        elif mapping.location is MappingTargetLocation.HEADER:
            changed = replace(
                changed,
                headers=_set_header(changed.headers, mapping.key, mapping.value),
            )
        elif mapping.location is MappingTargetLocation.BODY:
            changed = replace(changed, body=_set_body(changed.body, mapping.key, mapping.value))
        else:
            context.record_variable(
                mapping.key,
                mapping.value,
                node_id=mapping.source_node_id,
                path=mapping.source_path,
            )
        trace.append(
            {
                "source_node_id": mapping.source_node_id,
                "source_path": mapping.source_path,
                "target_location": mapping.location.value,
                "target_key": mapping.key,
            }
        )
    return changed, trace


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
