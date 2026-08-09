import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

import jmespath
from jmespath.exceptions import JMESPathError
from pydantic import JsonValue

from app.engine.contracts import (
    FieldMapping,
    MappingTargetLocation,
    MappingTransformKind,
)
from app.engine.scheduler import ExecutionContext


@dataclass(frozen=True, slots=True)
class MappingResolutionError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class ResolvedFieldMapping:
    location: MappingTargetLocation
    key: str
    value: JsonValue
    source_node_id: str
    source_path: str


def resolve_field_mappings(
    mappings: Iterable[FieldMapping],
    context: ExecutionContext,
) -> tuple[ResolvedFieldMapping, ...]:
    resolved: list[ResolvedFieldMapping] = []
    for mapping in mappings:
        source = context.output_of(mapping.source.node_id)
        try:
            value = cast(JsonValue, jmespath.search(mapping.source.path, source))
        except JMESPathError as error:
            raise MappingResolutionError(
                code="INVALID_MAPPING_PATH",
                message=f"映射表达式 {mapping.source.path} 无效",
            ) from error
        if value is None:
            raise MappingResolutionError(
                code="MAPPING_SOURCE_MISSING",
                message=f"映射表达式 {mapping.source.path} 未找到值",
            )
        resolved.append(
            ResolvedFieldMapping(
                location=mapping.target.location,
                key=mapping.target.key,
                value=_transform(value, mapping.transform.kind, mapping.transform.template),
                source_node_id=mapping.source.node_id,
                source_path=mapping.source.path,
            )
        )
    return tuple(resolved)


def _transform(value: JsonValue, kind: MappingTransformKind, template: str) -> JsonValue:
    if kind is MappingTransformKind.IDENTITY:
        return value
    if template == "{{value}}":
        return value
    rendered = template.replace("{{value}}", _stringify(value))
    return rendered


def _stringify(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
