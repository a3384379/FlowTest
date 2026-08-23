import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

import yaml

from app.domain.api_assets import JsonValue

MAX_SCHEMA_BYTES = 5 * 1024 * 1024
MAX_SCHEMA_DEPTH = 64
MAX_SCHEMA_NODES = 100_000
MAX_OPERATIONS = 500

HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})


class ContractSchemaError(ValueError):
    """Raised when an uploaded contract is invalid or exceeds safety limits."""


@dataclass(frozen=True, slots=True)
class ContractOperation:
    key: str
    method: str
    path: str
    operation_id: str
    service_target: str | None
    request_signature: dict[str, JsonValue]
    response_signature: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ContractChange:
    code: str
    severity: str
    operation_key: str
    path: str
    message: str
    before: JsonValue = None
    after: JsonValue = None

    def as_json(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "severity": self.severity,
            "operation_key": self.operation_key,
            "path": self.path,
            "message": self.message,
            "before": self.before,
            "after": self.after,
        }


def load_contract_document(content: bytes) -> dict[str, JsonValue]:
    if not content:
        raise ContractSchemaError("契约文档不能为空")
    if len(content) > MAX_SCHEMA_BYTES:
        raise ContractSchemaError("契约文档超过 5 MB 上限")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContractSchemaError("契约文档必须使用 UTF-8 编码") from error
    try:
        loaded = json.loads(text) if text.lstrip().startswith(("{", "[")) else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise ContractSchemaError("契约文档不是有效的 JSON 或 YAML") from error
    if not isinstance(loaded, Mapping):
        raise ContractSchemaError("契约文档根节点必须是对象")
    document = cast(dict[str, JsonValue], dict(loaded))
    _validate_document_shape(document)
    return document


def contract_operations(document: Mapping[str, JsonValue]) -> tuple[ContractOperation, ...]:
    paths = _mapping(document.get("paths"))
    operations: list[ContractOperation] = []
    for path, raw_path_item in paths.items():
        path_item = _mapping(raw_path_item)
        common_parameters = _sequence(path_item.get("parameters"))
        for method in sorted(HTTP_METHODS):
            raw_operation = path_item.get(method)
            if not isinstance(raw_operation, Mapping):
                continue
            operation = _mapping(raw_operation)
            operation_id = _text(operation.get("operationId")) or f"{method.upper()} {path}"
            parameters = common_parameters + _sequence(operation.get("parameters"))
            operations.append(
                ContractOperation(
                    key=_operation_key(method, path),
                    method=method.upper(),
                    path=path,
                    operation_id=operation_id[:200],
                    service_target=_service_target(operation, path_item, document),
                    request_signature=_request_signature(operation, parameters),
                    response_signature=_response_signature(operation),
                )
            )
    if not operations:
        raise ContractSchemaError("契约文档没有可测试的 HTTP 操作")
    if len(operations) > MAX_OPERATIONS:
        raise ContractSchemaError(f"契约操作数超过 {MAX_OPERATIONS} 上限")
    return tuple(operations)


def breaking_changes(
    baseline: Sequence[ContractOperation], current: Sequence[ContractOperation]
) -> tuple[ContractChange, ...]:
    baseline_by_key = {item.key: item for item in baseline}
    current_by_key = {item.key: item for item in current}
    changes: list[ContractChange] = []
    for key, old in sorted(baseline_by_key.items()):
        new = current_by_key.get(key)
        if new is None:
            changes.append(
                ContractChange(
                    code="OPERATION_REMOVED",
                    severity="breaking",
                    operation_key=key,
                    path=f"operations.{old.method}.{old.path}",
                    message=f"接口 {old.method} {old.path} 已删除",
                    before=old.operation_id,
                )
            )
            continue
        changes.extend(_operation_breaking_changes(old, new))
    return tuple(changes)


