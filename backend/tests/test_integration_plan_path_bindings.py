"""Explicit, evidenced path bindings reuse native workflow variables."""

import pytest
from test_s50_integration_plans import _golden_plan

from app.domain.integration_plans import (
    IntegrationPlan,
    compile_integration_plan,
    seal_integration_plan,
)


def _path_plan() -> IntegrationPlan:
    plan = _golden_plan()
    original = next(item for item in plan.bindings if item.target.step_id == "orders-query")
    binding = original.model_copy(
        update={"target": original.target.model_copy(update={"location": "path"})}
    )
    return seal_integration_plan(
        plan.model_copy(
            update={
                "operations": [
                    operation.model_copy(update={"path": f"/orders/{{{binding.target.key}}}"})
                    if operation.ref == "orders.query"
                    else operation
                    for operation in plan.operations
                ],
                "bindings": [binding if item.id == original.id else item for item in plan.bindings],
            }
        )
    )


def test_path_binding_compiles_to_existing_variable_mapping_and_keeps_all_oracles() -> None:
    path_plan = _path_plan()
    compilation = compile_integration_plan(path_plan)

    assert compilation.importable, [item.code for item in compilation.diagnostics]
    assert compilation.flow_spec is not None
    mappings = [mapping for edge in compilation.flow_spec.edges for mapping in edge.mappings]
    applied = next(item for item in mappings if item.target.node_id == "orders-query")
    assert applied.target.location.value == "variable"
    assert applied.target.key == "id"
    capture = next(
        node for node in compilation.flow_spec.nodes if node.id == applied.source.node_id
    )
    assert capture.kind == "extract"
    binding = next(item for item in path_plan.bindings if item.target.location == "path")
    assert capture.config["variable"] == binding.capture_variable
    assert sum(node.kind == "assert" for node in compilation.flow_spec.nodes) == len(
        path_plan.oracles
    )


@pytest.mark.parametrize(
    ("variant", "code"),
    [
        ("missing", "PATH_BINDING_REQUIRED"),
        ("duplicate", "PATH_BINDING_TARGET_DUPLICATE"),
        ("wrong-key", "PATH_BINDING_TARGET_UNKNOWN"),
        ("cookie", "BINDING_TARGET_RUNTIME_UNSUPPORTED"),
    ],
)
def test_missing_ambiguous_unknown_path_and_cookie_bindings_remain_blocked(
    variant: str, code: str
) -> None:
    plan = _path_plan()
    path = next(item for item in plan.bindings if item.target.location == "path")
    bindings = [item for item in plan.bindings if item.id != path.id]
    if variant == "duplicate":
        bindings.extend([path, path.model_copy(update={"id": "duplicate-path"})])
    elif variant == "wrong-key":
        bindings.append(
            path.model_copy(update={"target": path.target.model_copy(update={"key": "unknown"})})
        )
    elif variant == "cookie":
        bindings.append(
            path.model_copy(
                update={"target": path.target.model_copy(update={"location": "cookie"})}
            )
        )
    changed = seal_integration_plan(plan.model_copy(update={"bindings": bindings}))

    compilation = compile_integration_plan(changed)

    assert not compilation.importable
    assert code in {item.code for item in compilation.diagnostics}
