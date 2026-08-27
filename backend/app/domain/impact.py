import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from google.protobuf import descriptor_pb2
from graphql import GraphQLError, build_schema
from pydantic import JsonValue

from app.domain.contracts import breaking_changes, contract_operations

MAX_GIT_DIFF_BYTES = 2 * 1024 * 1024
MAX_GIT_DIFF_FILES = 500
MAX_GIT_DIFF_LINES = 100_000
MAX_CHANGE_ITEMS = 5_000
MAX_MAPPINGS = 2_000

_DIFF_HEADER = re.compile(r"^diff --git a/([A-Za-z0-9_./@+\-]+) b/([A-Za-z0-9_./@+\-]+)$")
_SAFE_PATH = re.compile(r"^[A-Za-z0-9_./@+\-]+$")


class SourceKind(StrEnum):
    GIT = "git"
    OPENAPI = "openapi"
    GRAPHQL = "graphql"
    GRPC = "grpc"


class TargetType(StrEnum):
    TEST_CASE = "test_case"
    WORKFLOW = "workflow"
    OPENAPI_CONTRACT = "openapi_contract"
    PACT_CONTRACT = "pact_contract"
    PERFORMANCE = "performance"


class ChangeType(StrEnum):
    ADDED = "added"
    CHANGED = "changed"
    DELETED = "deleted"


class ChangeSeverity(StrEnum):
    BREAKING = "breaking"
    WARNING = "warning"
    INFO = "info"


class ImpactInputError(ValueError):
    """Raised when an untrusted change input violates the bounded contract."""


@dataclass(frozen=True, slots=True)
class ChangeItem:
    key: str
    source_kind: SourceKind
    source_key: str
    change_type: ChangeType
    severity: ChangeSeverity
    label: str
    detail: str
    before: JsonValue = None
    after: JsonValue = None
    semantic_type: str = "schema_changed"
    field_path: str | None = None
    portable_operation_ref: str | None = None
    service_key: str | None = None
    method: str | None = None
    normalized_path: str | None = None
    current_contract_fingerprint: str | None = None
    baseline_contract_fingerprint: str | None = None
    source_contract_run_id: str | None = None
    current_contract_run_id: str | None = None
    api_definition_id: str | None = None
    api_version: int | None = None

    def as_json(self) -> dict[str, JsonValue]:
        return {
            "key": self.key,
            "source_kind": self.source_kind.value,
            "source_key": self.source_key,
            "change_type": self.change_type.value,
            "severity": self.severity.value,
            "label": self.label,
            "detail": self.detail,
            "before": self.before,
            "after": self.after,
            "semantic_type": self.semantic_type,
            "field_path": self.field_path,
            "portable_operation_ref": self.portable_operation_ref,
            "service_key": self.service_key,
            "method": self.method,
            "normalized_path": self.normalized_path,
            "current_contract_fingerprint": self.current_contract_fingerprint,
            "baseline_contract_fingerprint": self.baseline_contract_fingerprint,
            "source_contract_run_id": self.source_contract_run_id,
            "current_contract_run_id": self.current_contract_run_id,
            "api_definition_id": self.api_definition_id,
            "api_version": self.api_version,
        }


@dataclass(frozen=True, slots=True)
class AssetMapping:
    mapping_id: str
    source_kind: SourceKind
    selector: str
    target_type: TargetType
    target_id: str
    target_name: str
    target_version: str | int | None


@dataclass(slots=True)
class _GitFile:
    old_path: str
    new_path: str
    added_lines: int = 0
    deleted_lines: int = 0
    added_file: bool = False
    deleted_file: bool = False
    binary: bool = False


@dataclass(slots=True)
class _SelectedAsset:
    mapping: AssetMapping
    change_keys: set[str]
    reasons: set[str]
    severity: ChangeSeverity

    def as_json(self) -> dict[str, JsonValue]:
        return {
            "asset_type": _asset_category(self.mapping.target_type),
            "target_type": self.mapping.target_type.value,
            "target_id": self.mapping.target_id,
            "name": self.mapping.target_name,
            "version": self.mapping.target_version,
            "risk": _risk_label(self.severity),
            "change_keys": cast(JsonValue, sorted(self.change_keys)),
            "reasons": cast(JsonValue, sorted(self.reasons)),
        }