def schema_coverage(operations: Sequence[ContractOperation]) -> dict[str, JsonValue]:
    request_fields = sum(_field_count(item.request_signature) for item in operations)
    response_fields = sum(_field_count(item.response_signature) for item in operations)
    total_fields = request_fields + response_fields
    return {
        "operations_total": len(operations),
        "operations_generated": len(operations),
        "operation_coverage_percent": 100.0 if operations else 0.0,
        "request_fields_total": request_fields,
        "response_fields_total": response_fields,
        "schema_fields_total": total_fields,
        "schema_fields_covered": total_fields,
        "schema_coverage_percent": 100.0 if total_fields else 0.0,
    }


def document_sha256(document: Mapping[str, JsonValue]) -> str:
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _validate_document_shape(document: Mapping[str, JsonValue]) -> None:
    if not isinstance(document.get("openapi"), str) and document.get("swagger") != "2.0":
        raise ContractSchemaError("仅支持 OpenAPI 3.x 或 Swagger 2.0 文档")
    nodes = 0
    stack: list[tuple[JsonValue, int]] = [(cast(JsonValue, document), 1)]
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_SCHEMA_NODES:
            raise ContractSchemaError("契约文档节点数超过安全上限")
        if depth > MAX_SCHEMA_DEPTH:
            raise ContractSchemaError("契约文档嵌套深度超过安全上限")
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and not reference.startswith("#/"):
                raise ContractSchemaError("契约文档不允许外部 $ref")
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)


def _operation_breaking_changes(
    old: ContractOperation, new: ContractOperation
) -> list[ContractChange]:
    changes: list[ContractChange] = []
    old_required = set(_string_list(old.request_signature.get("required")))
    new_required = set(_string_list(new.request_signature.get("required")))
    for field in sorted(new_required - old_required):
        changes.append(
            ContractChange(
                code="REQUEST_REQUIRED_ADDED",
                severity="breaking",
                operation_key=old.key,
                path=f"request.required.{field}",
                message=f"新增必填请求字段 {field}",
                after=field,
            )
        )
    old_request_types = _string_mapping(old.request_signature.get("types"))
    new_request_types = _string_mapping(new.request_signature.get("types"))
    changes.extend(_type_changes(old, "request", old_request_types, new_request_types))

    old_codes = set(_string_list(old.response_signature.get("success_codes")))
    new_codes = set(_string_list(new.response_signature.get("success_codes")))
    for code in sorted(old_codes - new_codes):
        changes.append(
            ContractChange(
                code="SUCCESS_RESPONSE_REMOVED",
                severity="breaking",
                operation_key=old.key,
                path=f"responses.{code}",
                message=f"成功响应状态 {code} 已删除",
                before=code,
            )
        )
    old_response_types = _string_mapping(old.response_signature.get("types"))
    new_response_types = _string_mapping(new.response_signature.get("types"))
    for field in sorted(old_response_types.keys() - new_response_types.keys()):
        changes.append(
            ContractChange(
                code="RESPONSE_FIELD_REMOVED",
                severity="breaking",
                operation_key=old.key,
                path=f"response.properties.{field}",
                message=f"响应字段 {field} 已删除",
                before=old_response_types[field],
            )
        )
    changes.extend(_type_changes(old, "response", old_response_types, new_response_types))
    return changes


def _type_changes(
    operation: ContractOperation,
    location: str,
    before: Mapping[str, str],
    after: Mapping[str, str],
) -> list[ContractChange]:
    result: list[ContractChange] = []
    for field in sorted(before.keys() & after.keys()):
        if before[field] == after[field]:
            continue
        result.append(
            ContractChange(
                code=f"{location.upper()}_TYPE_CHANGED",
                severity="breaking",
                operation_key=operation.key,
                path=f"{location}.properties.{field}.type",
                message=f"{location} 字段 {field} 类型从 {before[field]} 变为 {after[field]}",
                before=before[field],
                after=after[field],
            )
        )
    return result


