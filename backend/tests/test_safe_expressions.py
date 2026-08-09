import pytest

from app.domain.expressions import (
    SafeExpressionError,
    evaluate_bounded_array,
    evaluate_safe_expression,
    validate_safe_expression,
)


def test_safe_expression_uses_jmespath_without_script_execution() -> None:
    source = {"users": [{"id": 1, "enabled": True}, {"id": 2, "enabled": False}]}

    validate_safe_expression("users[?enabled].id")

    assert evaluate_safe_expression("users[?enabled].id", source) == [1]
    assert evaluate_bounded_array("users", source) == source["users"]


def test_safe_expression_rejects_invalid_non_array_and_oversized_results() -> None:
    with pytest.raises(SafeExpressionError) as invalid:
        validate_safe_expression("[")
    assert invalid.value.code == "INVALID_SAFE_EXPRESSION"

    with pytest.raises(SafeExpressionError) as scalar:
        evaluate_bounded_array("value", {"value": 1})
    assert scalar.value.code == "FOR_EACH_SOURCE_NOT_ARRAY"

    with pytest.raises(SafeExpressionError) as oversized:
        evaluate_bounded_array("items", {"items": list(range(4))}, maximum_items=3)
    assert oversized.value.code == "FOR_EACH_LIMIT_EXCEEDED"
