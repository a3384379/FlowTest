import asyncio
from typing import cast

import jmespath
from jmespath.exceptions import JMESPathError
from pydantic import JsonValue

from app.domain.assertions import compare_values
from app.engine.contracts import (
    AssertNodeConfig,
    ConditionNodeConfig,
    DatasetNodeConfig,
    DelayNodeConfig,
    ExtractNodeConfig,
    NodeType,
    WorkflowNode,
    parse_node_config,
)
from app.engine.scheduler import ExecutionContext, NodeExecutionError


async def execute_control_node(node: WorkflowNode, context: ExecutionContext) -> JsonValue:
    if node.type is NodeType.START:
        return {"variables": context.resolved_variables()}
    if node.type is NodeType.END:
        return None
    config = parse_node_config(node)
    try:
        if isinstance(config, ExtractNodeConfig):
            return _extract(config, context)
        if isinstance(config, AssertNodeConfig):
            return _assert(config, context)
        if isinstance(config, ConditionNodeConfig):
            return _condition(config, context)
        if isinstance(config, DelayNodeConfig):
            await asyncio.sleep(config.seconds)
            return {"seconds": config.seconds}
        if isinstance(config, DatasetNodeConfig):
            return {"row": dict(context.dataset_variables)}
    except JMESPathError as error:
        raise NodeExecutionError(
            code="INVALID_JMESPATH",
            message=f"节点 {node.name} 的 JMESPath 表达式无效",
        ) from error
    raise NodeExecutionError(
        code="UNSUPPORTED_NODE_TYPE",
        message=f"当前版本不支持 {node.type.value} 节点",
    )


def _extract(config: ExtractNodeConfig, context: ExecutionContext) -> JsonValue:
    actual = _search(context, config.source_node_id, config.expression)
    if config.required and actual is None:
        raise NodeExecutionError(
            code="EXTRACT_VALUE_MISSING",
            message=f"提取表达式 {config.expression} 未找到值",
        )
    context.record_variable(
        config.variable,
        actual,
        node_id=config.source_node_id,
        path=config.expression,
    )
    return {
        "variable": config.variable,
        "value": actual,
        "source_node_id": config.source_node_id,
        "expression": config.expression,
    }


def _assert(config: AssertNodeConfig, context: ExecutionContext) -> JsonValue:
    actual = _search(context, config.source_node_id, config.expression)
    output: dict[str, JsonValue] = {
        "passed": compare_values(actual, config.expected, config.operator),
        "actual": actual,
        "expected": config.expected,
        "operator": config.operator.value,
        "source_node_id": config.source_node_id,
        "expression": config.expression,
    }
    if output["passed"] is not True:
        raise NodeExecutionError(
            code="WORKFLOW_ASSERTION_FAILED",
            message=f"实际值不满足 {config.operator.value} 断言",
            output=output,
        )
    return output


def _condition(config: ConditionNodeConfig, context: ExecutionContext) -> JsonValue:
    actual = _search(context, config.source_node_id, config.expression)
    return {
        "matched": compare_values(actual, config.expected, config.operator),
        "actual": actual,
        "expected": config.expected,
        "operator": config.operator.value,
        "source_node_id": config.source_node_id,
        "expression": config.expression,
    }


def _search(context: ExecutionContext, source_node_id: str, expression: str) -> JsonValue:
    source = context.output_of(source_node_id)
    return cast(JsonValue, jmespath.search(expression, source))