def _request_signature(
    operation: Mapping[str, JsonValue], parameters: list[JsonValue]
) -> dict[str, JsonValue]:
    required: list[str] = []
    types: dict[str, JsonValue] = {}
    constraints: dict[str, JsonValue] = {}
    for raw_parameter in parameters:
        parameter = _mapping(raw_parameter)
        name = _text(parameter.get("name"))
        location = _text(parameter.get("in"))
        if not name or not location:
            continue
        qualified = f"{location}.{name}"
        if parameter.get("required") is True:
            required.append(qualified)
        schema = _mapping(parameter.get("schema")) or parameter
        types[qualified] = _text(schema.get("type")) or "any"
        constraints[qualified] = _schema_constraints(schema)
    request_body = _mapping(operation.get("requestBody"))
    if request_body.get("required") is True:
        required.append("body")
    body_schema = _first_content_schema(request_body)
    _flatten_schema(body_schema, "body", types, constraints)
    return {
        "required": cast(JsonValue, sorted(required)),
        "types": types,
        "constraints": constraints,
    }


def _response_signature(operation: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    responses = _mapping(operation.get("responses"))
    all_codes = sorted(
        code for code in responses if code == "default" or re.fullmatch(r"[1-5][0-9]{2}", code)
    )
    success_codes = sorted(
        code for code in responses if code == "default" or (len(code) == 3 and code.startswith("2"))
    )
    types: dict[str, JsonValue] = {}
    constraints: dict[str, JsonValue] = {}
    for code in success_codes:
        response = _mapping(responses.get(code))
        schema = _first_content_schema(response) or _mapping(response.get("schema"))
        _flatten_schema(schema, code, types, constraints)
    return {
        "all_codes": cast(JsonValue, all_codes),
        "success_codes": cast(JsonValue, success_codes),
        "types": types,
        "constraints": constraints,
    }


def _first_content_schema(container: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    content = _mapping(container.get("content"))
    for media_type in sorted(content):
        if media_type == "application/json" or media_type.endswith("+json"):
            return _mapping(_mapping(content[media_type]).get("schema"))
    return {}


def _flatten_schema(
    schema: Mapping[str, JsonValue],
    prefix: str,
    target: dict[str, JsonValue],
    constraints: dict[str, JsonValue],
    depth: int = 0,
) -> None:
    if not schema or depth > 16:
        return
    schema_type = _text(schema.get("type")) or ("object" if schema.get("properties") else "any")
    target[prefix] = schema_type
    constraints[prefix] = _schema_constraints(schema)
    if schema_type == "array":
        _flatten_schema(
            _mapping(schema.get("items")), f"{prefix}[]", target, constraints, depth + 1
        )
    for name, raw_property in _mapping(schema.get("properties")).items():
        _flatten_schema(_mapping(raw_property), f"{prefix}.{name}", target, constraints, depth + 1)


def _schema_constraints(schema: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    keys = (
        "enum",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minItems",
        "maxItems",
        "uniqueItems",
        "additionalProperties",
        "nullable",
    )
    return {key: schema[key] for key in keys if key in schema}


def _service_target(
    operation: Mapping[str, JsonValue],
    path_item: Mapping[str, JsonValue],
    document: Mapping[str, JsonValue],
) -> str | None:
    for container in (operation, path_item, document):
        servers = container.get("servers")
        if not isinstance(servers, list) or not servers:
            continue
        first = _mapping(servers[0])
        url = _text(first.get("url"))
        if url:
            return url[:2048]
    return None


def _field_count(signature: Mapping[str, JsonValue]) -> int:
    return len(_string_mapping(signature.get("types")))


def _operation_key(method: str, path: str) -> str:
    return hashlib.sha256(f"{method.upper()}:{path}".encode()).hexdigest()


def _mapping(value: object) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): cast(JsonValue, item) for key, item in value.items() if isinstance(key, str)}


def _sequence(value: object) -> list[JsonValue]:
    return cast(list[JsonValue], list(value)) if isinstance(value, list) else []


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items() if isinstance(item, str)}
