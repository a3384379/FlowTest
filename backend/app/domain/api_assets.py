import re
from dataclasses import dataclass
from enum import StrEnum

from app.domain.scopes import HeaderScope, ResolvedValue, VariableScope, resolve_variables

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

TEMPLATE_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}")
REDACTED_VALUE = "******"


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class BodyKind(StrEnum):
    NONE = "none"
    JSON = "json"
    RAW = "raw"
    FORM = "form"
    MULTIPART = "multipart"


class AuthKind(StrEnum):
    NONE = "none"
    BEARER = "bearer"
    BASIC = "basic"
    API_KEY = "api_key"


@dataclass(frozen=True, slots=True)
class QueryParameterSpec:
    name: str
    value: str
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class APIVersionSpec:
    method: HttpMethod
    path: str
    query_parameters: tuple[QueryParameterSpec, ...]
    headers: dict[str, str]
    body_kind: BodyKind
    body: JsonValue
    auth_kind: AuthKind
    auth_config: dict[str, str]


@dataclass(frozen=True, slots=True)
class ResolvedHeader:
    name: str
    value: str
    source: HeaderScope


def merge_headers(layers: dict[HeaderScope, dict[str, str]]) -> dict[str, ResolvedHeader]:
    resolved: dict[str, ResolvedHeader] = {}
    for scope in HeaderScope:
        for name, value in layers.get(scope, {}).items():
            resolved[name.lower()] = ResolvedHeader(name=name, value=value, source=scope)
    return resolved


def render_template(value: str, variables: dict[str, ResolvedValue]) -> str:
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        resolved = variables.get(name)
        if resolved is None:
            missing.add(name)
            return match.group(0)
        return resolved.value

    rendered = TEMPLATE_PATTERN.sub(replace, value)
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"Unresolved variables: {names}")
    return rendered


def render_json(value: JsonValue, variables: dict[str, ResolvedValue]) -> JsonValue:
    if isinstance(value, str):
        return render_template(value, variables)
    if isinstance(value, list):
        return [render_json(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: render_json(item, variables) for key, item in value.items()}
    return value


def build_variables(
    *,
    global_values: dict[str, str],
    project_values: dict[str, str],
    environment_values: dict[str, str],
    runtime_values: dict[str, str],
) -> dict[str, ResolvedValue]:
    return resolve_variables(
        {
            VariableScope.GLOBAL: global_values,
            VariableScope.PROJECT: project_values,
            VariableScope.ENVIRONMENT: environment_values,
            VariableScope.RUNTIME: runtime_values,
        }
    )
