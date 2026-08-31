"""Pure sensitive-value checks shared by controlled FlowSpec proposal paths."""

from __future__ import annotations

import re

import jmespath
from jmespath.exceptions import JMESPathError

from app.domain.flow_spec import FlowSpec
from app.domain.flow_spec_v2 import FlowSpecV2
from app.domain.test_contexts import first_sensitive_value, is_sensitive_identifier

_SECRET_TEMPLATE = re.compile(r"(?:\{\{[^{}]+\}\}|\$\{[^{}]+\})")
_SECRET_REFERENCE = re.compile(r"secret://[A-Za-z0-9._:/-]+")


def contains_sensitive_flow_spec_value(spec: FlowSpec | FlowSpecV2) -> bool:
    """Reject credentials and correlated literals without returning their values."""

    if first_sensitive_value(spec.model_dump(mode="json")) is not None:
        return True
    if any(is_sensitive_identifier(name) for name in spec.variables):
        return True
    for parameter in spec.parameters:
        if parameter.value is not None and is_sensitive_identifier(parameter.name):
            return True
    if any(_has_sensitive_mapping_literal(node.model_dump(mode="json")) for node in spec.nodes):
        return True
    if any(
        _has_sensitive_mapping_literal(assertion.model_dump(mode="json"))
        for assertion in spec.assertions
    ):
        return True
    return any(
        _has_sensitive_edge_mapping(mapping) for edge in spec.edges for mapping in edge.mappings
    )


def contains_unsafe_jmespath_literal(expression: str) -> bool:
    try:
        parsed = jmespath.compile(expression).parsed
    except JMESPathError:
        return True
    return _contains_unsafe_jmespath_ast(parsed)


def _has_sensitive_edge_mapping(value: object) -> bool:
    target = getattr(value, "target", None)
    transform = getattr(value, "transform", None)
    source = getattr(value, "source", None)
    target_key = getattr(target, "key", None)
    if not isinstance(target_key, str) or not is_sensitive_identifier(target_key):
        return False
    transform_kind = getattr(getattr(transform, "kind", None), "value", None)
    if transform_kind == "template":
        return _contains_unsafe_literal(getattr(transform, "template", None))
    if transform_kind == "identity":
        source_path = getattr(source, "path", None)
        return not isinstance(source_path, str) or contains_unsafe_jmespath_literal(source_path)
    return False


def _has_sensitive_mapping_literal(value: object) -> bool:
    if isinstance(value, list):
        return any(_has_sensitive_mapping_literal(item) for item in value)
    if not isinstance(value, dict):
        return False
    expected_expression = value.get("expected_expression")
    if isinstance(expected_expression, str) and contains_unsafe_jmespath_literal(
        expected_expression
    ):
        return True
    for identifier_field, literal_field in (
        ("name", "value"),
        ("key", "value"),
        ("input", "expression"),
        ("expression", "expected"),
        ("query_ref", "expected"),
    ):
        named_value = value.get(identifier_field)
        if (
            isinstance(named_value, str)
            and is_sensitive_identifier(named_value)
            and _contains_unsafe_literal(value.get(literal_field))
        ):
            return True
    variable = value.get("variable")
    expression = value.get("expression")
    if (
        isinstance(variable, str)
        and is_sensitive_identifier(variable)
        and isinstance(expression, str)
        and contains_unsafe_jmespath_literal(expression)
    ):
        return True
    return any(
        (is_sensitive_identifier(str(name)) and _contains_unsafe_literal(child))
        or _has_sensitive_mapping_literal(child)
        for name, child in value.items()
    )


def _contains_unsafe_literal(value: object) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, str):
        return (
            _SECRET_REFERENCE.fullmatch(value) is None and _SECRET_TEMPLATE.fullmatch(value) is None
        )
    if isinstance(value, dict):
        return any(_contains_unsafe_literal(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_unsafe_literal(child) for child in value)
    return True


def _contains_unsafe_jmespath_ast(value: object) -> bool:
    if isinstance(value, list):
        return any(_contains_unsafe_jmespath_ast(child) for child in value)
    if not isinstance(value, dict):
        return False
    if value.get("type") == "literal" and _contains_unsafe_literal(value.get("value")):
        return True
    return _contains_unsafe_jmespath_ast(value.get("children"))
