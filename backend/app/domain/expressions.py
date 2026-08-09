from dataclasses import dataclass
from typing import cast

import jmespath
from jmespath.exceptions import JMESPathError
from pydantic import JsonValue


@dataclass(frozen=True, slots=True)
class SafeExpressionError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def validate_safe_expression(expression: str) -> None:
    try:
        jmespath.compile(expression)
    except JMESPathError as error:
        raise SafeExpressionError(
            code="INVALID_SAFE_EXPRESSION",
            message="受限表达式不是有效的 JMESPath",
        ) from error


def evaluate_safe_expression(expression: str, source: JsonValue) -> JsonValue:
    try:
        return cast(JsonValue, jmespath.search(expression, source))
    except JMESPathError as error:
        raise SafeExpressionError(
            code="INVALID_SAFE_EXPRESSION",
            message="受限表达式执行失败",
        ) from error


def evaluate_bounded_array(
    expression: str,
    source: JsonValue,
    *,
    maximum_items: int = 1000,
) -> list[JsonValue]:
    value = evaluate_safe_expression(expression, source)
    if not isinstance(value, list):
        raise SafeExpressionError(
            code="FOR_EACH_SOURCE_NOT_ARRAY",
            message="ForEach 表达式必须返回数组",
        )
    if len(value) > maximum_items:
        raise SafeExpressionError(
            code="FOR_EACH_LIMIT_EXCEEDED",
            message=f"ForEach 最多处理 {maximum_items} 项",
        )
    return value
