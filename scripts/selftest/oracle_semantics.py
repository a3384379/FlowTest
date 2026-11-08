"""Compare published native assertion meaning with its frozen source document.

This projection deliberately does not invoke the candidate compiler. Independent
scenario goldens still establish whether the source document itself is correct.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from scripts.selftest.contracts import Contract, OracleBinding, canonical_digest
from scripts.selftest.io import HarnessError, JsonObject, object_value, objects_value, text_value


class OracleSemantics(Contract):
    source_node_id: str
    expression: str
    operator: str
    assertion_type: Literal["comparison", "json_schema"]
    expected_digest: str
    expected_source_node_id: str | None = None
    expected_expression: str | None = None


def _native_semantics(config: JsonObject) -> OracleSemantics:
    assertion_type = config.get("assertion_type", "comparison")
    if assertion_type not in {"comparison", "json_schema"}:
        raise HarnessError("SELFTEST_PUBLISHED_ORACLE_SEMANTICS_CHANGED")
    return OracleSemantics(
        source_node_id=text_value(config.get("source_node_id")),
        expression=text_value(config.get("expression")),
        operator=text_value(config.get("operator", "equals")),
        assertion_type="json_schema" if assertion_type == "json_schema" else "comparison",
        expected_digest=canonical_digest(config.get("expected")),
        expected_source_node_id=_optional_text(config.get("expected_source_node_id")),
        expected_expression=_optional_text(config.get("expected_expression")),
    )


def _optional_text(value: object) -> str | None:
    return None if value is None else text_value(value)


def _design_semantics(oracle: JsonObject) -> OracleSemantics:
    kind = text_value(oracle["kind"])
    if kind not in {"status", "schema", "json_path", "expression"}:
        raise HarnessError("SELFTEST_PUBLISHED_ORACLE_SOURCE_UNSUPPORTED")
    expression = {"status": "status_code", "schema": "body"}.get(kind)
    return OracleSemantics(
        source_node_id="request",
        expression=expression if expression is not None else text_value(oracle["expression"]),
        operator="equals" if kind in {"status", "schema"} else text_value(oracle["operator"]),
        assertion_type="json_schema" if kind == "schema" else "comparison",
        expected_digest=canonical_digest(oracle.get("expected")),
    )


def _plan_semantics(oracle: JsonObject) -> OracleSemantics:
    source = oracle.get("expected_source")
    expected_source = object_value(source) if source is not None else None
    return OracleSemantics(
        source_node_id=text_value(oracle["step_id"]),
        expression=text_value(oracle["expression"]),
        operator=text_value(oracle["operator"]),
        assertion_type="json_schema" if oracle["kind"] == "schema" else "comparison",
        expected_digest=canonical_digest(oracle.get("expected")),
        expected_source_node_id=(
            text_value(expected_source["step_id"]) if expected_source is not None else None
        ),
        expected_expression=(
            text_value(expected_source["expression"]) if expected_source is not None else None
        ),
    )


def validate_published_oracles(
    definition: JsonObject,
    source: JsonObject,
    bindings: Sequence[OracleBinding],
    *,
    source_kind: Literal["design", "integration_plan"],
) -> None:
    nodes = objects_value(definition["nodes"])
    by_node = {text_value(item["id"]): item for item in nodes}
    oracles = objects_value(source["oracles"])
    by_oracle = {text_value(item["id"]): item for item in oracles}
    if len(by_node) != len(nodes) or len(by_oracle) != len(oracles):
        raise HarnessError("SELFTEST_PUBLISHED_ORACLE_SOURCE_DUPLICATE")
    _validate_binding_set(nodes, bindings)
    for binding in bindings:
        node, oracle = by_node.get(binding.node_id), by_oracle.get(binding.oracle_id)
        if node is None or node["type"] != "assert" or oracle is None:
            raise HarnessError("SELFTEST_PUBLISHED_ORACLE_MISSING")
        expected = _design_semantics(oracle) if source_kind == "design" else _plan_semantics(oracle)
        _validate_semantics(object_value(node["config"]), binding, expected)


def _validate_binding_set(nodes: list[JsonObject], bindings: Sequence[OracleBinding]) -> None:
    expected_nodes = {item.node_id for item in bindings}
    actual_nodes = {text_value(item["id"]) for item in nodes if item["type"] == "assert"}
    if (
        actual_nodes != expected_nodes
        or len(expected_nodes) != len(bindings)
        or len({item.oracle_id for item in bindings}) != len(bindings)
    ):
        raise HarnessError("SELFTEST_PUBLISHED_ORACLE_SET_CHANGED")


def _validate_semantics(
    config: JsonObject, binding: OracleBinding, expected: OracleSemantics
) -> None:
    if (
        _native_semantics(config) != expected
        or binding.expression != expected.expression
        or binding.expected_value_digest != expected.expected_digest
    ):
        raise HarnessError("SELFTEST_PUBLISHED_ORACLE_SEMANTICS_CHANGED")