@dataclass(frozen=True, slots=True)
class ImpactEvidence:
    selected_assets: tuple[dict[str, JsonValue], ...]
    graph: dict[str, JsonValue]
    matrix: tuple[dict[str, JsonValue], ...]
    gaps: tuple[dict[str, JsonValue], ...]
    summary: dict[str, JsonValue]


def parse_git_diff(content: str) -> tuple[ChangeItem, ...]:
    lines = _validate_git_diff(content)
    files = _parse_git_files(lines)
    return tuple(_git_change(file) for file in files)


def _validate_git_diff(content: str) -> list[str]:
    encoded = content.encode("utf-8")
    if not encoded:
        return []
    if len(encoded) > MAX_GIT_DIFF_BYTES:
        raise ImpactInputError("Git Diff 超过 2 MB 上限")
    lines = content.splitlines()
    if len(lines) > MAX_GIT_DIFF_LINES:
        raise ImpactInputError("Git Diff 行数超过 100000 上限")
    return lines


def _parse_git_files(lines: list[str]) -> list[_GitFile]:
    files: list[_GitFile] = []
    current: _GitFile | None = None
    for line in lines:
        match = _DIFF_HEADER.fullmatch(line)
        if match:
            if current is not None:
                files.append(current)
            current = _GitFile(_safe_git_path(match.group(1)), _safe_git_path(match.group(2)))
            if len(files) >= MAX_GIT_DIFF_FILES:
                raise ImpactInputError("Git Diff 文件数超过 500 上限")
            continue
        if current is None:
            if line.strip():
                raise ImpactInputError("Git Diff 必须使用标准 diff --git 格式")
            continue
        _consume_git_line(current, line)
    if current is not None:
        files.append(current)
    if not files:
        raise ImpactInputError("Git Diff 没有文件变更")
    return files


def diff_openapi(
    baseline_document: dict[str, JsonValue],
    current_document: dict[str, JsonValue],
) -> tuple[ChangeItem, ...]:
    baseline = contract_operations(baseline_document)
    current = contract_operations(current_document)
    old_by_key = {item.key: item for item in baseline}
    new_by_key = {item.key: item for item in current}
    changes: list[ChangeItem] = []
    for item in breaking_changes(baseline, current):
        operation = old_by_key[item.operation_key]
        source_key = f"{operation.method} {operation.path}"
        changes.append(
            _change(
                SourceKind.OPENAPI,
                source_key,
                ChangeType.DELETED if item.code == "OPERATION_REMOVED" else ChangeType.CHANGED,
                ChangeSeverity.BREAKING,
                source_key,
                item.message,
                item.before,
                item.after,
                discriminator=item.code,
                semantic_type=_contract_change_type(item.code),
                field_path=item.path,
            )
        )
    for key in sorted(new_by_key.keys() - old_by_key.keys()):
        operation = new_by_key[key]
        source_key = f"{operation.method} {operation.path}"
        changes.append(
            _change(
                SourceKind.OPENAPI,
                source_key,
                ChangeType.ADDED,
                ChangeSeverity.INFO,
                source_key,
                "新增 OpenAPI 操作",
                semantic_type="operation_added",
            )
        )
    for key in sorted(old_by_key.keys() & new_by_key.keys()):
        old = old_by_key[key]
        new = new_by_key[key]
        structured = _structured_operation_changes(old, new)
        changes.extend(structured)
        already_described = any(item.source_key == f"{new.method} {new.path}" for item in changes)
        if already_described or _operation_signature(old) == _operation_signature(new):
            continue
        source_key = f"{new.method} {new.path}"
        changes.append(
            _change(
                SourceKind.OPENAPI,
                source_key,
                ChangeType.CHANGED,
                ChangeSeverity.WARNING,
                source_key,
                "OpenAPI 请求或响应结构发生兼容性变更",
                semantic_type="schema_changed",
            )
        )
    return _bounded_changes(changes)


