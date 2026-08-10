import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from pydantic import JsonValue


class MockTemplateError(ValueError):
    """Raised when a mock path or response template is invalid."""


@dataclass(frozen=True, slots=True)
class MockRequestContext:
    path: Mapping[str, str]
    query: Mapping[str, str]
    headers: Mapping[str, str]
    body: JsonValue


_PATH_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_PLACEHOLDER = re.compile(r"\{\{\s*(path|query|header|body)\.([A-Za-z0-9_.-]{1,256})\s*\}\}")


def compile_mock_path(pattern: str) -> re.Pattern[str]:
    normalized = normalize_mock_path(pattern)
    names: set[str] = set()
    parts: list[str] = []
    for segment in normalized.strip("/").split("/") if normalized != "/" else []:
        if segment.startswith("{") and segment.endswith("}"):
            name = segment[1:-1]
            if not _PATH_SEGMENT.fullmatch(name) or name in names:
                raise MockTemplateError("Mock 路径参数名称无效或重复")
            names.add(name)
            parts.append(f"(?P<{name}>[^/]+)")
        elif "{" in segment or "}" in segment:
            raise MockTemplateError("Mock 路径参数必须占据完整路径段")
        else:
            parts.append(re.escape(segment))
    suffix = "/".join(parts)
    return re.compile(f"^/{suffix}$" if suffix else r"^/$")


def normalize_mock_path(pattern: str) -> str:
    normalized = pattern.strip()
    if not normalized.startswith("/") or len(normalized) > 1024 or "//" in normalized:
        raise MockTemplateError("Mock 路径必须以 / 开头且不得包含空路径段")
    if "?" in normalized or "#" in normalized or "\\" in normalized:
        raise MockTemplateError("Mock 路径不能包含 Query、Fragment 或反斜杠")
    return normalized.rstrip("/") or "/"


def render_mock_template(template: JsonValue, context: MockRequestContext) -> JsonValue:
    if isinstance(template, dict):
        return {key: render_mock_template(value, context) for key, value in template.items()}
    if isinstance(template, list):
        return [render_mock_template(value, context) for value in template]
    if not isinstance(template, str):
        return template
    exact = _PLACEHOLDER.fullmatch(template)
    if exact:
        return _resolve_placeholder(exact.group(1), exact.group(2), context)
    return _PLACEHOLDER.sub(
        lambda match: _string_value(_resolve_placeholder(match.group(1), match.group(2), context)),
        template,
    )


def match_mock_conditions(
    expected_query: Mapping[str, str],
    expected_headers: Mapping[str, str],
    context: MockRequestContext,
) -> bool:
    headers = {name.lower(): value for name, value in context.headers.items()}
    return all(context.query.get(name) == value for name, value in expected_query.items()) and all(
        headers.get(name.lower()) == value for name, value in expected_headers.items()
    )


def _resolve_placeholder(source: str, path: str, context: MockRequestContext) -> JsonValue:
    root: object = {
        "path": context.path,
        "query": context.query,
        "header": {name.lower(): value for name, value in context.headers.items()},
        "body": context.body,
    }[source]
    segments = path.split(".")
    if source == "header":
        segments = [path.lower()]
    value = root
    for segment in segments:
        if isinstance(value, Mapping) and segment in value:
            value = value[segment]
            continue
        raise MockTemplateError(f"Mock 模板变量不存在: {source}.{path}")
    return cast(JsonValue, value)


def _string_value(value: JsonValue) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise MockTemplateError("对象或数组变量必须占据完整模板值")
