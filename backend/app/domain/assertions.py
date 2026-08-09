import re
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

import jmespath
from jmespath.exceptions import JMESPathError
from jsonpath_ng.exceptions import JSONPathError
from jsonpath_ng.ext import parse as parse_jsonpath
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app.domain.api_assets import JsonValue


class AssertionKind(StrEnum):
    STATUS_CODE = "status_code"
    RESPONSE_TIME = "response_time"
    HEADER = "header"
    JSONPATH = "jsonpath"
    JMESPATH = "jmespath"
    JSON_SCHEMA = "json_schema"
    FILE_SIZE = "file_size"
    FILE_SHA256 = "file_sha256"
    CONTENT_TYPE = "content_type"


class ComparisonOperator(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    EXISTS = "exists"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    MATCHES = "matches"


@dataclass(frozen=True, slots=True)
class AssertionSpec:
    kind: AssertionKind
    operator: ComparisonOperator = ComparisonOperator.EQUALS
    target: str | None = None
    expected: JsonValue = None


@dataclass(frozen=True, slots=True)
class ResponseSnapshot:
    status_code: int
    elapsed_ms: float
    headers: dict[str, str]
    body: JsonValue
    content_size: int = 0
    content_sha256: str = ""
    content_type: str = ""


@dataclass(frozen=True, slots=True)
class AssertionOutcome:
    spec: AssertionSpec
    actual: JsonValue
    passed: bool
    message: str


def evaluate_assertions(
    snapshot: ResponseSnapshot, specs: tuple[AssertionSpec, ...]
) -> tuple[AssertionOutcome, ...]:
    return tuple(evaluate_assertion(snapshot, spec) for spec in specs)


def evaluate_assertion(snapshot: ResponseSnapshot, spec: AssertionSpec) -> AssertionOutcome:
    try:
        actual = _extract_actual(snapshot, spec)
        if spec.kind is AssertionKind.JSON_SCHEMA:
            return _evaluate_schema(spec, actual)
        passed = _compare(actual, spec.expected, spec.operator)
        message = "断言通过" if passed else f"实际值 {actual!r} 不满足 {spec.operator.value}"
        return AssertionOutcome(spec=spec, actual=actual, passed=passed, message=message)
    except (JSONPathError, JMESPathError, SchemaError, KeyError, TypeError, ValueError) as error:
        return AssertionOutcome(
            spec=spec,
            actual=None,
            passed=False,
            message=f"断言配置或取值失败: {error}",
        )


def _extract_actual(snapshot: ResponseSnapshot, spec: AssertionSpec) -> JsonValue:
    if spec.kind is AssertionKind.STATUS_CODE:
        return snapshot.status_code
    if spec.kind is AssertionKind.RESPONSE_TIME:
        return snapshot.elapsed_ms
    if spec.kind is AssertionKind.HEADER:
        if not spec.target:
            raise ValueError("Header 断言缺少 target")
        headers = {name.lower(): value for name, value in snapshot.headers.items()}
        return headers.get(spec.target.lower())
    if spec.kind in {AssertionKind.JSONPATH, AssertionKind.JMESPATH}:
        return _extract_body_value(snapshot.body, spec)
    return _extract_file_value(snapshot, spec.kind)


def _extract_body_value(body: JsonValue, spec: AssertionSpec) -> JsonValue:
    if spec.kind is AssertionKind.JSONPATH:
        if not spec.target:
            raise ValueError("JSONPath 断言缺少表达式")
        matches = [match.value for match in parse_jsonpath(spec.target).find(body)]
        if not matches:
            return None
        return matches[0] if len(matches) == 1 else matches
    if not spec.target:
        raise ValueError("JMESPath 断言缺少表达式")
    return cast(JsonValue, jmespath.search(spec.target, body))


def _extract_file_value(snapshot: ResponseSnapshot, kind: AssertionKind) -> JsonValue:
    if kind is AssertionKind.FILE_SIZE:
        return snapshot.content_size
    if kind is AssertionKind.FILE_SHA256:
        return snapshot.content_sha256
    if kind is AssertionKind.CONTENT_TYPE:
        return snapshot.content_type
    return snapshot.body


def _evaluate_schema(spec: AssertionSpec, actual: JsonValue) -> AssertionOutcome:
    if not isinstance(spec.expected, dict):
        raise ValueError("Schema 断言 expected 必须是对象")
    errors = sorted(Draft202012Validator(spec.expected).iter_errors(actual), key=str)
    if not errors:
        return AssertionOutcome(spec=spec, actual=actual, passed=True, message="Schema 断言通过")
    message = "; ".join(error.message for error in errors[:3])
    return AssertionOutcome(spec=spec, actual=actual, passed=False, message=message)


def _compare(actual: JsonValue, expected: JsonValue, operator: ComparisonOperator) -> bool:
    if operator is ComparisonOperator.EXISTS:
        return actual is not None
    if operator is ComparisonOperator.EQUALS:
        return actual == expected
    if operator is ComparisonOperator.NOT_EQUALS:
        return actual != expected
    if operator is ComparisonOperator.CONTAINS:
        if isinstance(actual, (str, list, dict)):
            return expected in actual
        return False
    if operator is ComparisonOperator.MATCHES:
        return (
            isinstance(actual, str)
            and isinstance(expected, str)
            and re.search(expected, actual) is not None
        )
    return _compare_numbers(actual, expected, operator)


def _compare_numbers(
    actual: JsonValue,
    expected: JsonValue,
    operator: ComparisonOperator,
) -> bool:
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return False
    if not isinstance(expected, (int, float)) or isinstance(expected, bool):
        return False
    if operator is ComparisonOperator.LESS_THAN:
        return actual < expected
    if operator is ComparisonOperator.LESS_THAN_OR_EQUAL:
        return actual <= expected
    if operator is ComparisonOperator.GREATER_THAN:
        return actual > expected
    return actual >= expected
