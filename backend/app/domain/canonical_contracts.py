"""Pure sanitization and semantic fingerprinting for canonical API contracts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, cast
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, JsonValue

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
_DANGEROUS_HINT_KEYS = frozenset(
    {"example", "examples", "default", "const", "x-example", "x-examples"}
)
_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(authorization|cookie|password|passwd|secret|token|api[_-]?key|"
    r"access[_-]?key|private[_-]?key)(?:$|[_-])",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_BEARER = re.compile(r"^Bearer\s+\S+$", re.IGNORECASE)
_BASIC = re.compile(r"^Basic\s+[A-Za-z0-9+/=]{8,}$", re.IGNORECASE)
_JWT = re.compile(r"^[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}$")
_CARD = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
_ACCESS_KEY = re.compile(r"^(?:AKIA|ASIA)[A-Z0-9]{16}$")
_PHONE = re.compile(r"^\+?[1-9]\d{9,14}$")


@dataclass(frozen=True, slots=True)
class CanonicalContractSanitization:
    payload: dict[str, JsonValue]
    redacted_count: int
    removed_hint_count: int
    invalid_count: int
    warnings: tuple[str, ...]


@dataclass(slots=True)
class _SanitizationState:
    redacted_count: int = 0
    removed_hint_count: int = 0
    enum_redacted: bool = False
    semantic_value_removed: bool = False
    invalid_count: int = 0


def sanitize_contract_payload(
    payload: Mapping[str, object], *, strict: bool = True
) -> CanonicalContractSanitization:
    """Return the only persistable/readable representation of an operation contract."""

    state = _SanitizationState()
    if strict:
        _validate_contract_schemas(payload)
    parameters = [
        sanitized
        for raw in _list(payload.get("parameters"))
        if (sanitized := _sanitize_parameter(_mapping(raw), state)) is not None
    ]
    request_body = _sanitize_request_body(_mapping(payload.get("request_body")), state)
    legacy_request = _sanitize_schema(_mapping(payload.get("request")), state)
    responses = {
        status: _sanitize_response(_mapping(raw), state)
        for status, raw in sorted(_mapping(payload.get("responses")).items())
        if re.fullmatch(r"[1-5][0-9]{2}|default", status)
    }
    completeness = str(payload.get("completeness") or "complete")
    if state.redacted_count or state.semantic_value_removed:
        completeness = "redacted_partial"
    warnings = {
        str(item)
        for item in _list(payload.get("warnings"))
        if isinstance(item, str) and not looks_sensitive_contract_value(item)
    }
    if state.removed_hint_count:
        warnings.add("canonical schema example/default/const hints removed")
    if state.redacted_count:
        warnings.add("sensitive canonical contract values redacted")
    if state.enum_redacted:
        warnings.add("sensitive enum values removed; only value count is retained")
    result: dict[str, JsonValue] = {
        "operation": str(payload.get("operation") or "operation"),
        "method": str(payload.get("method") or "GET").upper(),
        "path": str(payload.get("path") or "/"),
        "service": _safe_optional_text(payload.get("service"), state),
        "auth": _sanitize_auth(_mapping(payload.get("auth")), state),
        "parameters": cast(JsonValue, parameters),
        "request_body": cast(JsonValue, request_body),
        "request": legacy_request,
        "responses": cast(JsonValue, responses),
        "source_ref": _safe_optional_text(payload.get("source_ref"), state),
        "revision": _safe_optional_text(payload.get("revision"), state),
        "completeness": completeness,
        "warnings": cast(JsonValue, sorted(warnings)),
    }
    return CanonicalContractSanitization(
        payload=result,
        redacted_count=state.redacted_count,
        removed_hint_count=state.removed_hint_count,
        invalid_count=state.invalid_count,
        warnings=tuple(sorted(warnings)),
    )


def semantic_contract_fingerprint(payload: Mapping[str, object]) -> str:
    """Fingerprint contract semantics without provenance, warnings, or instance metadata."""

    sanitized = sanitize_contract_payload(payload).payload
    auth = _mapping(sanitized.get("auth"))
    parameters = []
    for raw in _list(sanitized.get("parameters")):
        parameter = _mapping(raw)
        parameters.append(
            {
                key: _semantic_schema_projection(parameter.get(key))
                for key in ("name", "location", "required", "schema", "style", "explode")
            }
        )
    request_body = _mapping(sanitized.get("request_body"))
    if request_body:
        semantic_request: JsonValue = {
            key: _semantic_schema_projection(request_body.get(key))
            for key in ("required", "content_type", "schema")
        }
    else:
        semantic_request = _semantic_schema_projection(sanitized.get("request", {}))
    responses = {
        status: {
            key: _semantic_schema_projection(response.get(key))
            for key in ("content_type", "schema")
        }
        for status, raw in sorted(_mapping(sanitized.get("responses")).items())
        if (response := _mapping(raw))
    }
    projection = {
        "method": sanitized.get("method"),
        "path": sanitized.get("path"),
        "service": sanitized.get("service"),
        "auth": {key: auth.get(key) for key in ("required", "kind", "location", "name")},
        "parameters": sorted(
            parameters,
            key=lambda item: (str(item.get("location")), str(item.get("name")).lower()),
        ),
        "request_body": semantic_request,
        "responses": responses,
    }
    canonical = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode()).hexdigest()


def semantic_schema_fingerprint(schema: Mapping[str, object]) -> str:
    """Return a stable, annotation-free and secret-free response Schema identity."""

    state = _SanitizationState()
    normalized = _sanitize_schema(schema, state)
    projection = _semantic_schema_projection(normalized)
    return sha256(_canonical_json(projection).encode()).hexdigest()


def looks_sensitive_contract_value(value: str) -> bool:
    if value in {"", "***"} or value.startswith("secret://") or "{{secret." in value:
        return False
    return bool(
        _EMAIL.search(value)
        or _BEARER.fullmatch(value)
        or _BASIC.fullmatch(value)
        or _JWT.fullmatch(value)
        or _CARD.search(value)
        or _ACCESS_KEY.fullmatch(value)
        or _PHONE.fullmatch(value)
        or "-----BEGIN " in value
        or _url_has_sensitive_identity(value)
        or _high_entropy(value)
    )


def contains_sensitive_contract_value(value: object) -> bool:
    """Return whether a JSON-like value contains a credential or direct identifier."""

    return _sensitive_json_value(value)


def _sanitize_parameter(
    parameter: Mapping[str, object], state: _SanitizationState
) -> dict[str, JsonValue] | None:
    name = parameter.get("name")
    location = parameter.get("location")
    if (
        not isinstance(name, str)
        or not isinstance(location, str)
        or location not in {"path", "query", "header", "cookie"}
    ):
        return None
    if "example" in parameter and parameter.get("example") is not None:
        _drop_hint(parameter.get("example"), state, semantic=False)
    return {
        "name": name,
        "location": location,
        "required": bool(parameter.get("required")),
        "schema": _sanitize_schema(_mapping(parameter.get("schema")), state),
        "style": _safe_optional_text(parameter.get("style"), state),
        "explode": cast(JsonValue, parameter.get("explode"))
        if isinstance(parameter.get("explode"), bool)
        else None,
        "source_ref": _safe_optional_text(parameter.get("source_ref"), state),
    }


def _sanitize_request_body(
    request_body: Mapping[str, object], state: _SanitizationState
) -> dict[str, JsonValue] | None:
    if not request_body:
        return None
    return {
        "required": bool(request_body.get("required")),
        "content_type": str(request_body.get("content_type") or "application/json")[:160],
        "schema": _sanitize_schema(_mapping(request_body.get("schema")), state),
    }


def _sanitize_response(
    response: Mapping[str, object], state: _SanitizationState
) -> dict[str, JsonValue]:
    schema = response.get("schema")
    return {
        "description": _safe_optional_text(response.get("description"), state) or "",
        "content_type": _safe_optional_text(response.get("content_type"), state),
        "schema": _sanitize_schema(_mapping(schema), state)
        if isinstance(schema, Mapping)
        else None,
    }


def _sanitize_auth(auth: Mapping[str, object], state: _SanitizationState) -> dict[str, JsonValue]:
    location = auth.get("location")
    return {
        "required": bool(auth.get("required")),
        "kind": str(auth.get("kind") or "none"),
        "location": location if location in {"header", "query", "cookie"} else None,
        "name": _safe_optional_text(auth.get("name"), state),
        "source_ref": _safe_optional_text(auth.get("source_ref"), state),
    }


def _sanitize_schema(
    schema: Mapping[str, object], state: _SanitizationState
) -> dict[str, JsonValue]:
    schema = _normalize_exclusive_boundaries(schema)
    result: dict[str, JsonValue] = {}
    for key, raw in schema.items():
        if key in _DANGEROUS_HINT_KEYS:
            _drop_hint(raw, state, semantic=key == "const")
            continue
        if key not in _SCHEMA_KEYS:
            continue
        sanitized = _sanitize_schema_item(key, raw, state)
        if key == "enum" and isinstance(sanitized, dict):
            result["x-flowtest-redacted-enum"] = sanitized
        else:
            result[key] = sanitized
    return result


def _normalize_exclusive_boundaries(schema: Mapping[str, object]) -> dict[str, object]:
    normalized = dict(schema)
    for inclusive_key, exclusive_key in (
        ("minimum", "exclusiveMinimum"),
        ("maximum", "exclusiveMaximum"),
    ):
        exclusive = normalized.get(exclusive_key)
        inclusive = normalized.get(inclusive_key)
        if not isinstance(exclusive, bool):
            continue
        normalized.pop(exclusive_key, None)
        if exclusive and isinstance(inclusive, (int, float)) and not isinstance(inclusive, bool):
            normalized.pop(inclusive_key, None)
            normalized[exclusive_key] = inclusive
    return normalized


def _sanitize_schema_item(key: str, raw: object, state: _SanitizationState) -> JsonValue:
    if key == "properties":
        return {
            name: _sanitize_schema(_mapping(child), state)
            for name, child in sorted(_mapping(raw).items())
        }
    if key in {"items", "not"}:
        return _sanitize_schema(_mapping(raw), state)
    if key in {"oneOf", "anyOf", "allOf"}:
        return [_sanitize_schema(_mapping(child), state) for child in _list(raw)]
    if key == "additionalProperties" and isinstance(raw, Mapping):
        return _sanitize_schema(_mapping(raw), state)
    if key == "enum" and isinstance(raw, list):
        return _sanitize_enum(raw, state)
    if key in {"title", "description"} and isinstance(raw, str):
        if looks_sensitive_contract_value(raw):
            state.redacted_count += 1
            state.semantic_value_removed = True
            return "***"
        return raw
    if key == "discriminator":
        return _sanitize_generic(cast(JsonValue, raw), state)
    return cast(JsonValue, raw)


def _sanitize_enum(values: list[object], state: _SanitizationState) -> JsonValue:
    if not any(_sensitive_json_value(value) for value in values):
        return cast(JsonValue, values)
    state.redacted_count += sum(_sensitive_json_value(value) for value in values)
    state.enum_redacted = True
    state.semantic_value_removed = True
    return {
        "value_count": len(values),
        "values_redacted": True,
    }


def _validate_contract_schemas(payload: Mapping[str, object]) -> None:
    # Lazy import avoids a module cycle while keeping sensitive-value recognition centralized.
    from app.domain.canonical_schemas import CanonicalSchemaValidator

    validator = CanonicalSchemaValidator()
    allow_partial = str(payload.get("completeness") or "complete") != "complete"
    for index, raw in enumerate(_list(payload.get("parameters"))):
        parameter = _mapping(raw)
        validator.validate(
            _normalize_exclusive_boundaries(_mapping(parameter.get("schema"))),
            path=f"$.parameters[{index}].schema",
            allow_partial_required=allow_partial,
        )
    request_body = _mapping(payload.get("request_body"))
    if request_body:
        validator.validate(
            _normalize_exclusive_boundaries(_mapping(request_body.get("schema"))),
            path="$.request_body.schema",
            allow_partial_required=allow_partial,
        )
    request = _mapping(payload.get("request"))
    if request:
        validator.validate(
            _normalize_exclusive_boundaries(request),
            path="$.request",
            allow_partial_required=allow_partial,
        )
    for status, raw in _mapping(payload.get("responses")).items():
        response = _mapping(raw)
        schema = response.get("schema")
        if isinstance(schema, Mapping):
            validator.validate(
                _normalize_exclusive_boundaries(_mapping(schema)),
                path=f"$.responses.{status}.schema",
                allow_partial_required=allow_partial,
            )


def _semantic_schema_projection(value: object) -> JsonValue:
    if isinstance(value, Mapping):
        return {
            str(key): _semantic_schema_projection(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            if str(key) not in {"title", "description", "source_ref", "warnings"}
        }
    if isinstance(value, list):
        return [_semantic_schema_projection(child) for child in value]
    return cast(JsonValue, value)


def _sanitize_generic(value: JsonValue, state: _SanitizationState) -> JsonValue:
    if isinstance(value, dict):
        return {key: _sanitize_generic(child, state) for key, child in value.items()}
    if isinstance(value, list):
        return [_sanitize_generic(child, state) for child in value]
    if isinstance(value, str) and looks_sensitive_contract_value(value):
        state.redacted_count += 1
        state.semantic_value_removed = True
        return "***"
    return value


def _drop_hint(value: object, state: _SanitizationState, *, semantic: bool) -> None:
    state.removed_hint_count += 1
    state.semantic_value_removed = state.semantic_value_removed or semantic
    if _sensitive_json_value(value):
        state.redacted_count += 1
        state.semantic_value_removed = True


def _safe_optional_text(value: object, state: _SanitizationState) -> str | None:
    if not isinstance(value, str):
        return None
    if looks_sensitive_contract_value(value):
        state.redacted_count += 1
        state.semantic_value_removed = True
        return None
    return value


def _sensitive_json_value(value: object) -> bool:
    if isinstance(value, str):
        return looks_sensitive_contract_value(value)
    if isinstance(value, Mapping):
        return any(
            (
                _SENSITIVE_KEY.search(str(key)) is not None
                and child is not None
                and child != ""
                and child != "***"
            )
            or _sensitive_json_value(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_sensitive_json_value(child) for child in value)
    return False


def _url_has_sensitive_identity(value: str) -> bool:
    if "://" not in value:
        return False
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None:
        return True
    return any(_SENSITIVE_KEY.search(name) for name, _value in parse_qsl(parsed.query))


def _high_entropy(value: str) -> bool:
    if not 32 <= len(value) <= 512 or re.fullmatch(r"[A-Za-z0-9_+/=-]+", value) is None:
        return False
    return (
        any(character.islower() for character in value)
        and any(character.isupper() for character in value)
        and any(character.isdigit() for character in value)
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _mapping(value: object) -> dict[str, object]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True)
    if not isinstance(value, Mapping):
        return {}
    return {str(key): child for key, child in value.items() if isinstance(key, str)}


def _list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []
