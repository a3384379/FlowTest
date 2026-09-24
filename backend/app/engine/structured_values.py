"""Typed value-source resolution shared by structured controls."""

from typing import cast

from pydantic import JsonValue

from app.engine.contracts import (
    LiteralValueSource,
    NodeOutputValueSource,
    ValueSource,
    VariableValueSource,
)
from app.engine.scheduler import ExecutionContext, NodeExecutionError


def resolve_value(source: ValueSource, context: ExecutionContext) -> JsonValue:
    if isinstance(source, LiteralValueSource):
        return source.value
    if isinstance(source, NodeOutputValueSource):
        if not context.has_output(source.node_id):
            raise NodeExecutionError(
                code="VALUE_SOURCE_MISSING",
                message=f"节点 {source.node_id} 在当前作用域中没有已完成输出",
            )
        return _path_value(context.output_of(source.node_id), source.path)
    if isinstance(source, VariableValueSource):
        snapshot = context.snapshot()
        extracted = snapshot["extracted_variables"]
        scopes: dict[str, dict[str, JsonValue]] = {
            "runtime": context.runtime_variables,
            "workflow": context.workflow_variables,
            "input": context.input_variables,
            "loop": context.loop_variables,
            "state": context.state_variables,
            "error": context.error_variables,
            "local": cast(dict[str, JsonValue], extracted),
        }
        return _path_value(scopes[source.scope], source.path)
    raise NodeExecutionError(code="INVALID_VALUE_SOURCE", message="不支持的取值来源")


def _path_value(value: JsonValue, path: tuple[str | int, ...]) -> JsonValue:
    current = value
    for segment in path:
        current = _path_segment(current, segment)
    return current


def _path_segment(value: JsonValue, segment: str | int) -> JsonValue:
    if isinstance(value, dict) and isinstance(segment, str) and segment in value:
        return value[segment]
    if isinstance(value, list) and isinstance(segment, int) and 0 <= segment < len(value):
        return value[segment]
    raise NodeExecutionError(code="VALUE_SOURCE_MISSING", message="取值路径在当前作用域中不存在")
