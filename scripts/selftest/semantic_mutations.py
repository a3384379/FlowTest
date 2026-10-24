"""Synthetic negative artifacts; these deliberate changes are never normal generation."""

from copy import deepcopy

from scripts.selftest.io import HarnessError, JsonObject, object_value, objects_value
from scripts.selftest.semantic_contracts import SemanticVariant


def mutate_assertion(definition: JsonObject, variant: SemanticVariant) -> JsonObject:
    result = deepcopy(definition)
    if variant == "positive_control":
        return result
    nodes = objects_value(result["nodes"])
    schemas = [
        node
        for node in nodes
        if node["type"] == "assert"
        and object_value(node["config"]).get("assertion_type") == "json_schema"
    ]
    if len(schemas) != 1:
        raise HarnessError("SELFTEST_SEMANTIC_SCHEMA_NODE_SET_CHANGED")
    selected = schemas[0]
    config = object_value(selected["config"])
    if variant == "missing_assertion":
        _remove_node(result, selected)
    elif variant == "wrong_field":
        config.update(
            {
                "expression": "body.code",
                "assertion_type": "comparison",
                "operator": "equals",
                "expected": 0,
            }
        )
    elif variant == "wrong_operator":
        config.update({"assertion_type": "comparison", "operator": "not_equals"})
    else:
        config.update(
            {
                "assertion_type": "comparison",
                "expected_source_node_id": "request",
                "expected_expression": "body",
            }
        )
    return result


def _remove_node(definition: JsonObject, selected: JsonObject) -> None:
    edges = objects_value(definition["edges"])
    inbound = [edge for edge in edges if edge["target"] == selected["id"]]
    outbound = [edge for edge in edges if edge["source"] == selected["id"]]
    if len(inbound) != 1 or len(outbound) != 1:
        raise HarnessError("SELFTEST_SEMANTIC_MUTATION_GRAPH_CHANGED")
    inbound[0]["target"] = outbound[0]["target"]
    definition["edges"] = [edge for edge in edges if edge["id"] != outbound[0]["id"]]
    definition["nodes"] = [
        node for node in objects_value(definition["nodes"]) if node["id"] != selected["id"]
    ]
