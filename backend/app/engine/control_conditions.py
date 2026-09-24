"""Bounded, strictly typed predicates for structured workflow controls."""

from typing import cast

from pydantic import JsonValue

from app.engine.contracts import ConditionExpression, ValueSource
from app.engine.scheduler import ExecutionContext, NodeExecutionError
from app.engine.structured_values import resolve_value


def evaluate_condition(
    expression: ConditionExpression, context: ExecutionContext
) -> tuple[bool, list[dict[str, JsonValue]]]:
    trace: list[dict[str, JsonValue]] = []
    result = _evaluate(expression, context, trace)
    return result, trace


def _evaluate(
    expression: ConditionExpression,
    context: ExecutionContext,
    trace: list[dict[str, JsonValue]],
) -> bool:
    if expression.kind == "compare":
        return _compare(expression, context, trace)
    if expression.kind == "not":
        if expression.condition is None:
            raise NodeExecutionError(code="INVALID_CONDITION", message="条件缺少子表达式")
        return not _evaluate(expression.condition, context, trace)
    children = expression.conditions or []
    for index, child in enumerate(children):
        result = _evaluate(child, context, trace)
        if (expression.kind == "all" and not result) or (expression.kind == "any" and result):
            trace.extend(
                {"kind": "short_circuit", "result": "not_evaluated"} for _ in children[index + 1 :]
            )
            return result
    return expression.kind == "all"


def _compare(
    expression: ConditionExpression,
    context: ExecutionContext,
    trace: list[dict[str, JsonValue]],
) -> bool:
    if expression.left is None:
        raise NodeExecutionError(code="INVALID_CONDITION", message="条件缺少左侧来源")
    left_source = expression.left
    operator = expression.operator
    if operator is None:
        raise NodeExecutionError(code="INVALID_CONDITION", message="条件缺少运算符")
    exists, actual = _resolve_optional(left_source, context)
    if operator in {"exists", "not_exists"}:
        result = exists if operator == "exists" else not exists
    else:
        if not exists:
            raise NodeExecutionError(
                code="VALUE_SOURCE_MISSING",
                message="条件来源在当前作用域中不存在",
            )
        expected = resolve_value(expression.right, context) if expression.right else None
        result = _apply_operator(operator, actual, expected)
    trace.append(
        {
            "kind": "compare",
            "operator": operator,
            "actual": actual if exists else None,
            "exists": exists,
            "expected": resolve_value(expression.right, context) if expression.right else None,
            "result": result,
        }
    )
    return result


def _resolve_optional(source: ValueSource, context: ExecutionContext) -> tuple[bool, JsonValue]:
    try:
        return True, resolve_value(source, context)
    except NodeExecutionError as error:
        if error.code != "VALUE_SOURCE_MISSING":
            raise
        return False, None


def _apply_operator(operator: str, actual: JsonValue, expected: JsonValue) -> bool:
    if operator == "equals":
        return strict_equal(actual, expected)
    if operator == "not_equals":
        return not strict_equal(actual, expected)
    if operator in {"is_null", "not_null"}:
        return (actual is None) == (operator == "is_null")
    if operator in {"is_empty", "not_empty"}:
        length = _length(actual)
        return (length == 0) == (operator == "is_empty")
    if operator.startswith("length_"):
        left = _length(actual)
        right = _number(expected)
        return _numeric_compare(operator[7:], left, right)
    if operator in {"gt", "gte", "lt", "lte"}:
        return _numeric_compare(operator, _number(actual), _number(expected))
    if operator == "contains":
        return _contains(actual, expected)
    if operator == "in":
        return _contains(expected, actual)
    raise NodeExecutionError(code="INVALID_CONDITION", message="不支持的条件运算符")


def strict_equal(left: JsonValue, right: JsonValue) -> bool:
    if _is_number(left) and _is_number(right):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            strict_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            strict_equal(left[key], right[key]) for key in left
        )
    return left == right


def _is_number(value: JsonValue) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number(value: JsonValue) -> int | float:
    if not _is_number(value):
        raise NodeExecutionError(code="CONDITION_TYPE_MISMATCH", message="条件需要数值")
    return cast(int | float, value)


def _length(value: JsonValue) -> int:
    if not isinstance(value, (str, list, dict)):
        raise NodeExecutionError(code="CONDITION_TYPE_MISMATCH", message="条件需要可计算长度的值")
    return len(value)


def _numeric_compare(operator: str, left: int | float, right: int | float) -> bool:
    return {
        "gt": left > right,
        "gte": left >= right,
        "lt": left < right,
        "lte": left <= right,
        "equals": left == right,
    }[operator]


def _contains(container: JsonValue, item: JsonValue) -> bool:
    if isinstance(container, str) and isinstance(item, str):
        return item in container
    if isinstance(container, list):
        return any(strict_equal(value, item) for value in container)
    if isinstance(container, dict) and isinstance(item, str):
        return item in container
    raise NodeExecutionError(code="CONDITION_TYPE_MISMATCH", message="包含比较的类型不兼容")