def diff_graphql(baseline_content: bytes, current_content: bytes) -> tuple[ChangeItem, ...]:
    old_fields = _graphql_fields(baseline_content)
    new_fields = _graphql_fields(current_content)
    changes: list[ChangeItem] = []
    for key in sorted(old_fields.keys() - new_fields.keys()):
        changes.append(
            _change(
                SourceKind.GRAPHQL,
                key,
                ChangeType.DELETED,
                ChangeSeverity.BREAKING,
                key,
                "GraphQL 字段已删除",
                old_fields[key],
            )
        )
    for key in sorted(new_fields.keys() - old_fields.keys()):
        changes.append(
            _change(
                SourceKind.GRAPHQL,
                key,
                ChangeType.ADDED,
                ChangeSeverity.INFO,
                key,
                "新增 GraphQL 字段",
                after=new_fields[key],
            )
        )
    for key in sorted(old_fields.keys() & new_fields.keys()):
        if old_fields[key] == new_fields[key]:
            continue
        changes.append(
            _change(
                SourceKind.GRAPHQL,
                key,
                ChangeType.CHANGED,
                ChangeSeverity.BREAKING,
                key,
                "GraphQL 字段类型或参数签名发生变化",
                old_fields[key],
                new_fields[key],
            )
        )
    return _bounded_changes(changes)


def diff_grpc(baseline_content: bytes, current_content: bytes) -> tuple[ChangeItem, ...]:
    old_shapes = _grpc_shapes(baseline_content)
    new_shapes = _grpc_shapes(current_content)
    changes: list[ChangeItem] = []
    for key in sorted(old_shapes.keys() - new_shapes.keys()):
        changes.append(
            _change(
                SourceKind.GRPC,
                key,
                ChangeType.DELETED,
                ChangeSeverity.BREAKING,
                key,
                "Proto/gRPC 成员已删除",
                old_shapes[key],
            )
        )
    for key in sorted(new_shapes.keys() - old_shapes.keys()):
        changes.append(
            _change(
                SourceKind.GRPC,
                key,
                ChangeType.ADDED,
                ChangeSeverity.INFO,
                key,
                "新增 Proto/gRPC 成员",
                after=new_shapes[key],
            )
        )
    for key in sorted(old_shapes.keys() & new_shapes.keys()):
        if old_shapes[key] == new_shapes[key]:
            continue
        changes.append(
            _change(
                SourceKind.GRPC,
                key,
                ChangeType.CHANGED,
                ChangeSeverity.BREAKING,
                key,
                "Proto/gRPC 签名发生变化",
                old_shapes[key],
                new_shapes[key],
            )
        )
    return _bounded_changes(changes)


