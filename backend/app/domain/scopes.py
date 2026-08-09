from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class VariableScope(StrEnum):
    GLOBAL = "global"
    PROJECT = "project"
    ENVIRONMENT = "environment"
    WORKFLOW = "workflow"
    DATASET = "dataset"
    RUNTIME = "runtime"


class HeaderScope(StrEnum):
    SYSTEM = "system"
    PROJECT = "project"
    ENVIRONMENT = "environment"
    WORKFLOW = "workflow"
    API = "api"
    RUNTIME = "runtime"


VARIABLE_PRECEDENCE = tuple(VariableScope)
HEADER_PRECEDENCE = tuple(HeaderScope)


@dataclass(frozen=True, slots=True)
class ResolvedValue:
    value: str
    source: StrEnum


def resolve_scoped_values[ScopeT: StrEnum](
    precedence: tuple[ScopeT, ...],
    values: Mapping[ScopeT, Mapping[str, str]],
) -> dict[str, ResolvedValue]:
    resolved: dict[str, ResolvedValue] = {}
    for scope in precedence:
        for key, value in values.get(scope, {}).items():
            resolved[key] = ResolvedValue(value=value, source=scope)
    return resolved


def resolve_variables(
    values: Mapping[VariableScope, Mapping[str, str]],
) -> dict[str, ResolvedValue]:
    return resolve_scoped_values(VARIABLE_PRECEDENCE, values)


def resolve_headers(
    values: Mapping[HeaderScope, Mapping[str, str]],
) -> dict[str, ResolvedValue]:
    return resolve_scoped_values(HEADER_PRECEDENCE, values)
