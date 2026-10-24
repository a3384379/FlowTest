"""Conservative trusted-H request bounds; unknown control shapes fail closed."""

from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    integer_value,
    object_value,
    objects_value,
    text_value,
)


def _number(value: object) -> int:
    result = integer_value(value)
    if result < 0 or result > 100000:
        raise HarnessError("SELFTEST_REQUEST_BUDGET_UNSUPPORTED")
    return result


def _simple_graph_bound(definition: JsonObject) -> int:
    if definition.get("regions"):
        raise HarnessError("SELFTEST_REQUEST_BUDGET_UNSUPPORTED")
    nodes = objects_value(definition["nodes"])
    identifiers = {text_value(node["id"]) for node in nodes}
    edges = objects_value(definition.get("edges", []))
    remaining: dict[str, set[str]] = {identifier: set() for identifier in identifiers}
    for edge in edges:
        source, target = text_value(edge["source"]), text_value(edge["target"])
        if source not in identifiers or target not in identifiers:
            raise HarnessError("SELFTEST_REQUEST_BUDGET_UNSUPPORTED")
        remaining[target].add(source)
    while remaining:
        ready = {key for key, dependencies in remaining.items() if not dependencies}
        if not ready:
            raise HarnessError("SELFTEST_REQUEST_BUDGET_UNSUPPORTED")
        remaining = {
            key: dependencies - ready for key, dependencies in remaining.items() if key not in ready
        }
    return sum(_node_bound(node) for node in nodes)


def _node_bound(node: JsonObject) -> int:
    if node["type"] not in {"start", "api", "assert", "extract", "variable", "end"}:
        raise HarnessError("SELFTEST_REQUEST_BUDGET_UNSUPPORTED")
    if node["type"] != "api":
        return 0
    config = object_value(node["config"])
    if config.get("polling") is not None:
        raise HarnessError("SELFTEST_REQUEST_BUDGET_UNSUPPORTED")
    return (1 + _number(config.get("max_retries", 0))) * (
        1 + _number(node.get("cleanup_retry_budget", 0))
    )


def native_request_bound(definition: JsonObject) -> int:
    policy = object_value(definition["run_policy"])
    request = policy.get("request_budget")
    cleanup = policy.get("cleanup_request_budget")
    if request is None:
        return _simple_graph_bound(definition)
    cleanup_bound = (
        _number(cleanup)
        if cleanup not in (None, 0)
        else sum(
            _node_bound(node)
            for node in objects_value(definition["nodes"])
            if node.get("phase") == "cleanup"
        )
    )
    return _number(request) + cleanup_bound