def build_impact_evidence(
    changes: tuple[ChangeItem, ...], mappings: tuple[AssetMapping, ...]
) -> ImpactEvidence:
    if len(changes) > MAX_CHANGE_ITEMS:
        raise ImpactInputError("变更项超过 5000 上限")
    if len(mappings) > MAX_MAPPINGS:
        raise ImpactInputError("资产映射超过 2000 上限")
    selected: dict[tuple[TargetType, str], _SelectedAsset] = {}
    change_assets: dict[str, set[tuple[TargetType, str]]] = {
        change.key: set() for change in changes
    }
    edges: list[dict[str, JsonValue]] = []
    for change in changes:
        for mapping in mappings:
            if mapping.source_kind != change.source_kind or not selector_matches(
                mapping.selector, change.source_key
            ):
                continue
            target_key = (mapping.target_type, mapping.target_id)
            asset = selected.setdefault(
                target_key,
                _SelectedAsset(mapping, set(), set(), change.severity),
            )
            asset.change_keys.add(change.key)
            asset.reasons.add(f"{mapping.selector} 命中 {change.source_key}")
            asset.severity = _maximum_severity(asset.severity, change.severity)
            change_assets[change.key].add(target_key)
            edges.append(
                {
                    "from": f"change:{change.key}",
                    "to": f"asset:{mapping.target_type.value}:{mapping.target_id}",
                    "reason": f"映射 {mapping.selector}",
                }
            )
    selected_values = tuple(
        item.as_json()
        for item in sorted(
            selected.values(),
            key=lambda value: (
                _severity_rank(value.severity) * -1,
                _asset_category(value.mapping.target_type),
                value.mapping.target_name,
            ),
        )
    )
    matrix = tuple(_matrix_row(change, change_assets[change.key], selected) for change in changes)
    gaps: tuple[dict[str, JsonValue], ...] = tuple(
        cast(
            dict[str, JsonValue],
            {
                "change_key": change.key,
                "source_kind": change.source_kind.value,
                "source_key": change.source_key,
                "label": change.label,
                "change_type": change.change_type.value,
                "severity": change.severity.value,
                "semantic_type": change.semantic_type,
                "field_path": change.field_path,
                "detail": change.detail,
                "before": change.before,
                "after": change.after,
                "reason": "没有显式资产映射覆盖此变更",
            },
        )
        for change in changes
        if not change_assets[change.key]
    )
    covered = len(changes) - len(gaps)
    total = len(changes)
    summary: dict[str, JsonValue] = {
        "change_count": total,
        "breaking_change_count": sum(
            change.severity == ChangeSeverity.BREAKING for change in changes
        ),
        "selected_asset_count": len(selected_values),
        "covered_change_count": covered,
        "gap_count": len(gaps),
        "coverage_percent": round(covered * 100 / total, 2) if total else 100.0,
    }
    graph = {
        "nodes": cast(
            JsonValue,
            [
                *(
                    {
                        "id": f"change:{change.key}",
                        "kind": "change",
                        "label": change.label,
                        "severity": change.severity.value,
                    }
                    for change in changes
                ),
                *(
                    {
                        "id": f"asset:{item.mapping.target_type.value}:{item.mapping.target_id}",
                        "kind": "asset",
                        "label": item.mapping.target_name,
                        "asset_type": _asset_category(item.mapping.target_type),
                    }
                    for item in selected.values()
                ),
            ],
        ),
        "edges": cast(JsonValue, edges),
    }
    return ImpactEvidence(selected_values, graph, matrix, gaps, summary)


def selector_matches(selector: str, source_key: str) -> bool:
    return (
        source_key.startswith(selector[:-1]) if selector.endswith("*") else selector == source_key
    )


