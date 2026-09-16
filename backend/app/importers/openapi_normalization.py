"""Bounded source-dialect adaptation before strict canonical validation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, cast
from urllib.parse import unquote

from app.domain.api_assets import JsonValue
from app.domain.canonical_schemas import CanonicalSchemaValidator
from app.importers.openapi_dialects import source_dialect

SCHEMA_KEYS = frozenset(
    [
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
        "example",
        "examples",
        "default",
        "const",
    ]
)


class OpenAPIResourceError(ValueError):
    """The source exceeded a bounded normalization resource limit."""


@dataclass(frozen=True, slots=True)
class ImportDiagnostic:
    source_version: str
    source_dialect: str
    method: str
    endpoint: str
    operation_id: str | None
    source_path: str
    canonical_path: str
    keyword: str
    severity: Literal["FATAL", "WARNING", "INFO"]
    code: str
    message: str
    normalized_as: str
    suggested_fix: str = "请核对源文档与导入后的契约; 未表达的约束需人工补充。"
    value_preview: str | None = None
    semantic_loss: bool = False

    def as_json(self) -> dict[str, JsonValue]:
        from dataclasses import asdict

        return cast(dict[str, JsonValue], asdict(self))


def mapping(value: object) -> dict[str, object]:
    return {str(key): child for key, child in value.items()} if isinstance(value, dict) else {}


def sequence(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def pointer(path: str, key: str) -> str:
    return path + "/" + key.replace("~", "~0").replace("/", "~1")


@dataclass(slots=True)
class SourceNormalizer:
    document: Mapping[str, object]
    method: str
    endpoint: str
    operation_id: str | None
    diagnostics: list[ImportDiagnostic] = field(default_factory=list)
    nodes: int = 0
    partial: bool = False
    repair_legacy_refs: bool = True

    @property
    def dialect(self) -> str:
        return source_dialect(self.document)

    @property
    def modern_schema(self) -> bool:
        return self.dialect in {"OPENAPI_3_1", "OPENAPI_3_2"}

    def warn(
        self,
        source: str,
        canonical: str,
        keyword: str,
        code: str,
        normalized_as: str,
        *,
        loss: bool = False,
    ) -> None:
        self.partial |= loss
        if len(self.diagnostics) >= 500:
            raise OpenAPIResourceError("兼容性诊断超过每个接口 500 条的资源预算")
        self.diagnostics.append(
            ImportDiagnostic(
                source_version=(
                    "swagger-" + str(self.document.get("swagger"))
                    if self.dialect == "SWAGGER_2_0"
                    else "openapi-" + str(self.document.get("openapi"))
                ),
                source_dialect=self.dialect,
                method=self.method,
                endpoint=self.endpoint,
                operation_id=self.operation_id,
                source_path=source,
                canonical_path=canonical,
                keyword=keyword,
                severity="WARNING",
                code=code,
                message=(
                    "部分源约束未进入 Canonical Contract, 存在语义损失。"
                    if loss
                    else "源文档已进行兼容性规范化。"
                ),
                normalized_as=normalized_as,
                semantic_loss=loss,
            )
        )

    def resolve(
        self,
        value: object,
        source: str,
        canonical: str,
        stack: tuple[str, ...] = (),
        schema_reference: bool = False,
    ) -> tuple[dict[str, object], str, tuple[str, ...]]:
        result = {"not": {}} if value is False else mapping(value)
        reference = result.get("$ref")
        if not isinstance(reference, str):
            return result, source, stack
        if reference in stack or len(stack) >= 24:
            self.warn(
                pointer(source, "$ref"),
                canonical,
                "$ref",
                "REF_CYCLE_OR_BUDGET",
                "递归引用截断; 引用位置保留在 source_path",
                loss=True,
            )
            return self.unresolved_siblings(result, schema_reference), source, stack
        if not reference.startswith("#/"):
            self.warn(
                pointer(source, "$ref"),
                canonical,
                "$ref",
                "EXTERNAL_REF_NOT_RESOLVED",
                "未联网解析; 请在源文档中将此引用内联",
                loss=True,
            )
            return self.unresolved_siblings(result, schema_reference), source, stack
        current: object = self.document
        for part in unquote(reference[2:]).split("/"):
            current = mapping(current).get(part.replace("~1", "/").replace("~0", "~"))
        if current is None:
            repaired = self.legacy_reference(reference, source, canonical)
            if repaired is not None:
                current, reference = repaired
        if not isinstance(current, (dict, bool)):
            self.warn(
                pointer(source, "$ref"),
                canonical,
                "$ref",
                "REF_NOT_FOUND",
                "未找到内部引用; 保留其他可识别字段",
                loss=True,
            )
            return self.unresolved_siblings(result, schema_reference), source, stack
        resolved, origin, refs = self.resolve(
            current, reference, canonical, (*stack, reference), schema_reference
        )
        siblings = {key: item for key, item in result.items() if key != "$ref"}
        if siblings:
            # Schema $ref siblings in 3.1 are conjunctions, never overwrites.
            if self.modern_schema and schema_reference:
                return {"allOf": [resolved, siblings]}, source, refs
            self.warn(
                source,
                canonical,
                "$ref",
                "REF_SIBLINGS_IGNORED",
                "按 2.0/3.0 Reference Object 语义忽略同级字段",
            )
        return resolved, origin, refs

    def legacy_reference(
        self, reference: str, source: str, canonical: str
    ) -> tuple[object, str] | None:
        if not self.repair_legacy_refs or not reference.startswith("#/definitions/"):
            return None
        name = unquote(reference.removeprefix("#/definitions/"))
        definitions = mapping(self.document.get("definitions"))
        if "/" not in name or name not in definitions:
            return None
        repaired = pointer("#/definitions", name)
        self.warn(
            pointer(source, "$ref"), canonical, "$ref", "LEGACY_REF_ESCAPING_REPAIRED", repaired
        )
        return definitions[name], repaired

    def unresolved_siblings(
        self, schema: dict[str, object], schema_reference: bool
    ) -> dict[str, object]:
        if self.modern_schema and schema_reference:
            return {key: value for key, value in schema.items() if key != "$ref"}
        return {}

    def schema(
        self,
        value: object,
        source: str,
        canonical: str,
        *,
        stack: tuple[str, ...] = (),
        depth: int = 0,
    ) -> dict[str, JsonValue]:
        self.nodes += 1
        if self.nodes > 10_000:
            raise OpenAPIResourceError("接口 Schema 超过 10000 节点预算")
        if depth >= 22:
            self.warn(
                source,
                canonical,
                "$schema",
                "SCHEMA_DEPTH_BUDGET",
                "深层 Schema 截断为空约束",
                loss=True,
            )
            return {}
        if isinstance(value, bool):
            return {} if value else {"not": {}}
        raw, source, stack = self.resolve(value, source, canonical, stack, True)
        result: dict[str, JsonValue] = {}
        for key, item in raw.items():
            if key not in SCHEMA_KEYS:
                self.warn(
                    pointer(source, key),
                    canonical + "." + key,
                    key,
                    "SOURCE_KEYWORD_NOT_REPRESENTED",
                    "该字段仅保留在源文档中",
                    loss=not key.startswith("x-")
                    and key not in {"$defs", "definitions", "xml", "externalDocs", "deprecated"},
                )
                continue
            if not self.json_keyword(item, pointer(source, key), canonical, key):
                continue
            result[key] = self.schema_item(
                key, item, pointer(source, key), canonical + "." + key, stack, depth
            )
        self.normalize_scalars(result, source, canonical)
        self.validate_projection(result, source, canonical)
        return result

    def json_keyword(self, value: object, source: str, canonical: str, key: str) -> bool:
        if key in {"properties", "items", "not", "oneOf", "anyOf", "allOf", "additionalProperties"}:
            return True
        try:
            json.dumps(value, ensure_ascii=False, allow_nan=False)
            return True
        except (TypeError, ValueError):
            self.warn(
                source,
                canonical + "." + key,
                key,
                "SOURCE_VALUE_NOT_JSON",
                "忽略非 JSON 值; YAML 日期请使用引号包围, 非有限数值请修正",
                loss=True,
            )
            return False

    def schema_item(
        self,
        key: str,
        value: object,
        source: str,
        canonical: str,
        stack: tuple[str, ...],
        depth: int,
    ) -> JsonValue:
        if key == "properties":
            if len(mapping(value)) > 500:
                raise OpenAPIResourceError("Schema 超过 500 个属性预算")
            return {
                name: self.schema(
                    child,
                    pointer(source, name),
                    canonical + "." + name,
                    stack=stack,
                    depth=depth + 1,
                )
                for name, child in mapping(value).items()
                if self.property_name(name, source, canonical)
            }
        if key in {"oneOf", "anyOf", "allOf"}:
            if len(sequence(value)) > 50:
                raise OpenAPIResourceError("Schema 超过 50 个组合分支预算")
            return [
                self.schema(
                    child,
                    pointer(source, str(index)),
                    f"{canonical}[{index}]",
                    stack=stack,
                    depth=depth + 1,
                )
                for index, child in enumerate(sequence(value))
            ]
        if key in {"items", "not"} or (key == "additionalProperties" and isinstance(value, dict)):
            return self.schema(value, source, canonical, stack=stack, depth=depth + 1)
        return cast(JsonValue, value)

    def property_name(self, name: str, source: str, canonical: str) -> bool:
        if name and len(name) <= 160 and re.search(r"[\x00-\x1f\x7f]", name) is None:
            return True
        self.warn(
            pointer(source, name),
            canonical + "." + name,
            "properties",
            "SOURCE_PROPERTY_NOT_REPRESENTED",
            "移除不满足安全约束的属性名称",
            loss=True,
        )
        return False

    def normalize_scalars(self, result: dict[str, JsonValue], source: str, canonical: str) -> None:
        for key in ("title", "description"):
            value = result.get(key)
            if isinstance(value, str):
                normalized = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
                if normalized != value:
                    result[key] = normalized
                    self.warn(
                        pointer(source, key),
                        canonical + "." + key,
                        key,
                        "SCHEMA_TEXT_WHITESPACE_NORMALIZED",
                        "格式空白及 C0/DEL 控制字符转换为空格",
                    )
        if result.get("type") == "file" and self.dialect == "SWAGGER_2_0":
            result.update(type="string", format="binary")
        discriminator = result.get("discriminator")
        if isinstance(discriminator, str) and self.dialect == "SWAGGER_2_0":
            result["discriminator"] = {"propertyName": discriminator}
        for inclusive, exclusive in [
            ("minimum", "exclusiveMinimum"),
            ("maximum", "exclusiveMaximum"),
        ]:
            flag = result.get(exclusive)
            if isinstance(flag, bool) and not self.modern_schema:
                result.pop(exclusive)
                if flag and isinstance(result.get(inclusive), (int, float)):
                    result[exclusive] = result.pop(inclusive)

    def validate_projection(
        self, result: dict[str, JsonValue], source: str, canonical: str
    ) -> None:
        # Children have already been normalized. Invalid source constraints are diagnosed
        # and removed locally, then the resulting projection is strictly validated again.
        required = result.get("required")
        if isinstance(required, list) and any(
            str(name) not in mapping(result.get("properties")) for name in required
        ):
            self.partial = True
            self.warn(
                source + "/required",
                canonical + ".required",
                "required",
                "REQUIRED_WITHOUT_LOCAL_PROPERTIES",
                "保留 required 约束; 属性可能由 composition 或 additionalProperties 定义",
            )
        issues = CanonicalSchemaValidator().issues(result, allow_partial_required=self.partial)
        for issue in issues:
            if "budget" in issue.reason:
                raise OpenAPIResourceError("Schema 超过 Canonical 安全资源预算")
            if issue.path != "$":
                raise OpenAPIResourceError("Schema 规范化后的嵌套约束无法安全处理")
            keys = (
                ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")
                if issue.keyword == "bounds"
                else (issue.keyword,)
            )
            for key in keys:
                result.pop(key, None)
            self.warn(
                pointer(source, issue.keyword),
                canonical + "." + issue.keyword,
                issue.keyword,
                "SOURCE_CONSTRAINT_NOT_REPRESENTED",
                "移除无法安全表达的约束: " + issue.reason,
                loss=True,
            )
        CanonicalSchemaValidator().validate(result, allow_partial_required=self.partial)
