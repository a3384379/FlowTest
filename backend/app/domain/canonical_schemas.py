"""Strict, bounded validation for persistable canonical JSON Schemas."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from app.domain.canonical_contracts import looks_sensitive_contract_value

MAX_SCHEMA_DEPTH: Final = 24
MAX_SCHEMA_NODES: Final = 10_000
MAX_SCHEMA_BYTES: Final = 512 * 1024
MAX_PROPERTIES: Final = 500
MAX_PROPERTY_NAME: Final = 160
MAX_COMPOSITION_BRANCHES: Final = 50
MAX_ENUM_VALUES: Final = 500
MAX_TEXT_LENGTH: Final = 4_000
MAX_PATTERN_LENGTH: Final = 500
MAX_FORMAT_LENGTH: Final = 80

_TYPES = frozenset({"null", "boolean", "object", "array", "number", "string", "integer"})
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NESTED_SCHEMA_KEYS = frozenset({"items", "not"})
_BRANCH_KEYS = frozenset({"oneOf", "anyOf", "allOf"})
_NUMERIC_KEYS = frozenset(
    {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}
)
_COUNT_KEYS = frozenset(
    {"minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties"}
)
_BOOLEAN_KEYS = frozenset({"uniqueItems", "nullable", "readOnly", "writeOnly"})
_ALLOWED_KEYS = frozenset(
    {
        "type",
        "format",
        "title",
        "description",
        "required",
        "properties",
        "items",
        "enum",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "additionalProperties",
        "nullable",
        "readOnly",
        "writeOnly",
        "oneOf",
        "anyOf",
        "allOf",
        "not",
        "discriminator",
        "x-flowtest-redacted-enum",
        "example",
        "examples",
        "default",
        "const",
        "x-example",
        "x-examples",
    }
)
_NESTED_QUANTIFIER = re.compile(r"\([^)]*[+*][^)]*\)[+*{]")


@dataclass(frozen=True, slots=True)
class CanonicalSchemaIssue:
    path: str
    keyword: str
    reason: str

    def as_json(self) -> dict[str, str]:
        return {"path": self.path, "keyword": self.keyword, "reason": self.reason}


class CanonicalSchemaValidationError(ValueError):
    """Raised when an untrusted schema cannot enter the canonical contract."""

    def __init__(self, issues: list[CanonicalSchemaIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__(issues[0].reason if issues else "canonical schema is invalid")


class CanonicalSchemaValidator:
    """Validate keyword types, relationships, sensitive values, and complexity."""

    def validate(
        self,
        schema: Mapping[str, object],
        *,
        path: str = "$",
        allow_partial_required: bool = False,
    ) -> None:
        issues = self.issues(
            schema,
            path=path,
            allow_partial_required=allow_partial_required,
        )
        if issues:
            raise CanonicalSchemaValidationError(issues)

    def issues(
        self,
        schema: Mapping[str, object],
        *,
        path: str = "$",
        allow_partial_required: bool = False,
    ) -> list[CanonicalSchemaIssue]:
        try:
            encoded = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return [_issue(path, "$schema", "schema must contain JSON-compatible values")]
        if len(encoded.encode()) > MAX_SCHEMA_BYTES:
            return [_issue(path, "$schema", "schema exceeds the canonical byte budget")]
        state = _ValidationState(allow_partial_required=allow_partial_required)
        _validate_schema(schema, path, 1, state)
        return state.issues


@dataclass(slots=True)
class _ValidationState:
    allow_partial_required: bool
    nodes: int = 0
    issues: list[CanonicalSchemaIssue] = field(default_factory=list)

    def add(self, path: str, keyword: str, reason: str) -> None:
        if len(self.issues) < 100:
            self.issues.append(_issue(path, keyword, reason))


def _validate_schema(
    schema: Mapping[str, object], path: str, depth: int, state: _ValidationState
) -> None:
    state.nodes += 1
    if state.nodes > MAX_SCHEMA_NODES:
        state.add(path, "$schema", "schema exceeds the canonical node budget")
        return
    if depth > MAX_SCHEMA_DEPTH:
        state.add(path, "$schema", "schema exceeds the canonical recursion budget")
        return
    for key in schema:
        if not isinstance(key, str) or key not in _ALLOWED_KEYS:
            state.add(path, str(key), "schema keyword is not allowed")
    _validate_type(schema.get("type"), path, state)
    _validate_numeric(schema, path, state)
    _validate_counts(schema, path, state)
    _validate_booleans(schema, path, state)
    _validate_properties(schema, path, depth, state)
    _validate_required(schema, path, state)
    _validate_nested(schema, path, depth, state)
    _validate_enum(schema, path, state)
    _validate_redacted_enum(schema.get("x-flowtest-redacted-enum"), path, state)
    _validate_text(schema, path, state)
    _validate_discriminator(schema.get("discriminator"), path, state)


def _validate_type(value: object, path: str, state: _ValidationState) -> None:
    if value is None:
        return
    if isinstance(value, str):
        if value not in _TYPES:
            state.add(path, "type", "type must be a supported JSON Schema primitive")
        return
    if isinstance(value, list):
        if not value or not all(isinstance(item, str) and item in _TYPES for item in value):
            state.add(path, "type", "type array must contain supported primitive names")
        elif len(value) != len(set(value)):
            state.add(path, "type", "type array must contain unique values")
        return
    state.add(path, "type", "type must be a string or a unique string array")


def _validate_numeric(schema: Mapping[str, object], path: str, state: _ValidationState) -> None:
    for key in _NUMERIC_KEYS:
        value = schema.get(key)
        if value is None:
            continue
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            state.add(path, key, f"{key} must be a number and must not be boolean")
        elif key == "multipleOf" and value <= 0:
            state.add(path, key, "multipleOf must be greater than zero")
    _validate_numeric_consistency(schema, path, state)


def _validate_numeric_consistency(
    schema: Mapping[str, object], path: str, state: _ValidationState
) -> None:
    lower = _bound(schema, "minimum", "exclusiveMinimum")
    upper = _bound(schema, "maximum", "exclusiveMaximum")
    if lower is None or upper is None:
        return
    lower_value, lower_exclusive = lower
    upper_value, upper_exclusive = upper
    if lower_value > upper_value or (
        lower_value == upper_value and (lower_exclusive or upper_exclusive)
    ):
        state.add(path, "bounds", "numeric constraints are unsatisfiable")


def _bound(
    schema: Mapping[str, object], inclusive: str, exclusive: str
) -> tuple[int | float, bool] | None:
    candidates = [
        (value, key == exclusive)
        for key in (inclusive, exclusive)
        if isinstance((value := schema.get(key)), (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ]
    if not candidates:
        return None
    selector = max if inclusive == "minimum" else min
    boundary = selector(value for value, _ in candidates)
    return boundary, any(value == boundary and is_exclusive for value, is_exclusive in candidates)


def _validate_counts(schema: Mapping[str, object], path: str, state: _ValidationState) -> None:
    for key in _COUNT_KEYS:
        value = schema.get(key)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            state.add(path, key, f"{key} must be a non-negative integer")
    for minimum, maximum in (
        ("minLength", "maxLength"),
        ("minItems", "maxItems"),
        ("minProperties", "maxProperties"),
    ):
        lower = schema.get(minimum)
        upper = schema.get(maximum)
        if isinstance(lower, int) and isinstance(upper, int) and lower > upper:
            state.add(path, maximum, f"{minimum} must not exceed {maximum}")


def _validate_booleans(schema: Mapping[str, object], path: str, state: _ValidationState) -> None:
    for key in _BOOLEAN_KEYS:
        if key in schema and not isinstance(schema[key], bool):
            state.add(path, key, f"{key} must be boolean")


def _validate_properties(
    schema: Mapping[str, object], path: str, depth: int, state: _ValidationState
) -> None:
    value = schema.get("properties")
    if value is None:
        return
    if not isinstance(value, Mapping):
        state.add(path, "properties", "properties must be an object")
        return
    if len(value) > MAX_PROPERTIES:
        state.add(path, "properties", "properties exceeds the canonical property budget")
    for raw_name, child in value.items():
        name = str(raw_name)
        child_path = f"{path}.properties.{name}"
        if (
            not isinstance(raw_name, str)
            or not name
            or len(name) > MAX_PROPERTY_NAME
            or _CONTROL.search(name)
        ):
            state.add(child_path, "properties", "property name is invalid")
            continue
        if not isinstance(child, Mapping):
            state.add(child_path, "properties", "property value must be a schema object")
            continue
        _validate_schema(child, child_path, depth + 1, state)


def _validate_required(schema: Mapping[str, object], path: str, state: _ValidationState) -> None:
    value = schema.get("required")
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        state.add(path, "required", "required must be a unique string array")
        return
    if len(value) != len(set(value)):
        state.add(path, "required", "required names must be unique")
    if any(not item or len(item) > MAX_PROPERTY_NAME or _CONTROL.search(item) for item in value):
        state.add(path, "required", "required names must be safe non-empty property names")
    properties = schema.get("properties")
    if state.allow_partial_required:
        return
    known = set(properties) if isinstance(properties, Mapping) else set()
    if any(item not in known for item in value):
        state.add(path, "required", "required names must exist in properties")


def _validate_nested(
    schema: Mapping[str, object], path: str, depth: int, state: _ValidationState
) -> None:
    for key in _NESTED_SCHEMA_KEYS:
        value = schema.get(key)
        if value is None:
            continue
        if not isinstance(value, Mapping):
            state.add(path, key, f"{key} must be a schema object")
        else:
            _validate_schema(value, f"{path}.{key}", depth + 1, state)
    _validate_additional_properties(schema.get("additionalProperties"), path, depth, state)
    _validate_branches(schema, path, depth, state)


def _validate_additional_properties(
    value: object, path: str, depth: int, state: _ValidationState
) -> None:
    if value is None or isinstance(value, bool):
        return
    if not isinstance(value, Mapping):
        state.add(
            path,
            "additionalProperties",
            "additionalProperties must be boolean or a schema object",
        )
        return
    _validate_schema(value, f"{path}.additionalProperties", depth + 1, state)


def _validate_branches(
    schema: Mapping[str, object], path: str, depth: int, state: _ValidationState
) -> None:
    for key in _BRANCH_KEYS:
        branches = schema.get(key)
        if branches is None:
            continue
        if not isinstance(branches, list) or not branches:
            state.add(path, key, f"{key} must be a non-empty schema array")
            continue
        if len(branches) > MAX_COMPOSITION_BRANCHES:
            state.add(path, key, f"{key} exceeds the composition branch budget")
        for index, branch in enumerate(branches):
            if not isinstance(branch, Mapping):
                state.add(path, key, f"{key} entries must be schema objects")
            else:
                _validate_schema(branch, f"{path}.{key}[{index}]", depth + 1, state)


def _validate_enum(schema: Mapping[str, object], path: str, state: _ValidationState) -> None:
    value = schema.get("enum")
    if value is None:
        return
    if not isinstance(value, list) or not value or len(value) > MAX_ENUM_VALUES:
        state.add(path, "enum", "enum must be a non-empty bounded JSON value array")
        return
    if any(not _bounded_enum_value(item, 0) for item in value):
        state.add(path, "enum", "enum contains an unsupported or oversized JSON value")
        return
    encoded = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
    if len(encoded) != len(set(encoded)):
        state.add(path, "enum", "enum values must be unique")
    if any(not _enum_matches_schema(item, schema) for item in value):
        state.add(path, "enum", "enum values must satisfy the declared type and bounds")


def _validate_redacted_enum(value: object, path: str, state: _ValidationState) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping) or set(value) != {"value_count", "values_redacted"}:
        state.add(path, "x-flowtest-redacted-enum", "redacted enum marker is invalid")
        return
    count = value.get("value_count")
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or count < 1
        or count > MAX_ENUM_VALUES
        or value.get("values_redacted") is not True
    ):
        state.add(path, "x-flowtest-redacted-enum", "redacted enum marker is invalid")


def _enum_matches_schema(value: object, schema: Mapping[str, object]) -> bool:
    raw_types = schema.get("type")
    types = raw_types if isinstance(raw_types, list) else [raw_types]
    if raw_types is not None and not any(_enum_matches_type(value, item) for item in types):
        return False
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return True
    minimum = _bound(schema, "minimum", "exclusiveMinimum")
    maximum = _bound(schema, "maximum", "exclusiveMaximum")
    if minimum is not None and (value < minimum[0] or (value == minimum[0] and minimum[1])):
        return False
    return not (
        maximum is not None and (value > maximum[0] or (value == maximum[0] and maximum[1]))
    )


def _enum_matches_type(value: object, expected: object) -> bool:
    if not isinstance(expected, str):
        return False
    matches = {
        "null": value is None,
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "string": isinstance(value, str),
        "array": isinstance(value, list),
        "object": isinstance(value, Mapping),
    }
    return matches.get(expected, False)


def _bounded_enum_value(value: object, depth: int) -> bool:
    if depth > 4:
        return False
    if value is None or isinstance(value, (bool, int, float)):
        return True
    if isinstance(value, str):
        return len(value) <= 1_000 and _CONTROL.search(value) is None
    if isinstance(value, list):
        return len(value) <= 50 and all(_bounded_enum_value(item, depth + 1) for item in value)
    return False


def _validate_text(schema: Mapping[str, object], path: str, state: _ValidationState) -> None:
    for key in ("title", "description"):
        value = schema.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH or _CONTROL.search(value):
            state.add(path, key, f"{key} must be a bounded string without control characters")
    format_name = schema.get("format")
    if format_name is not None and (
        not isinstance(format_name, str)
        or not format_name
        or len(format_name) > MAX_FORMAT_LENGTH
        or _CONTROL.search(format_name)
        or looks_sensitive_contract_value(format_name)
    ):
        state.add(path, "format", "format must be a safe bounded annotation")
    pattern = schema.get("pattern")
    if pattern is None:
        return
    if (
        not isinstance(pattern, str)
        or len(pattern) > MAX_PATTERN_LENGTH
        or _CONTROL.search(pattern)
        or looks_sensitive_contract_value(pattern)
        or _regex_complexity(pattern) > 40
        or _NESTED_QUANTIFIER.search(pattern)
    ):
        state.add(path, "pattern", "pattern must be a safe bounded regular expression")
        return
    try:
        re.compile(pattern)
    except re.error:
        state.add(path, "pattern", "pattern must compile as a regular expression")


def _regex_complexity(pattern: str) -> int:
    return sum(pattern.count(token) for token in ("*", "+", "?", "{", "|", "("))


def _validate_discriminator(value: object, path: str, state: _ValidationState) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        state.add(path, "discriminator", "discriminator must be an object")
        return
    if set(value) - {"propertyName", "mapping"}:
        state.add(path, "discriminator", "discriminator contains unsupported keys")
    property_name = value.get("propertyName")
    if (
        not isinstance(property_name, str)
        or not property_name
        or len(property_name) > MAX_PROPERTY_NAME
        or _CONTROL.search(property_name)
    ):
        state.add(path, "discriminator", "discriminator propertyName is invalid")
    mapping = value.get("mapping")
    if mapping is None:
        return
    if not isinstance(mapping, Mapping) or len(mapping) > MAX_PROPERTIES:
        state.add(path, "discriminator", "discriminator mapping must be a bounded object")
        return
    for key, target in mapping.items():
        if (
            not isinstance(key, str)
            or not isinstance(target, str)
            or not key
            or not target
            or len(key) > MAX_PROPERTY_NAME
            or len(target) > 2_048
            or _CONTROL.search(key)
            or _CONTROL.search(target)
            or looks_sensitive_contract_value(target)
        ):
            state.add(path, "discriminator", "discriminator mapping contains an unsafe value")


def _issue(path: str, keyword: str, reason: str) -> CanonicalSchemaIssue:
    return CanonicalSchemaIssue(path=path[:1_024], keyword=keyword[:80], reason=reason[:500])