def validate_selector(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 512 or any(char in normalized for char in "\r\n\0"):
        raise ImpactInputError("影响映射选择器无效")
    if "*" in normalized[:-1] or normalized.count("*") > 1:
        raise ImpactInputError("影响映射只允许末尾前缀通配符")
    return normalized


def changes_fingerprint(changes: tuple[ChangeItem, ...]) -> str:
    payload = "\n".join(
        f"{item.key}|{item.source_kind.value}|{item.source_key}|{item.severity.value}"
        for item in changes
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _consume_git_line(current: _GitFile, line: str) -> None:
    if line == "--- /dev/null":
        current.added_file = True
    elif line == "+++ /dev/null":
        current.deleted_file = True
    elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
        current.binary = True
    elif line.startswith("+") and not line.startswith("+++"):
        current.added_lines += 1
    elif line.startswith("-") and not line.startswith("---"):
        current.deleted_lines += 1


def _git_change(file: _GitFile) -> ChangeItem:
    path = file.old_path if file.deleted_file else file.new_path
    change_type = (
        ChangeType.ADDED
        if file.added_file
        else ChangeType.DELETED
        if file.deleted_file
        else ChangeType.CHANGED
    )
    detail = (
        "二进制文件变化"
        if file.binary
        else f"新增 {file.added_lines} 行 / 删除 {file.deleted_lines} 行"
    )
    return _change(
        SourceKind.GIT,
        path,
        change_type,
        ChangeSeverity.WARNING,
        path,
        detail,
    )


def _safe_git_path(value: str) -> str:
    if (
        not value
        or _SAFE_PATH.fullmatch(value) is None
        or value.startswith("/")
        or ".." in value.split("/")
        or value.endswith("/")
    ):
        raise ImpactInputError("Git Diff 包含不安全路径")
    return value


def _graphql_fields(content: bytes) -> dict[str, str]:
    try:
        schema = build_schema(content.decode("utf-8"))
    except (GraphQLError, UnicodeDecodeError) as error:
        raise ImpactInputError("GraphQL 基线或当前 Schema 无效") from error
    result: dict[str, str] = {}
    for type_name, schema_type in schema.type_map.items():
        if type_name.startswith("__"):
            continue
        fields = getattr(schema_type, "fields", None)
        if not isinstance(fields, dict):
            continue
        for field_name, field in fields.items():
            arguments = getattr(field, "args", {})
            argument_signature = ",".join(
                f"{name}:{getattr(argument, 'type', '')}"
                for name, argument in sorted(arguments.items())
            )
            result[f"{type_name}.{field_name}"] = (
                f"({argument_signature})->{getattr(field, 'type', '')}"
            )
    return result


def _grpc_shapes(content: bytes) -> dict[str, str]:
    descriptor_set = descriptor_pb2.FileDescriptorSet()
    try:
        descriptor_set.ParseFromString(content)
    except Exception as error:
        raise ImpactInputError("Proto 基线或当前 Descriptor Set 无效") from error
    if not descriptor_set.file:
        raise ImpactInputError("Proto Descriptor Set 不能为空")
    result: dict[str, str] = {}
    for file_descriptor in descriptor_set.file:
        package = f"{file_descriptor.package}." if file_descriptor.package else ""
        for service in file_descriptor.service:
            service_name = f"{package}{service.name}"
            for method in service.method:
                result[f"{service_name}.{method.name}"] = (
                    f"{method.input_type.lstrip('.')}->{method.output_type.lstrip('.')}"
                    f":client_stream={method.client_streaming}:server_stream={method.server_streaming}"
                )
        for message in file_descriptor.message_type:
            _append_message_shapes(result, package, message)
    return result


def _append_message_shapes(
    result: dict[str, str],
    prefix: str,
    message: descriptor_pb2.DescriptorProto,
) -> None:
    message_name = f"{prefix}{message.name}"
    for field in message.field:
        result[f"{message_name}.{field.name}"] = (
            f"number={field.number}:type={field.type}:label={field.label}:"
            f"type_name={field.type_name.lstrip('.')}"
        )
    for nested in message.nested_type:
        _append_message_shapes(result, f"{message_name}.", nested)


def _structured_operation_changes(old: Any, new: Any) -> list[ChangeItem]:
    source_key = f"{new.method} {new.path}"
    changes = [
        *_field_presence_changes(
            source_key, old.request_signature, new.request_signature, "request"
        ),
        *_field_presence_changes(
            source_key, old.response_signature, new.response_signature, "response"
        ),
        *_required_relaxations(source_key, old.request_signature, new.request_signature),
        *_constraint_changes(source_key, old.request_signature, new.request_signature, "request"),
        *_constraint_changes(
            source_key, old.response_signature, new.response_signature, "response"
        ),
        *_response_status_changes(source_key, old.response_signature, new.response_signature),
    ]
    if old.service_target != new.service_target:
        changes.append(
            _change(
                SourceKind.OPENAPI,
                source_key,
                ChangeType.CHANGED,
                ChangeSeverity.WARNING,
                f"{source_key} · Service Target",
                "Service Target 发生变更",
                old.service_target,
                new.service_target,
                discriminator="SERVICE_TARGET_CHANGED",
                semantic_type="service_target_changed",
                field_path="service_target",
            )
        )
    return changes


def _field_presence_changes(
    source_key: str,
    before_signature: dict[str, JsonValue],
    after_signature: dict[str, JsonValue],
    location: str,
) -> list[ChangeItem]:
    before = _json_mapping(before_signature.get("types"))
    after = _json_mapping(after_signature.get("types"))
    changes: list[ChangeItem] = []
    for field in sorted(after.keys() - before.keys()):
        changes.append(
            _semantic_change(
                source_key,
                f"{location}.{field}",
                "field_added",
                ChangeType.ADDED,
                ChangeSeverity.INFO,
                None,
                after[field],
            )
        )
    if location == "request":
        for field in sorted(before.keys() - after.keys()):
            changes.append(
                _semantic_change(
                    source_key,
                    f"{location}.{field}",
                    "field_removed",
                    ChangeType.DELETED,
                    ChangeSeverity.WARNING,
                    before[field],
                    None,
                )
            )
    return changes


def _required_relaxations(
    source_key: str,
    before_signature: dict[str, JsonValue],
    after_signature: dict[str, JsonValue],
) -> list[ChangeItem]:
    before = set(_json_strings(before_signature.get("required")))
    after = set(_json_strings(after_signature.get("required")))
    return [
        _semantic_change(
            source_key,
            f"request.required.{field}",
            "required_changed",
            ChangeType.CHANGED,
            ChangeSeverity.INFO,
            True,
            False,
        )
        for field in sorted(before - after)
    ]


def _constraint_changes(
    source_key: str,
    before_signature: dict[str, JsonValue],
    after_signature: dict[str, JsonValue],
    location: str,
) -> list[ChangeItem]:
    before = _nested_json_mapping(before_signature.get("constraints"))
    after = _nested_json_mapping(after_signature.get("constraints"))
    changes: list[ChangeItem] = []
    for field in sorted(before.keys() | after.keys()):
        old_constraints = before.get(field, {})
        new_constraints = after.get(field, {})
        for constraint in sorted(old_constraints.keys() | new_constraints.keys()):
            old_value = old_constraints.get(constraint)
            new_value = new_constraints.get(constraint)
            if old_value == new_value:
                continue
            changes.append(
                _semantic_change(
                    source_key,
                    f"{location}.{field}.{constraint}",
                    _constraint_semantic_type(constraint),
                    ChangeType.CHANGED,
                    _constraint_severity(constraint, old_value, new_value),
                    old_value,
                    new_value,
                )
            )
    return changes


def _response_status_changes(
    source_key: str,
    before_signature: dict[str, JsonValue],
    after_signature: dict[str, JsonValue],
) -> list[ChangeItem]:
    before = set(_json_strings(before_signature.get("all_codes")))
    after = set(_json_strings(after_signature.get("all_codes")))
    return [
        _semantic_change(
            source_key,
            f"responses.{code}",
            "response_status_changed",
            ChangeType.ADDED,
            ChangeSeverity.INFO,
            None,
            code,
        )
        for code in sorted(after - before)
    ]


def _semantic_change(
    source_key: str,
    field_path: str,
    semantic_type: str,
    change_type: ChangeType,
    severity: ChangeSeverity,
    before: JsonValue,
    after: JsonValue,
) -> ChangeItem:
    return _change(
        SourceKind.OPENAPI,
        source_key,
        change_type,
        severity,
        f"{source_key} · {field_path}",
        f"结构化变更: {field_path}",
        before,
        after,
        discriminator=f"{semantic_type}:{field_path}",
        semantic_type=semantic_type,
        field_path=field_path,
    )


def _contract_change_type(code: str) -> str:
    return {
        "OPERATION_REMOVED": "operation_removed",
        "REQUEST_REQUIRED_ADDED": "required_changed",
        "REQUEST_TYPE_CHANGED": "type_changed",
        "RESPONSE_TYPE_CHANGED": "type_changed",
        "SUCCESS_RESPONSE_REMOVED": "response_status_changed",
        "RESPONSE_FIELD_REMOVED": "field_removed",
    }.get(code, "schema_changed")


def _constraint_semantic_type(constraint: str) -> str:
    if constraint == "enum":
        return "enum_changed"
    if constraint in {"pattern", "format"}:
        return f"{constraint}_changed"
    if constraint in {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
    }:
        return f"{constraint}_changed"
    return "schema_changed"


def _constraint_severity(constraint: str, before: JsonValue, after: JsonValue) -> ChangeSeverity:
    if constraint == "enum" and isinstance(before, list) and isinstance(after, list):
        return (
            ChangeSeverity.BREAKING
            if set(map(str, before)) - set(map(str, after))
            else ChangeSeverity.WARNING
        )
    if constraint in {"minimum", "exclusiveMinimum", "minLength", "minItems"}:
        return _numeric_constraint_severity(before, after, increase_breaks=True)
    if constraint in {"maximum", "exclusiveMaximum", "maxLength", "maxItems"}:
        return _numeric_constraint_severity(before, after, increase_breaks=False)
    return ChangeSeverity.WARNING


def _numeric_constraint_severity(
    before: JsonValue, after: JsonValue, *, increase_breaks: bool
) -> ChangeSeverity:
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return ChangeSeverity.WARNING
    breaking = after > before if increase_breaks else after < before
    return ChangeSeverity.BREAKING if breaking else ChangeSeverity.WARNING


def _json_mapping(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _nested_json_mapping(value: JsonValue) -> dict[str, dict[str, JsonValue]]:
    return {
        str(key): child for key, child in _json_mapping(value).items() if isinstance(child, dict)
    }


def _json_strings(value: JsonValue) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _change(
    source_kind: SourceKind,
    source_key: str,
    change_type: ChangeType,
    severity: ChangeSeverity,
    label: str,
    detail: str,
    before: JsonValue = None,
    after: JsonValue = None,
    *,
    discriminator: str = "",
    semantic_type: str = "schema_changed",
    field_path: str | None = None,
) -> ChangeItem:
    digest = hashlib.sha256(
        f"{source_kind.value}|{source_key}|{change_type.value}|{discriminator}|{detail}".encode()
    ).hexdigest()[:20]
    return ChangeItem(
        key=digest,
        source_kind=source_kind,
        source_key=source_key,
        change_type=change_type,
        severity=severity,
        label=label,
        detail=detail,
        before=before,
        after=after,
        semantic_type=semantic_type,
        field_path=field_path,
    )


def _bounded_changes(changes: list[ChangeItem]) -> tuple[ChangeItem, ...]:
    if len(changes) > MAX_CHANGE_ITEMS:
        raise ImpactInputError("Schema Diff 变更项超过 5000 上限")
    return tuple(changes)


def _operation_signature(operation: Any) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
    return operation.request_signature, operation.response_signature


def _asset_category(target_type: TargetType) -> str:
    if target_type == TargetType.TEST_CASE:
        return "case"
    if target_type in {TargetType.OPENAPI_CONTRACT, TargetType.PACT_CONTRACT}:
        return "contract"
    return target_type.value


def _risk_label(severity: ChangeSeverity) -> str:
    return {
        ChangeSeverity.BREAKING: "high",
        ChangeSeverity.WARNING: "medium",
        ChangeSeverity.INFO: "normal",
    }[severity]


def _severity_rank(severity: ChangeSeverity) -> int:
    return {
        ChangeSeverity.INFO: 1,
        ChangeSeverity.WARNING: 2,
        ChangeSeverity.BREAKING: 3,
    }[severity]


def _maximum_severity(left: ChangeSeverity, right: ChangeSeverity) -> ChangeSeverity:
    return left if _severity_rank(left) >= _severity_rank(right) else right


def _matrix_row(
    change: ChangeItem,
    targets: set[tuple[TargetType, str]],
    selected: dict[tuple[TargetType, str], _SelectedAsset],
) -> dict[str, JsonValue]:
    counts = {"case": 0, "workflow": 0, "contract": 0, "performance": 0}
    for target in targets:
        category = _asset_category(selected[target].mapping.target_type)
        counts[category] += 1
    return {
        "change_key": change.key,
        "source_kind": change.source_kind.value,
        "source_key": change.source_key,
        "label": change.label,
        "severity": change.severity.value,
        "case_count": counts["case"],
        "workflow_count": counts["workflow"],
        "contract_count": counts["contract"],
        "performance_count": counts["performance"],
        "covered": bool(targets),
    }
