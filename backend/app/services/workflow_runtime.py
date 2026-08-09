import json
from dataclasses import dataclass, replace
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import JsonValue

from app.core.config import settings
from app.core.logging import redact
from app.domain.api_assets import BodyKind
from app.domain.scopes import HeaderScope
from app.engine.contracts import (
    FieldMapping,
    MappingTargetLocation,
    NodeType,
    RetryCategory,
    WorkflowDefinition,
    WorkflowNode,
)
from app.engine.control_nodes import execute_control_node
from app.engine.mappings import MappingResolutionError, ResolvedFieldMapping, resolve_field_mappings
from app.engine.scheduler import ExecutionContext, NodeExecutionError
from app.services.api_assets import PreparedHeader, PreparedRequest
from app.services.executions import (
    PreparedMultipart,
    _redact_response_headers,
    _response_body,
    _send_request,
)


@dataclass(frozen=True, slots=True)
class PreparedWorkflowRequest:
    request: PreparedRequest
    body_kind: BodyKind
    multipart: PreparedMultipart | None


class WorkflowNodeExecutor:
    def __init__(
        self,
        client: httpx.AsyncClient,
        requests: dict[str, PreparedWorkflowRequest],
        definition: WorkflowDefinition,
    ) -> None:
        self._client = client
        self._requests = requests
        self._mappings = _mappings_by_target(definition)

    async def execute(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        if node.type is not NodeType.API:
            return await execute_control_node(node, context)
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
        "headers": cast(JsonValue, _redact_response_headers(dict(response.headers))),
        "body": cast(JsonValue, redact(_response_body(response))),
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
