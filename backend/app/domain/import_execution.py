"""Execution projections for imported contracts, without infrastructure access."""

import json
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit

from app.domain.api_assets import TEMPLATE_PATTERN, JsonValue, QueryParameterSpec, render_template
from app.domain.scopes import ResolvedValue


def render_import_query(
    parameters: Sequence[QueryParameterSpec],
    variables: dict[str, ResolvedValue],
    contract: Mapping[str, JsonValue],
) -> list[tuple[str, str]]:
    declarations = contract.get("parameters", [])
    schemas = (
        {
            str(item.get("name")): item
            for item in declarations
            if isinstance(item, dict) and item.get("location") == "query"
        }
        if isinstance(declarations, list)
        else {}
    )
    result: list[tuple[str, str]] = []
    for item in parameters:
        if not item.enabled:
            continue
        name = render_template(item.name, variables)
        value = render_template(item.value, variables)
        declaration = schemas.get(item.name, {})
        schema = declaration.get("schema", {})
        is_array = isinstance(schema, dict) and schema.get("type") == "array"
        if is_array and TEMPLATE_PATTERN.fullmatch(item.value):
            result.extend((name, part) for part in serialize_array(value, declaration))
        else:
            result.append((name, value))
    return result


def serialize_array(value: str, parameter: Mapping[str, JsonValue]) -> list[str]:
    try:
        items = json.loads(value)
    except (ValueError, TypeError) as error:
        raise ValueError("数组变量必须绑定 JSON 标量数组") from error
    if not isinstance(items, list) or len(items) > 1000:
        raise ValueError("数组变量必须是最多 1000 项的 JSON 数组")
    if any(isinstance(item, (dict, list)) for item in items):
        raise ValueError("复杂对象数组的 query 序列化需要人工配置")
    encoded = [
        item if isinstance(item, str) else json.dumps(item, allow_nan=False) for item in items
    ]
    style = parameter.get("style") or "form"
    explode = parameter.get("explode")
    if explode is None:
        explode = style == "form"
    if style == "form" and explode:
        return encoded
    separators = {"form": ",", "spaceDelimited": " ", "pipeDelimited": "|", "tabDelimited": "\t"}
    if style not in separators or explode:
        raise ValueError("该数组序列化样式需要人工配置")
    return [separators[str(style)].join(encoded)] if encoded else []


def imported_execution_path(base_url: str, path: str, contract: Mapping[str, JsonValue]) -> str:
    """Remove only an explicitly recorded Swagger prefix already present in the target."""
    warnings = contract.get("warnings", [])
    if not isinstance(warnings, list):
        return path
    for warning in warnings:
        if not isinstance(warning, str) or not warning.startswith("import_base_path="):
            continue
        prefix = warning.removeprefix("import_base_path=").rstrip("/")
        if (
            prefix
            and urlsplit(base_url).path.rstrip("/").endswith(prefix)
            and path.startswith(prefix + "/")
        ):
            return path[len(prefix) :]
    return path
