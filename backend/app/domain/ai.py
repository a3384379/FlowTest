from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from pydantic import JsonValue

REDACTED = "[REDACTED]"
MAX_INPUT_BYTES = 1024 * 1024
MAX_DEPTH = 32
MAX_NODES = 50_000

_SENSITIVE_KEY = re.compile(
    r"(^|[_\-.])(password|passwd|authorization|cookie|token|secret|api[_-]?key|"
    r"access[_-]?key|private[_-]?key|client[_-]?secret)($|[_\-.])",
    re.IGNORECASE,
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_BASIC_VALUE = re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/=]{8,}")
_JWT_VALUE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_SCHEMA_STRUCTURAL_KEYS = frozenset(
    {
        "$ref",
        "type",
        "format",
        "title",
        "description",
        "required",
        "properties",
        "items",
        "additionalProperties",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "nullable",
        "readOnly",
        "writeOnly",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
    }
)
_SCHEMA_VALUE_KEYS = frozenset({"example", "examples", "default", "const", "enum"})


class AIInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SanitizedAIInput:
    payload: dict[str, JsonValue]
    sha256: str
    redacted_paths: tuple[str, ...]
    sample_included: bool


def sanitize_ai_input(
    *,
    schema_document: dict[str, JsonValue] | None,
    metadata: dict[str, JsonValue],
    sample: JsonValue | None,
) -> SanitizedAIInput:
    redacted: list[str] = []
    counter = [0]
    payload: dict[str, JsonValue] = {
        "schema": _sanitize_value(
            schema_document or {},
            path="$.schema",
            redacted=redacted,
            counter=counter,
            schema_mode=True,
        ),
        "metadata": _sanitize_value(
            metadata, path="$.metadata", redacted=redacted, counter=counter, schema_mode=False
        ),
    }
    if sample is not None:
        payload["sample"] = _sanitize_value(
            sample, path="$.sample", redacted=redacted, counter=counter, schema_mode=False
        )
    encoded = _canonical_json(payload)
    if len(encoded) > MAX_INPUT_BYTES:
        raise AIInputError("AI 输入超过 1 MB 上限")
    return SanitizedAIInput(
        payload=payload,
        sha256=hashlib.sha256(encoded).hexdigest(),
        redacted_paths=tuple(sorted(set(redacted))),
        sample_included=sample is not None,
    )


def suggestion_output_schema(max_suggestions: int) -> dict[str, JsonValue]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["suggestions"],
        "properties": {
            "suggestions": {
                "type": "array",
                "maxItems": max_suggestions,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["type", "title", "content"],
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["test_case", "assertion", "workflow", "failure_analysis"],
                        },
                        "title": {"type": "string", "minLength": 1, "maxLength": 200},
                        "content": {"type": "object", "maxProperties": 100},
                    },
                },
            }
        },
    }


def _sanitize_value(
    value: JsonValue,
    *,
    path: str,
    redacted: list[str],
    counter: list[int],
    schema_mode: bool,
    depth: int = 0,
) -> JsonValue:
    if depth > MAX_DEPTH:
        raise AIInputError("AI 输入嵌套深度超过上限")
    counter[0] += 1
    if counter[0] > MAX_NODES:
        raise AIInputError("AI 输入节点数量超过上限")
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            item_path = f"{path}.{key}"
            if _is_sensitive_key(key) and not _is_schema_definition(item, schema_mode):
                result[key] = REDACTED
                redacted.append(item_path)
                continue
            if schema_mode and key in _SCHEMA_VALUE_KEYS and _path_has_sensitive_name(path):
                result[key] = REDACTED
                redacted.append(item_path)
                continue
            result[key] = _sanitize_value(
                item,
                path=item_path,
                redacted=redacted,
                counter=counter,
                schema_mode=schema_mode,
                depth=depth + 1,
            )
        return result
    if isinstance(value, list):
        return [
            _sanitize_value(
                item,
                path=f"{path}[{index}]",
                redacted=redacted,
                counter=counter,
                schema_mode=schema_mode,
                depth=depth + 1,
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, str):
        cleaned = _redact_embedded_secrets(value)
        if cleaned != value:
            redacted.append(path)
        return cleaned
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower()
    return _SENSITIVE_KEY.search(f"_{normalized}_") is not None


def _is_schema_definition(value: JsonValue, schema_mode: bool) -> bool:
    return schema_mode and isinstance(value, dict) and bool(_SCHEMA_STRUCTURAL_KEYS & value.keys())


def _path_has_sensitive_name(path: str) -> bool:
    return any(_is_sensitive_key(part) for part in re.split(r"[.\[\]]+", path) if part)


def _redact_embedded_secrets(value: str) -> str:
    result = _BEARER_VALUE.sub(REDACTED, value)
    result = _BASIC_VALUE.sub(REDACTED, result)
    return _JWT_VALUE.sub(REDACTED, result)


def _canonical_json(value: JsonValue) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
