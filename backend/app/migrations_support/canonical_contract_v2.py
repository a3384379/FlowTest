"""Frozen S47.3 canonical contract cleanup.

Migration contract: immutable after release. Never replace this implementation with
imports from the runtime domain sanitizer; historical migration output must stay stable.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit

_TYPES = frozenset({"null", "boolean", "object", "array", "number", "string", "integer"})
_SCHEMA_KEYS = frozenset(
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
    }
)
_DANGEROUS_HINTS = frozenset({"example", "examples", "default", "const", "x-example", "x-examples"})
_NUMERIC = frozenset({"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"})
_COUNTS = frozenset(
    {"minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties"}
)
_BOOLEANS = frozenset({"uniqueItems", "nullable", "readOnly", "writeOnly"})
_BRANCHES = frozenset({"oneOf", "anyOf", "allOf"})
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_BEARER = re.compile(r"^Bearer\s+\S+$", re.IGNORECASE)
_JWT = re.compile(r"^[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}$")
_CARD = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
_ACCESS_KEY = re.compile(r"^(?:AKIA|ASIA)[A-Z0-9]{16}$")
_PHONE = re.compile(r"^\+?[1-9]\d{9,14}$")
_NESTED_QUANTIFIER = re.compile(r"\([^)]*[+*][^)]*\)[+*{]")


@dataclass(frozen=True, slots=True)
class HistoricalCleanup:
    payload: dict[str, Any]
    fingerprint: str
    completeness: str
    invalid_count: int
    redacted_count: int


@dataclass(slots=True)
class _State:
    invalid: int = 0
    redacted: int = 0


def clean_historical_contract(payload: Mapping[str, object]) -> HistoricalCleanup:
    state = _State()
    parameters = [
        item_cleaned
        for item in _list(payload.get("parameters"))
        if (item_cleaned := _parameter(_mapping(item), state)) is not None
    ]
    request_body = _request_body(_mapping(payload.get("request_body")), state)
    request = _schema(_mapping(payload.get("request")), state, 0)
    responses = {
        status: _response(_mapping(value), state)
        for status, value in sorted(_mapping(payload.get("responses")).items())
        if re.fullmatch(r"[1-5][0-9]{2}|default", status)
    }
    operation = _safe_identifier(payload.get("operation"), "operation", 240, state)
    method = _safe_method(payload.get("method"), state)
    path = _safe_path(payload.get("path"), state)
    service = _safe_optional_text(payload.get("service"), 160, state)
    auth = _auth(_mapping(payload.get("auth")), state)
    source_ref = _safe_optional_text(payload.get("source_ref"), 512, state)
    revision = _safe_optional_text(payload.get("revision"), 160, state)
    original_completeness = str(payload.get("completeness") or "complete")
    allowed_completeness = {
        "complete",
        "legacy_partial",
        "redacted_partial",
        "invalid_history_cleaned",
    }
    if original_completeness not in allowed_completeness:
        state.invalid += 1
    warnings = {
        str(item)[:500]
        for item in _list(payload.get("warnings"))
        if isinstance(item, str) and not _sensitive(item) and not _CONTROL.search(item)
    }
    if state.invalid:
        warnings.add(
            "historical canonical schema contained invalid keywords; unsafe values removed"
        )
    if state.redacted:
        warnings.add("historical canonical contract contained sensitive values; values removed")
    if state.redacted:
        completeness = "redacted_partial"
    elif state.invalid:
        completeness = "invalid_history_cleaned"
    elif original_completeness in allowed_completeness:
        completeness = original_completeness
    else:
        completeness = "invalid_history_cleaned"
    cleaned_contract: dict[str, Any] = {
        "operation": operation,
        "method": method,
        "path": path,
        "service": service,
        "auth": auth,
        "parameters": parameters,
        "request_body": request_body,
        "request": request,
        "responses": responses,
        "source_ref": source_ref,
        "revision": revision,
        "completeness": completeness,
        "warnings": sorted(warnings),
    }
    fingerprint = semantic_fingerprint(cleaned_contract)
    return HistoricalCleanup(
        cleaned_contract, fingerprint, completeness, state.invalid, state.redacted
    )


def semantic_fingerprint(payload: Mapping[str, object]) -> str:
    auth = _mapping(payload.get("auth"))
    parameters = [
        {
            key: _semantic(item.get(key))
            for key in ("name", "location", "required", "schema", "style", "explode")
        }
        for raw in _list(payload.get("parameters"))
        if (item := _mapping(raw))
    ]
    request_body = _mapping(payload.get("request_body"))
    request: Any = (
        {key: _semantic(request_body.get(key)) for key in ("required", "content_type", "schema")}
        if request_body
        else _semantic(payload.get("request", {}))
    )
    responses = {
        status: {key: _semantic(response.get(key)) for key in ("content_type", "schema")}
        for status, raw in sorted(_mapping(payload.get("responses")).items())
        if (response := _mapping(raw))
    }
    projection = {
        "method": payload.get("method"),
        "path": payload.get("path"),
        "service": payload.get("service"),
        "auth": {key: auth.get(key) for key in ("required", "kind", "location", "name")},
        "parameters": sorted(
            parameters,
            key=lambda item: (str(item.get("location")), str(item.get("name")).lower()),
        ),
        "request_body": request,
        "responses": responses,
    }
    encoded = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode()).hexdigest()


def _parameter(value: Mapping[str, object], state: _State) -> dict[str, Any] | None:
    name = value.get("name")
    location = value.get("location")
    if (
        not isinstance(name, str)
        or not name
        or location not in {"path", "query", "header", "cookie"}
    ):
        state.invalid += 1
        return None
    return {
        "name": name[:160],
        "location": location,
        "required": value.get("required") is True,
        "schema": _schema(_mapping(value.get("schema")), state, 0),
        "style": _safe_optional_text(value.get("style"), 80, state),
        "explode": value.get("explode") if isinstance(value.get("explode"), bool) else None,
        "source_ref": _safe_optional_text(value.get("source_ref"), 512, state),
    }


def _request_body(value: Mapping[str, object], state: _State) -> dict[str, Any] | None:
    if not value:
        return None
    return {
        "required": value.get("required") is True,
        "content_type": _safe_optional_text(value.get("content_type"), 160, state)
        or "application/json",
        "schema": _schema(_mapping(value.get("schema")), state, 0),
    }


def _response(value: Mapping[str, object], state: _State) -> dict[str, Any]:
    schema = value.get("schema")
    return {
        "description": _safe_optional_text(value.get("description"), 4000, state) or "",
        "content_type": _safe_optional_text(value.get("content_type"), 160, state),
        "schema": _schema(_mapping(schema), state, 0) if isinstance(schema, Mapping) else None,
    }


def _auth(value: Mapping[str, object], state: _State) -> dict[str, Any]:
    kind = value.get("kind")
    if kind not in {"none", "bearer", "basic", "api_key"}:
        kind = "none"
        state.invalid += 1
    location = value.get("location")
    if location not in {"header", "query", "cookie"}:
        location = None
    return {
        "required": value.get("required") is True,
        "kind": kind,
        "location": location,
        "name": _safe_optional_text(value.get("name"), 160, state),
        "source_ref": _safe_optional_text(value.get("source_ref"), 512, state),
    }


def _schema(value: Mapping[str, object], state: _State, depth: int) -> dict[str, Any]:
    if depth > 24:
        state.invalid += 1
        return {}
    result: dict[str, Any] = {}
    for key, raw in value.items():
        if key in _DANGEROUS_HINTS:
            state.invalid += 1
            continue
        if key not in _SCHEMA_KEYS:
            state.invalid += 1
            continue
        cleaned = _schema_value(key, raw, state, depth)
        if cleaned is not _INVALID:
            if key == "enum" and isinstance(cleaned, dict):
                result["x-flowtest-redacted-enum"] = cleaned
            else:
                result[key] = cleaned
    _clean_schema_relationships(result, state)
    return result


_INVALID = object()
_UNHANDLED = object()


def _schema_value(key: str, raw: object, state: _State, depth: int) -> object:
    simple = _simple_schema_value(key, raw, state)
    if simple is not _UNHANDLED:
        return simple
    structured = _structured_schema_value(key, raw, state, depth)
    if structured is not _UNHANDLED:
        return structured
    return _annotation_schema_value(key, raw, state)


def _simple_schema_value(key: str, raw: object, state: _State) -> object:
    if key == "type":
        return _schema_type(raw, state)
    if key in _NUMERIC:
        return _numeric_value(key, raw, state)
    if key in _COUNTS:
        return _count_value(raw, state)
    if key in _BOOLEANS:
        return raw if isinstance(raw, bool) else _invalid(state)
    return _UNHANDLED


def _structured_schema_value(key: str, raw: object, state: _State, depth: int) -> object:
    if key == "properties":
        return _properties(raw, state, depth)
    if key == "required":
        return _required(raw, state)
    if key in {"items", "not"}:
        return (
            _schema(_mapping(raw), state, depth + 1)
            if isinstance(raw, Mapping)
            else _invalid(state)
        )
    if key in _BRANCHES:
        return _branches(raw, state, depth)
    if key == "additionalProperties":
        return _additional(raw, state, depth)
    if key == "enum":
        return _enum(raw, state)
    if key == "x-flowtest-redacted-enum":
        return _redacted_enum(raw, state)
    return _UNHANDLED


def _annotation_schema_value(key: str, raw: object, state: _State) -> object:
    if key in {"title", "description"}:
        return _safe_schema_text(raw, 4000, state)
    if key == "format":
        return _safe_schema_text(raw, 80, state, remove_sensitive=True)
    if key == "pattern":
        return _pattern(raw, state)
    if key == "discriminator":
        return _discriminator(raw, state)
    return _invalid(state)


def _schema_type(raw: object, state: _State) -> object:
    if isinstance(raw, str) and raw in _TYPES:
        return raw
    if (
        isinstance(raw, list)
        and raw
        and all(isinstance(item, str) and item in _TYPES for item in raw)
    ):
        unique = list(dict.fromkeys(raw))
        if len(unique) != len(raw):
            state.invalid += 1
        return unique
    return _invalid(state)


def _numeric_value(key: str, raw: object, state: _State) -> object:
    if not isinstance(raw, (int, float)) or isinstance(raw, bool) or not math.isfinite(raw):
        return _invalid(state)
    if key == "multipleOf" and raw <= 0:
        return _invalid(state)
    return raw


def _count_value(raw: object, state: _State) -> object:
    return (
        raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else _invalid(state)
    )


def _properties(raw: object, state: _State, depth: int) -> object:
    if not isinstance(raw, Mapping) or len(raw) > 500:
        return _invalid(state)
    result: dict[str, Any] = {}
    for name, child in sorted(raw.items(), key=lambda item: str(item[0])):
        if not isinstance(name, str) or not name or len(name) > 160 or _CONTROL.search(name):
            state.invalid += 1
            continue
        if not isinstance(child, Mapping):
            state.invalid += 1
            continue
        result[name] = _schema(child, state, depth + 1)
    return result


def _required(raw: object, state: _State) -> object:
    if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
        return _invalid(state)
    safe = [item[:160] for item in raw if len(item) <= 160 and not _CONTROL.search(item)]
    unique = list(dict.fromkeys(safe))
    if len(unique) != len(raw):
        state.invalid += 1
    return unique


def _branches(raw: object, state: _State, depth: int) -> object:
    if not isinstance(raw, list) or not raw or len(raw) > 50:
        return _invalid(state)
    result = [_schema(item, state, depth + 1) for item in raw if isinstance(item, Mapping)]
    if len(result) != len(raw):
        state.invalid += 1
    return result if result else _invalid(state)


def _additional(raw: object, state: _State, depth: int) -> object:
    if isinstance(raw, bool):
        return raw
    return _schema(raw, state, depth + 1) if isinstance(raw, Mapping) else _invalid(state)


def _enum(raw: object, state: _State) -> object:
    if not isinstance(raw, list) or not raw or len(raw) > 500:
        return _invalid(state)
    values = [item for item in raw if _bounded_enum(item, 0)]
    if len(values) != len(raw):
        state.invalid += 1
    if not values:
        return _INVALID
    if any(_sensitive_json(item) for item in values):
        state.redacted += sum(_sensitive_json(item) for item in values)
        return {"value_count": len(values), "values_redacted": True}
    return values


def _redacted_enum(raw: object, state: _State) -> object:
    value = _mapping(raw)
    count = value.get("value_count")
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 500:
        return _invalid(state)
    if "value_hashes" in value:
        state.redacted += 1
    return {"value_count": count, "values_redacted": True}


def _safe_schema_text(
    raw: object, limit: int, state: _State, *, remove_sensitive: bool = False
) -> object:
    if not isinstance(raw, str) or not raw or len(raw) > limit or _CONTROL.search(raw):
        return _invalid(state)
    if _sensitive(raw):
        state.redacted += 1
        return _INVALID if remove_sensitive else "***"
    return raw


def _pattern(raw: object, state: _State) -> object:
    value = _safe_schema_text(raw, 500, state, remove_sensitive=True)
    if value is _INVALID or not isinstance(value, str):
        return _INVALID
    try:
        re.compile(value)
    except re.error:
        return _invalid(state)
    if _NESTED_QUANTIFIER.search(value):
        return _invalid(state)
    return value


def _discriminator(raw: object, state: _State) -> object:
    value = _mapping(raw)
    property_name = value.get("propertyName")
    if not isinstance(property_name, str) or not property_name or len(property_name) > 160:
        return _invalid(state)
    result: dict[str, Any] = {"propertyName": property_name}
    mapping = value.get("mapping")
    if mapping is not None:
        if not isinstance(mapping, Mapping):
            return _invalid(state)
        safe_mapping = {
            str(key)[:160]: target
            for key, target in mapping.items()
            if isinstance(key, str)
            and isinstance(target, str)
            and len(target) <= 2048
            and not _sensitive(target)
        }
        if len(safe_mapping) != len(mapping):
            state.redacted += 1
        result["mapping"] = safe_mapping
    return result


def _clean_schema_relationships(schema: dict[str, Any], state: _State) -> None:
    properties = schema.get("properties")
    required = schema.get("required")
    if isinstance(required, list) and isinstance(properties, dict):
        filtered = [name for name in required if name in properties]
        if len(filtered) != len(required):
            state.invalid += 1
        schema["required"] = filtered
    for minimum, maximum in (
        ("minLength", "maxLength"),
        ("minItems", "maxItems"),
        ("minProperties", "maxProperties"),
    ):
        if minimum in schema and maximum in schema and schema[minimum] > schema[maximum]:
            schema.pop(minimum, None)
            schema.pop(maximum, None)
            state.invalid += 1
    lower = _effective_bound(schema, lower=True)
    upper = _effective_bound(schema, lower=False)
    if (
        lower
        and upper
        and (lower[0] > upper[0] or (lower[0] == upper[0] and (lower[1] or upper[1])))
    ):
        for key in ("minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum"):
            schema.pop(key, None)
        state.invalid += 1


def _effective_bound(schema: Mapping[str, object], *, lower: bool) -> tuple[float, bool] | None:
    keys = ("minimum", "exclusiveMinimum") if lower else ("maximum", "exclusiveMaximum")
    values = [
        (float(value), key.startswith("exclusive"))
        for key in keys
        if isinstance((value := schema.get(key)), (int, float)) and not isinstance(value, bool)
    ]
    if not values:
        return None
    boundary = (max if lower else min)(value for value, _ in values)
    return boundary, any(value == boundary and exclusive for value, exclusive in values)


def _bounded_enum(value: object, depth: int) -> bool:
    if depth > 4:
        return False
    if value is None or isinstance(value, (bool, int, float)):
        return True
    if isinstance(value, str):
        return len(value) <= 1000 and not _CONTROL.search(value)
    return (
        isinstance(value, list)
        and len(value) <= 50
        and all(_bounded_enum(item, depth + 1) for item in value)
    )


def _semantic(value: object) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _semantic(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            if str(key) not in {"title", "description", "source_ref", "warnings"}
        }
    if isinstance(value, list):
        return [_semantic(item) for item in value]
    return value


def _safe_identifier(raw: object, fallback: str, limit: int, state: _State) -> str:
    if isinstance(raw, str) and raw and len(raw) <= limit and not _CONTROL.search(raw):
        return raw
    state.invalid += 1
    return fallback


def _safe_method(raw: object, state: _State) -> str:
    value = str(raw or "GET").upper()
    if value in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        return value
    state.invalid += 1
    return "GET"


def _safe_path(raw: object, state: _State) -> str:
    value = str(raw or "/")
    path = value.split("?", 1)[0]
    if not path.startswith("/") or _CONTROL.search(path) or _sensitive(path):
        state.invalid += 1
        return "/"
    if path != value:
        state.redacted += 1
    return path[:2048]


def _safe_optional_text(raw: object, limit: int, state: _State) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or len(raw) > limit or _CONTROL.search(raw):
        state.invalid += 1
        return None
    if _sensitive(raw):
        state.redacted += 1
        return None
    return raw


def _sensitive_json(value: object) -> bool:
    if isinstance(value, str):
        return _sensitive(value)
    if isinstance(value, list):
        return any(_sensitive_json(item) for item in value)
    if isinstance(value, Mapping):
        return any(_sensitive_json(item) for item in value.values())
    return False


def _sensitive(value: str) -> bool:
    if value in {"", "***"} or value.startswith("secret://"):
        return False
    parsed = urlsplit(value)
    unsafe_url = bool(parsed.scheme and (parsed.username or parsed.password or parsed.query))
    return bool(
        _EMAIL.search(value)
        or _BEARER.fullmatch(value)
        or _JWT.fullmatch(value)
        or _CARD.search(value)
        or _ACCESS_KEY.fullmatch(value)
        or _PHONE.fullmatch(value)
        or "-----BEGIN " in value
        or unsafe_url
    )


def _invalid(state: _State) -> object:
    state.invalid += 1
    return _INVALID


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, (list, tuple)) else []
