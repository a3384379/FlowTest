import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from app.domain.api_assets import BodyKind, HttpMethod
from app.domain.network import OutboundNetworkPolicy
from app.engine.contracts import (
    ConditionExpression,
    NodeStatus,
    NodeType,
    WorkflowDefinition,
    WorkflowPhase,
)
from app.engine.control_conditions import evaluate_condition
from app.engine.control_nodes import execute_control_node
from app.engine.results import NodeResult
from app.engine.scheduler import (
    CancellationToken,
    ExecutionContext,
    NodeExecutionError,
    NodeRunRecord,
    RequestBudget,
    WorkflowScheduler,
)
from app.engine.structured_control import (
    StructuredControlRunner,
    _instance_id,
    control_placeholder,
)
from app.services.api_assets import PreparedRequest
from app.services.workflow_runtime import (
    PreparedSubflow,
    PreparedWorkflowRequest,
    WorkflowNodeExecutor,
    _apply_control_templates,
)


def _node(node_id: str, capability: str | None = None, configuration: dict | None = None) -> dict:
    node: dict = {
        "id": node_id,
        "type": "capability" if capability else "delay",
        "name": node_id,
        "position": {"x": 0, "y": 0},
    }
    if capability:
        node.update(
            capability_id=capability,
            capability_version="1.0.0",
            configuration=configuration or {},
            bindings=[],
        )
    else:
        node["config"] = {"seconds": 0}
    return node


def _definition() -> dict:
    return {
        "schema_version": "4.0",
        "run_policy": {"request_budget": 1000, "max_runtime_seconds": 300},
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            _node(
                "loop",
                "flow.control.foreach",
                {
                    "collection": {"kind": "variable", "scope": "runtime", "path": ["cases"]},
                    "body": {"kind": "inline", "region_id": "body"},
                    "policy": {"max_iterations": 1000, "timeout_seconds": 120},
                },
            ),
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 0, "y": 0}},
        ],
        "edges": [
            {"id": "s-l", "source": "start", "target": "loop"},
            {"id": "l-e", "source": "loop", "target": "end"},
        ],
        "regions": [
            {
                "id": "body",
                "owner_node_id": "loop",
                "role": "body",
                "nodes": [_node("step")],
                "edges": [],
                "entry_node_id": "step",
                "exit_node_ids": ["step"],
            }
        ],
    }


def test_inline_region_is_part_of_versioned_definition() -> None:
    definition = WorkflowDefinition.model_validate(_definition())

    assert definition.schema_version == "4.0"
    assert definition.regions[0].owner_node_id == "loop"
    assert definition.model_dump(mode="json")["regions"][0]["nodes"][0]["id"] == "step"


@pytest.mark.parametrize("version", ["1.0", "2.0", "3.0", "9.0"])
def test_inline_region_requires_supported_schema(version: str) -> None:
    payload = _definition()
    payload["schema_version"] = version
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(payload)


def test_region_rejects_cross_boundary_edge() -> None:
    payload = _definition()
    payload["regions"][0]["edges"] = [{"id": "bad", "source": "step", "target": "end"}]
    with pytest.raises(ValidationError, match=r"bad.*outside region"):
        WorkflowDefinition.model_validate(payload)


def test_region_rejects_implicit_branch() -> None:
    payload = _definition()
    payload["regions"][0]["nodes"].extend([_node("second"), _node("third")])
    payload["regions"][0]["edges"] = [
        {"id": "a", "source": "step", "target": "second"},
        {"id": "b", "source": "step", "target": "third"},
    ]
    payload["regions"][0]["exit_node_ids"] = ["second", "third"]
    with pytest.raises(ValidationError, match="implicit branch"):
        WorkflowDefinition.model_validate(payload)


def test_region_rejects_shared_owner_and_cycles() -> None:
    payload = _definition()
    payload["regions"].append(
        {
            **deepcopy(payload["regions"][0]),
            "id": "second",
            "role": "other",
            "nodes": [_node("other_step")],
            "entry_node_id": "other_step",
            "exit_node_ids": ["other_step"],
        }
    )
    with pytest.raises(ValidationError, match="owner"):
        WorkflowDefinition.model_validate(payload)

    payload = _definition()
    payload["regions"][0]["nodes"].extend([_node("second"), _node("third")])
    payload["regions"][0]["edges"] = [
        {"id": "a", "source": "step", "target": "second"},
        {"id": "b", "source": "second", "target": "third"},
        {"id": "c", "source": "third", "target": "second"},
    ]
    payload["regions"][0]["exit_node_ids"] = ["second"]
    with pytest.raises(ValidationError, match="cycle"):
        WorkflowDefinition.model_validate(payload)


def test_repeat_rejects_non_positive_and_fractional_count() -> None:
    for count in (0, -1, 1.5, "3"):
        payload = _definition()
        payload["nodes"][1]["capability_id"] = "flow.control.repeat"
        payload["nodes"][1]["configuration"].pop("collection")
        payload["nodes"][1]["configuration"]["count"] = count
        with pytest.raises(ValidationError):
            WorkflowDefinition.model_validate(payload)


class CountingExecutor:
    def __init__(self, definition: WorkflowDefinition, fail_on: int | None = None) -> None:
        self.definition = definition
        self.fail_on = fail_on
        self.calls: list[tuple[int, object]] = []

    async def execute(self, node, context: ExecutionContext):
        if node.capability_id and node.capability_id.startswith("flow.control."):
            return await StructuredControlRunner(self.definition, self).execute(node, context)
        if node.id == "step":
            index = context.loop_variables["index"]
            item = context.loop_variables.get("item")
            assert isinstance(index, int)
            self.calls.append((index, item))
            if index == self.fail_on:
                return NodeResult.failed(code="CASE_FAILED", message="受控失败")
            return {"item": item, "index": index}
        return await execute_control_node(node, context)


def _branch_definition(capability: str, configuration: dict, roles: list[tuple[str, str]]) -> dict:
    payload = _definition()
    payload["nodes"][1] = _node("loop", capability, configuration)
    payload["regions"] = [
        {
            "id": region_id,
            "owner_node_id": "loop",
            "role": role,
            "nodes": [_node(f"{region_id}_step")],
            "entry_node_id": f"{region_id}_step",
            "exit_node_ids": [f"{region_id}_step"],
        }
        for role, region_id in roles
    ]
    return payload


class BranchExecutor(CountingExecutor):
    def __init__(self, definition: WorkflowDefinition) -> None:
        super().__init__(definition)
        self.visited: list[str] = []

    async def execute(self, node, context: ExecutionContext):
        if node.id.endswith("_step"):
            self.visited.append(node.id)
            return {"visited": node.id}
        return await super().execute(node, context)


@pytest.mark.asyncio
@pytest.mark.parametrize("value,expected", [(4, "true_step"), (5, "false_step")])
async def test_if_runs_only_selected_region(value: int, expected: str) -> None:
    payload = _branch_definition(
        "flow.control.if",
        {
            "condition": {
                "kind": "compare",
                "left": {"kind": "variable", "scope": "runtime", "path": ["value"]},
                "operator": "equals",
                "right": {"kind": "literal", "value": 4},
            },
            "true_body": {"kind": "inline", "region_id": "true"},
            "false_body": {"kind": "inline", "region_id": "false"},
        },
        [("true", "true"), ("false", "false")],
    )
    definition = WorkflowDefinition.model_validate(payload)
    executor = BranchExecutor(definition)
    result = await WorkflowScheduler(executor).run(
        definition, context=ExecutionContext(runtime_variables={"value": value})
    )
    assert result.status == "passed"
    assert executor.visited == [expected]
    assert result.records[1].output["selected_branch_id"] == ("true" if value == 4 else "false")


@pytest.mark.asyncio
async def test_if_missing_source_fails_and_does_not_route_false() -> None:
    payload = _branch_definition(
        "flow.control.if",
        {
            "condition": {
                "kind": "compare",
                "left": {"kind": "variable", "scope": "runtime", "path": ["missing"]},
                "operator": "equals",
                "right": {"kind": "literal", "value": None},
            },
            "true_body": {"kind": "inline", "region_id": "true"},
            "false_body": {"kind": "inline", "region_id": "false"},
        },
        [("true", "true"), ("false", "false")],
    )
    definition = WorkflowDefinition.model_validate(payload)
    executor = BranchExecutor(definition)
    result = await WorkflowScheduler(executor).run(definition)
    assert result.records[1].error_code == "VALUE_SOURCE_MISSING"
    assert executor.visited == []


@pytest.mark.asyncio
async def test_switch_first_match_and_explicit_default_skip() -> None:
    payload = _branch_definition(
        "flow.control.switch",
        {
            "mode": "value",
            "value": {"kind": "variable", "scope": "runtime", "path": ["value"]},
            "branches": [
                {
                    "id": "done",
                    "label": "完成",
                    "match": {"kind": "literal", "value": "DONE"},
                    "body": {"kind": "inline", "region_id": "done_region"},
                },
                {
                    "id": "waiting",
                    "label": "等待",
                    "match": {"kind": "literal", "value": "WAITING"},
                    "body": {"kind": "inline", "region_id": "waiting_region"},
                },
            ],
            "default": {"behavior": "skip"},
        },
        [("case:done", "done_region"), ("case:waiting", "waiting_region")],
    )
    definition = WorkflowDefinition.model_validate(payload)
    executor = BranchExecutor(definition)
    matched = await WorkflowScheduler(executor).run(
        definition, context=ExecutionContext(runtime_variables={"value": "WAITING"})
    )
    skipped = await WorkflowScheduler(executor).run(
        definition, context=ExecutionContext(runtime_variables={"value": "OTHER"})
    )
    assert executor.visited == ["waiting_region_step"]
    assert matched.records[1].output["selected_branch_id"] == "waiting"
    assert skipped.records[1].result.test_verdict == "not_run"
    assert skipped.records[1].output["reason"] == "no_match"


def test_switch_rejects_duplicate_literal_cases() -> None:
    payload = _branch_definition(
        "flow.control.switch",
        {
            "mode": "value",
            "value": {"kind": "literal", "value": "A"},
            "branches": [
                {
                    "id": name,
                    "label": name,
                    "match": {"kind": "literal", "value": "A"},
                    "body": {"kind": "inline", "region_id": region},
                }
                for name, region in [("first", "one"), ("second", "two")]
            ],
            "default": {"behavior": "skip"},
        },
        [("case:first", "one"), ("case:second", "two")],
    )
    with pytest.raises(ValidationError, match="duplicate literal"):
        WorkflowDefinition.model_validate(payload)


def test_strict_condition_distinguishes_bool_missing_and_null() -> None:
    context = ExecutionContext(runtime_variables={"flag": True, "null": None})

    def compare(path: str, operator: str, right: object = None) -> ConditionExpression:
        payload: dict = {
            "kind": "compare",
            "left": {"kind": "variable", "scope": "runtime", "path": [path]},
            "operator": operator,
        }
        if operator not in {"exists", "not_exists", "is_null"}:
            payload["right"] = {"kind": "literal", "value": right}
        return ConditionExpression.model_validate(payload)

    assert evaluate_condition(compare("flag", "equals", 1), context)[0] is False
    assert evaluate_condition(compare("null", "is_null"), context)[0] is True
    assert evaluate_condition(compare("missing", "exists"), context)[0] is False
    with pytest.raises(NodeExecutionError, match="不存在"):
        evaluate_condition(compare("missing", "is_null"), context)


def test_condition_short_circuit_marks_skipped_predicate() -> None:
    expression = ConditionExpression.model_validate(
        {
            "kind": "all",
            "conditions": [
                {
                    "kind": "compare",
                    "left": {"kind": "literal", "value": 1},
                    "operator": "equals",
                    "right": {"kind": "literal", "value": 2},
                },
                {
                    "kind": "compare",
                    "left": {"kind": "variable", "scope": "runtime", "path": ["missing"]},
                    "operator": "equals",
                    "right": {"kind": "literal", "value": 2},
                },
            ],
        }
    )
    result, trace = evaluate_condition(expression, ExecutionContext())
    assert result is False
    assert trace[-1]["result"] == "not_evaluated"


def _condition_loop_definition(mode: str, condition: dict, maximum: int = 3) -> dict:
    payload = _definition()
    payload["nodes"][1] = _node(
        "loop",
        f"flow.control.{mode}",
        {
            "condition": condition,
            "body": {"kind": "inline", "region_id": "body"},
            "state": {"counter": {"kind": "literal", "value": 0}},
            "update": {"counter": {"kind": "add", "value": {"kind": "literal", "value": 1}}},
            "policy": {"max_iterations": maximum, "timeout_seconds": 120},
        },
    )
    return payload


def _state_less_than(value: int) -> dict:
    return {
        "kind": "compare",
        "left": {"kind": "variable", "scope": "state", "path": ["counter"]},
        "operator": "lt",
        "right": {"kind": "literal", "value": value},
    }


@pytest.mark.asyncio
async def test_while_false_initially_runs_zero_iterations() -> None:
    definition = WorkflowDefinition.model_validate(
        _condition_loop_definition("while", _state_less_than(0))
    )
    executor = CountingExecutor(definition)
    result = await WorkflowScheduler(executor).run(definition)
    assert executor.calls == []
    assert result.records[1].output["started_count"] == 0
    assert result.records[1].result.test_verdict == "not_run"


@pytest.mark.asyncio
async def test_do_while_runs_once_and_until_sees_latest_round() -> None:
    do_definition = WorkflowDefinition.model_validate(
        _condition_loop_definition("do_while", _state_less_than(0))
    )
    do_executor = CountingExecutor(do_definition)
    do_result = await WorkflowScheduler(do_executor).run(do_definition)
    assert len(do_executor.calls) == 1
    assert do_result.records[1].output["termination_reason"] == "condition_false"

    until_payload = _condition_loop_definition(
        "until",
        {
            "kind": "compare",
            "left": {"kind": "node_output", "node_id": "step", "path": ["index"]},
            "operator": "equals",
            "right": {"kind": "literal", "value": 2},
        },
    )
    until_definition = WorkflowDefinition.model_validate(until_payload)
    until_executor = CountingExecutor(until_definition)
    until_result = await WorkflowScheduler(until_executor).run(until_definition)
    assert [index for index, _ in until_executor.calls] == [0, 1, 2]
    assert until_result.records[1].output["termination_reason"] == "condition_met"
    assert until_result.records[1].output["state"]["counter"] == 3


@pytest.mark.asyncio
async def test_condition_loop_reports_limit_instead_of_passing() -> None:
    definition = WorkflowDefinition.model_validate(
        _condition_loop_definition("while", _state_less_than(99), maximum=2)
    )
    result = await WorkflowScheduler(CountingExecutor(definition)).run(definition)
    assert result.status == "failed"
    assert result.records[1].error_code == "LOOP_LIMIT_EXCEEDED"
    assert result.records[1].output["started_count"] == 2


@pytest.mark.asyncio
async def test_cursor_pagination_uses_current_page_to_advance_and_stop() -> None:
    payload = _condition_loop_definition(
        "while",
        {
            "kind": "compare",
            "left": {"kind": "variable", "scope": "state", "path": ["hasNext"]},
            "operator": "equals",
            "right": {"kind": "literal", "value": True},
        },
        maximum=100,
    )
    config = payload["nodes"][1]["configuration"]
    config["state"] = {
        "cursor": {"kind": "literal", "value": ""},
        "hasNext": {"kind": "literal", "value": True},
    }
    config["update"] = {
        "cursor": {
            "kind": "set",
            "value": {"kind": "node_output", "node_id": "step", "path": ["body", "nextCursor"]},
        },
        "hasNext": {
            "kind": "set",
            "value": {"kind": "node_output", "node_id": "step", "path": ["body", "hasNext"]},
        },
    }
    payload["regions"][0]["nodes"] = [_node("step", "custom.test")]
    definition = WorkflowDefinition.model_validate(payload)

    class CursorExecutor:
        def __init__(self) -> None:
            self.cursors: list[str] = []

        async def execute(self, node, context: ExecutionContext):
            if node.capability_id == "flow.control.while":
                return await StructuredControlRunner(definition, self).execute(node, context)
            if node.id != "step":
                return await execute_control_node(node, context)
            cursor = context.state_variables["cursor"]
            assert isinstance(cursor, str)
            self.cursors.append(cursor)
            return {
                "body": {
                    "nextCursor": "second-page" if cursor == "" else "",
                    "hasNext": cursor == "",
                }
            }

    executor = CursorExecutor()
    result = await WorkflowScheduler(executor).run(definition)
    assert result.status == "passed", [
        (record.node_id, record.error_code, record.error_message, record.output)
        for record in result.records
    ]
    assert executor.cursors == ["", "second-page"]
    assert result.records[1].output["termination_reason"] == "condition_false"
    assert result.records[1].output["state"] == {"cursor": "", "hasNext": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("signal,expected,final_state", [("break", 1, 0), ("continue", 3, 3)])
async def test_serial_control_signal_skips_remaining_body(
    signal: str, expected: int, final_state: int
) -> None:
    payload = _condition_loop_definition("while", _state_less_than(3))
    payload["regions"][0]["nodes"] = [
        _node("signal", f"flow.control.{signal}", {}),
        _node("step"),
    ]
    payload["regions"][0]["entry_node_id"] = "signal"
    payload["regions"][0]["exit_node_ids"] = ["step"]
    payload["regions"][0]["edges"] = [{"id": "signal-step", "source": "signal", "target": "step"}]
    definition = WorkflowDefinition.model_validate(payload)
    executor = CountingExecutor(definition)
    result = await WorkflowScheduler(executor).run(definition)
    assert result.status == "passed"
    assert executor.calls == []
    assert result.records[1].output["started_count"] == expected
    assert result.records[1].output["state"]["counter"] == final_state


def test_control_signal_outside_loop_is_rejected() -> None:
    payload = _definition()
    payload["nodes"][1] = _node("loop", "flow.control.break", {})
    payload["regions"] = []
    with pytest.raises(ValidationError, match="inside a serial loop"):
        WorkflowDefinition.model_validate(payload)


def _parallel_definition(on_error: str = "collect_all") -> dict:
    return _branch_definition(
        "flow.control.parallel",
        {
            "branches": [
                {
                    "id": name,
                    "label": name,
                    "body": {"kind": "inline", "region_id": f"{name}_region"},
                }
                for name in ("first", "second", "third")
            ],
            "policy": {"concurrency": 2, "timeout_seconds": 120, "on_error": on_error},
        },
        [(f"branch:{name}", f"{name}_region") for name in ("first", "second", "third")],
    )


@pytest.mark.asyncio
async def test_parallel_is_bounded_and_merges_in_definition_order() -> None:
    definition = WorkflowDefinition.model_validate(_parallel_definition())

    class ParallelExecutor(BranchExecutor):
        def __init__(self, definition: WorkflowDefinition) -> None:
            super().__init__(definition)
            self.active = 0
            self.peak = 0

        async def execute(self, node, context: ExecutionContext):
            if node.id.endswith("_step"):
                self.active += 1
                self.peak = max(self.peak, self.active)
                try:
                    await asyncio.sleep(0.01 if node.id.startswith("first") else 0.001)
                    self.visited.append(node.id)
                    return {"node": node.id}
                finally:
                    self.active -= 1
            return await super().execute(node, context)

    executor = ParallelExecutor(definition)
    result = await WorkflowScheduler(executor).run(definition)
    assert result.status == "passed"
    assert executor.peak == 2
    assert [item["branch_id"] for item in result.records[1].output["branches"]] == [
        "first",
        "second",
        "third",
    ]
    assert executor.visited[0] == "second_region_step"


@pytest.mark.asyncio
async def test_parallel_branches_cannot_mutate_sibling_json_inputs() -> None:
    payload = _parallel_definition()
    payload["nodes"][1]["configuration"]["inputs"] = {
        "payload": {"kind": "variable", "scope": "runtime", "path": ["payload"]}
    }
    definition = WorkflowDefinition.model_validate(payload)
    first_done = asyncio.Event()

    class IsolatedExecutor(BranchExecutor):
        async def execute(self, node, context: ExecutionContext):
            if node.id == "first_region_step":
                context.input_variables["payload"]["nested"]["flag"] = True
                first_done.set()
                return {"branch": "first"}
            if node.id == "second_region_step":
                await first_done.wait()
                assert "flag" not in context.input_variables["payload"]["nested"]
                return {"branch": "second"}
            return await super().execute(node, context)

    source = {"payload": {"nested": {"value": 1}}}
    result = await WorkflowScheduler(IsolatedExecutor(definition)).run(
        definition, context=ExecutionContext(runtime_variables=source)
    )
    assert result.status == "passed", result.records[1].output
    assert source == {"payload": {"nested": {"value": 1}}}


@pytest.mark.asyncio
async def test_parallel_stop_on_error_does_not_start_later_branch() -> None:
    definition = WorkflowDefinition.model_validate(_parallel_definition("stop_on_error"))

    class FailingExecutor(BranchExecutor):
        async def execute(self, node, context: ExecutionContext):
            if node.id == "first_region_step":
                return NodeResult.failed(code="CASE_FAILED", message="受控失败")
            if node.id == "second_region_step":
                await asyncio.sleep(0.1)
            return await super().execute(node, context)

    executor = FailingExecutor(definition)
    result = await WorkflowScheduler(executor).run(definition)
    branches = result.records[1].output["branches"]
    assert result.status == "failed"
    assert branches[0]["status"] == "failed"
    assert branches[2]["status"] == "not_started"
    assert "third_region_step" not in executor.visited


@pytest.mark.asyncio
async def test_concurrent_foreach_keeps_input_order_and_bound() -> None:
    payload = _definition()
    payload["nodes"][1]["configuration"]["policy"]["concurrency"] = 2
    definition = WorkflowDefinition.model_validate(payload)

    class DelayedExecutor(CountingExecutor):
        def __init__(self, definition: WorkflowDefinition) -> None:
            super().__init__(definition)
            self.active = 0
            self.peak = 0

        async def execute(self, node, context: ExecutionContext):
            if node.id == "step":
                self.active += 1
                self.peak = max(self.peak, self.active)
                try:
                    await asyncio.sleep(0.01 if context.loop_variables["index"] == 0 else 0.001)
                    return await super().execute(node, context)
                finally:
                    self.active -= 1
            return await super().execute(node, context)

    executor = DelayedExecutor(definition)
    result = await WorkflowScheduler(executor).run(
        definition, context=ExecutionContext(runtime_variables={"cases": [1, 2, 3]})
    )
    assert result.status == "passed"
    assert executor.peak == 2
    assert [item["input_index"] for item in result.records[1].output["items"]] == [0, 1, 2]
    assert executor.calls[0][0] == 1


@pytest.mark.asyncio
async def test_concurrent_foreach_stop_does_not_start_later_item() -> None:
    payload = _definition()
    payload["nodes"][1]["configuration"]["policy"].update({"concurrency": 2, "on_error": "stop"})
    definition = WorkflowDefinition.model_validate(payload)

    class FailingExecutor(CountingExecutor):
        async def execute(self, node, context: ExecutionContext):
            if node.id == "step" and context.loop_variables["index"] == 1:
                await asyncio.sleep(0.1)
            return await super().execute(node, context)

    executor = FailingExecutor(definition, fail_on=0)
    result = await WorkflowScheduler(executor).run(
        definition, context=ExecutionContext(runtime_variables={"cases": [1, 2, 3]})
    )
    summary = result.records[1].output
    assert result.status == "failed"
    assert summary["not_started_count"] == 1
    assert (2, 3) not in executor.calls


@pytest.mark.asyncio
async def test_concurrent_foreach_inputs_do_not_share_mutable_objects() -> None:
    payload = _definition()
    payload["nodes"][1]["configuration"]["policy"]["concurrency"] = 2
    payload["nodes"][1]["configuration"]["inputs"] = {
        "shared": {"kind": "variable", "scope": "runtime", "path": ["shared"]}
    }
    definition = WorkflowDefinition.model_validate(payload)
    changed = asyncio.Event()

    class IsolatedExecutor(BranchExecutor):
        async def execute(self, node, context: ExecutionContext):
            if node.id == "step" and context.loop_variables["index"] == 0:
                context.input_variables["shared"]["nested"]["flag"] = True
                changed.set()
            elif node.id == "step":
                await changed.wait()
                assert "flag" not in context.input_variables["shared"]["nested"]
            return await super().execute(node, context)

    source = {"cases": [1, 2], "shared": {"nested": {"value": 1}}}
    result = await WorkflowScheduler(IsolatedExecutor(definition)).run(
        definition, context=ExecutionContext(runtime_variables=source)
    )
    assert result.status == "passed", result.records[1].output
    assert source["shared"] == {"nested": {"value": 1}}


@pytest.mark.asyncio
async def test_concurrent_foreach_with_nested_parallel_shares_leaf_limit() -> None:
    payload = _definition()
    payload["settings"] = {"concurrency": 1}
    payload["nodes"][1]["configuration"]["policy"]["concurrency"] = 2
    payload["regions"][0]["nodes"] = [
        _node(
            "nested_parallel",
            "flow.control.parallel",
            {
                "branches": [
                    {"id": name, "label": name, "body": {"kind": "inline", "region_id": name}}
                    for name in ("a", "b")
                ],
                "policy": {"concurrency": 2, "timeout_seconds": 30},
            },
        )
    ]
    payload["regions"][0]["entry_node_id"] = "nested_parallel"
    payload["regions"][0]["exit_node_ids"] = ["nested_parallel"]
    payload["regions"].extend(
        {
            "id": name,
            "owner_node_id": "nested_parallel",
            "role": f"branch:{name}",
            "nodes": [_node(f"{name}_step", "custom.test")],
            "edges": [],
            "entry_node_id": f"{name}_step",
            "exit_node_ids": [f"{name}_step"],
        }
        for name in ("a", "b")
    )
    definition = WorkflowDefinition.model_validate(payload)

    class NestedExecutor(BranchExecutor):
        def __init__(self, definition: WorkflowDefinition) -> None:
            super().__init__(definition)
            self.active = 0
            self.peak = 0

        async def execute(self, node, context: ExecutionContext):
            if node.id in {"a_step", "b_step"}:
                self.active += 1
                self.peak = max(self.peak, self.active)
                try:
                    await asyncio.sleep(0.005)
                    self.visited.append(f"{context.loop_variables['index']}:{node.id}")
                    return {"branch": node.id}
                finally:
                    self.active -= 1
            return await super().execute(node, context)

    executor = NestedExecutor(definition)
    result = await asyncio.wait_for(
        WorkflowScheduler(executor).run(
            definition, context=ExecutionContext(runtime_variables={"cases": [1, 2]})
        ),
        timeout=2,
    )
    assert result.status == "passed", [
        (record.node_id, record.error_code, record.error_message, record.output)
        for record in result.records
    ]
    assert executor.peak == 1
    assert sorted(executor.visited) == ["0:a_step", "0:b_step", "1:a_step", "1:b_step"]


@pytest.mark.asyncio
@pytest.mark.parametrize("root_concurrency", [1, 2])
async def test_parallel_http_leaf_limit_and_cookie_isolation(root_concurrency: int) -> None:
    payload = _branch_definition(
        "flow.control.parallel",
        {
            "branches": [
                {"id": name, "label": name, "body": {"kind": "inline", "region_id": name}}
                for name in ("a", "b")
            ],
            "policy": {"concurrency": 2, "timeout_seconds": 120, "on_error": "collect_all"},
        },
        [(f"branch:{name}", name) for name in ("a", "b")],
    )
    payload["settings"] = {
        "fail_fast": True,
        "concurrency": root_concurrency,
        "default_timeout_seconds": 30,
    }
    prepared: dict[str, PreparedWorkflowRequest] = {}
    for region in payload["regions"]:
        name = region["id"]
        region["nodes"] = [
            {
                "id": f"{name}_{part}",
                "type": "api",
                "name": f"{name}_{part}",
                "position": {"x": 0, "y": 0},
                "config": {"api_definition_id": "00000000-0000-0000-0000-000000000001"},
            }
            for part in ("start", "check")
        ]
        region["entry_node_id"] = f"{name}_start"
        region["exit_node_ids"] = [f"{name}_check"]
        region["edges"] = [
            {"id": f"{name}-edge", "source": f"{name}_start", "target": f"{name}_check"}
        ]
        for part in ("start", "check"):
            request = PreparedRequest(
                HttpMethod.GET, f"https://example.test/{name}/{part}", (), None, ()
            )
            prepared[f"{name}_{part}"] = PreparedWorkflowRequest(
                request, request, BodyKind.NONE, None
            )
    definition = WorkflowDefinition.model_validate(payload)
    active = 0
    peak = 0
    cookies: dict[str, str | None] = {}
    events: list[str] = []

    async def respond(incoming: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        events.append(f"start:{incoming.url.path}")
        try:
            await asyncio.sleep(0.005)
            name, part = incoming.url.path.strip("/").split("/")
            if part == "start":
                return httpx.Response(
                    200, json={"ok": True}, headers={"set-cookie": f"session={name}; Path=/"}
                )
            cookies[name] = incoming.headers.get("cookie")
            return httpx.Response(200, json={"ok": True})
        finally:
            active -= 1
            events.append(f"end:{incoming.url.path}")

    class AllowOutbound:
        async def enforce(self, url: str, policy: OutboundNetworkPolicy) -> None:
            return None

    transport = httpx.MockTransport(respond)
    context = ExecutionContext()
    async with httpx.AsyncClient(transport=transport) as client:
        executor = WorkflowNodeExecutor(
            client,
            prepared,
            definition,
            OutboundNetworkPolicy(),
            outbound_guard=AllowOutbound(),  # type: ignore[arg-type]
            branch_client_factory=lambda: httpx.AsyncClient(transport=transport),
        )
        result = await asyncio.wait_for(
            WorkflowScheduler(executor).run(definition, context=context), timeout=1
        )
    assert result.status == "passed"
    assert peak == root_concurrency, events
    assert cookies == {"a": "session=a", "b": "session=b"}


@pytest.mark.asyncio
async def test_parallel_branches_call_subflows_without_holding_leaf_permits() -> None:
    workflow_id = UUID("00000000-0000-0000-0000-000000000321")
    payload = _branch_definition(
        "flow.control.parallel",
        {
            "branches": [
                {"id": name, "label": name, "body": {"kind": "inline", "region_id": name}}
                for name in ("a", "b")
            ],
            "policy": {"concurrency": 2, "timeout_seconds": 30},
        },
        [(f"branch:{name}", name) for name in ("a", "b")],
    )
    payload["settings"] = {"concurrency": 1}
    for region in payload["regions"]:
        name = region["id"]
        region["nodes"] = [
            {
                "id": f"{name}_subflow",
                "type": "subflow",
                "name": f"{name}_subflow",
                "position": {"x": 0, "y": 0},
                "config": {"workflow_id": str(workflow_id), "workflow_version": 1},
            }
        ]
        region["entry_node_id"] = f"{name}_subflow"
        region["exit_node_ids"] = [f"{name}_subflow"]
    definition = WorkflowDefinition.model_validate(payload)
    api_config = {"api_definition_id": "00000000-0000-0000-0000-000000000001"}
    child = WorkflowDefinition.model_validate(
        {
            "schema_version": "2.0",
            "nodes": [
                {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
                *[
                    {
                        "id": name,
                        "type": "api",
                        "name": name,
                        "position": {"x": 0, "y": 0},
                        "config": api_config,
                    }
                    for name in ("first", "second")
                ],
                {"id": "end", "type": "end", "name": "结束", "position": {"x": 0, "y": 0}},
            ],
            "edges": [
                {"id": "s-f", "source": "start", "target": "first"},
                {"id": "s-s", "source": "start", "target": "second"},
                {"id": "f-e", "source": "first", "target": "end"},
                {"id": "s-e", "source": "second", "target": "end"},
            ],
        }
    )
    request = PreparedRequest(HttpMethod.GET, "https://example.test/read", (), None, ())
    prepared_request = PreparedWorkflowRequest(request, request, BodyKind.NONE, None)
    prepared = PreparedSubflow(
        workflow_id=workflow_id,
        workflow_version=1,
        fingerprint="e" * 64,
        definition=child,
        requests={"first": prepared_request, "second": prepared_request},
        subflows={},
        snapshot={},
    )
    active = 0
    peak = 0
    sent = 0

    async def respond(_: httpx.Request) -> httpx.Response:
        nonlocal active, peak, sent
        active += 1
        sent += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.005)
            return httpx.Response(200, json={"ok": True})
        finally:
            active -= 1

    class AllowOutbound:
        async def enforce(self, url: str, policy: OutboundNetworkPolicy) -> None:
            return None

    transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport) as client:
        executor = WorkflowNodeExecutor(
            client,
            {},
            definition,
            OutboundNetworkPolicy(),
            subflows={f"{name}_subflow": prepared for name in ("a", "b")},
            outbound_guard=AllowOutbound(),  # type: ignore[arg-type]
            branch_client_factory=lambda: httpx.AsyncClient(transport=transport),
        )
        result = await asyncio.wait_for(WorkflowScheduler(executor).run(definition), timeout=2)
    assert result.status == "passed", result.records
    assert sent == 4
    assert peak == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cases", [[], [{"id": 1}], [{"id": 1}, {"id": 2}, {"id": 3}]])
async def test_inline_foreach_runs_each_item_once_with_isolated_output(cases: list[dict]) -> None:
    definition = WorkflowDefinition.model_validate(_definition())
    executor = CountingExecutor(definition)
    context = ExecutionContext(runtime_variables={"cases": cases})

    result = await WorkflowScheduler(executor).run(
        definition,
        context=context,
    )

    loop = next(record for record in result.records if record.node_id == "loop")
    assert executor.calls == list(enumerate(cases))
    assert loop.output["input_count"] == len(cases)
    assert loop.output["started_count"] == len(cases)
    assert loop.result.test_verdict == ("not_run" if not cases else "passed")
    instance_ids = [item["nodes"][0]["instance_id"] for item in loop.output["items"]]
    assert [
        context.nested_checkpoint_records[instance_id].output["item"]
        for instance_id in instance_ids
    ] == cases


@pytest.mark.asyncio
async def test_repeat_runs_exactly_three_times() -> None:
    payload = _definition()
    payload["nodes"][1]["capability_id"] = "flow.control.repeat"
    payload["nodes"][1]["configuration"] = {
        "count": 3,
        "body": {"kind": "inline", "region_id": "body"},
    }
    definition = WorkflowDefinition.model_validate(payload)
    executor = CountingExecutor(definition)

    result = await WorkflowScheduler(executor).run(definition)

    assert result.status == "passed"
    assert executor.calls == [(0, None), (1, None), (2, None)]


@pytest.mark.asyncio
async def test_iteration_input_can_read_parent_output() -> None:
    payload = _definition()
    payload["nodes"][1]["configuration"]["inputs"] = {
        "created_id": {"kind": "node_output", "node_id": "start", "path": ["id"]}
    }
    definition = WorkflowDefinition.model_validate(payload)

    class ParentExecutor(CountingExecutor):
        async def execute(self, node, context: ExecutionContext):
            if node.id == "start":
                return {"id": 41}
            if node.id == "step":
                assert context.input_variables["created_id"] == 41
            return await super().execute(node, context)

    executor = ParentExecutor(definition)
    result = await WorkflowScheduler(executor).run(
        definition,
        context=ExecutionContext(runtime_variables={"cases": [1]}),
    )
    assert result.status == "passed"


@pytest.mark.asyncio
@pytest.mark.parametrize("on_error,expected", [("stop", 2), ("continue_collect", 3)])
async def test_foreach_failure_policy_keeps_failed_verdict(on_error: str, expected: int) -> None:
    payload = _definition()
    payload["nodes"][1]["configuration"]["policy"]["on_error"] = on_error
    definition = WorkflowDefinition.model_validate(payload)
    executor = CountingExecutor(definition, fail_on=1)

    result = await WorkflowScheduler(executor).run(
        definition,
        context=ExecutionContext(runtime_variables={"cases": [1, 2, 3]}),
    )

    loop = next(record for record in result.records if record.node_id == "loop")
    assert len(executor.calls) == expected
    assert loop.status == "passed"
    assert loop.result.test_verdict == "failed"
    assert loop.output["failed_count"] == 1
    assert result.status == "failed"


@pytest.mark.asyncio
async def test_foreach_does_not_continue_collect_after_unknown_write_outcome() -> None:
    payload = _definition()
    payload["nodes"][1]["configuration"]["policy"]["on_error"] = "continue_collect"
    payload["regions"][0]["nodes"][0] = {
        "id": "step",
        "type": "api",
        "name": "写入",
        "position": {"x": 0, "y": 0},
        "config": {"api_definition_id": "00000000-0000-0000-0000-000000000001"},
    }
    definition = WorkflowDefinition.model_validate(payload)
    now = datetime.now(UTC)
    instance_id = _instance_id(("region", "body", "iteration", "0"), "step")
    reserved = NodeRunRecord(
        node_id=instance_id,
        node_type=NodeType.API,
        name="写入",
        status=NodeStatus.RUNNING,
        attempts=1,
        output=None,
        result=NodeResult(status=NodeStatus.CANCELLED, request_attempts=1),
        error_code=None,
        error_message=None,
        started_at=now,
        completed_at=now,
        input_hash="a" * 64,
    )
    context = ExecutionContext(runtime_variables={"cases": [1, 2, 3]})
    context.nested_checkpoint_records[instance_id] = reserved
    executor = CountingExecutor(definition)
    result = await WorkflowScheduler(executor).run(
        definition, context=context, resume_records=(reserved,)
    )

    loop = next(record for record in result.records if record.node_id == "loop")
    assert executor.calls == []
    assert loop.error_code == "SIDE_EFFECT_OUTCOME_UNKNOWN"
    assert loop.output["started_count"] == 1
    assert result.status == "failed"


@pytest.mark.asyncio
async def test_inline_api_uses_each_iteration_input_in_request() -> None:
    payload = _definition()
    payload["nodes"][1]["configuration"]["inputs"] = {
        "record_id": {"kind": "variable", "scope": "loop", "path": ["item", "id"]}
    }
    payload["regions"][0]["nodes"] = [
        {
            "id": "request",
            "type": "api",
            "name": "请求",
            "position": {"x": 0, "y": 0},
            "config": {"api_definition_id": "00000000-0000-0000-0000-000000000001"},
        }
    ]
    payload["regions"][0]["entry_node_id"] = "request"
    payload["regions"][0]["exit_node_ids"] = ["request"]
    definition = WorkflowDefinition.model_validate(payload)
    marker = control_placeholder("request", "input.record_id")
    request = PreparedRequest(
        HttpMethod.POST,
        f"https://example.test/records/{marker}",
        (),
        {"id": marker},
        (),
    )
    seen: list[tuple[str, str]] = []

    def respond(incoming: httpx.Request) -> httpx.Response:
        seen.append((incoming.url.path, incoming.read().decode()))
        return httpx.Response(200, json={"ok": True})

    class AllowOutbound:
        async def enforce(self, url: str, policy: OutboundNetworkPolicy) -> None:
            return None

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        executor = WorkflowNodeExecutor(
            client,
            {"request": PreparedWorkflowRequest(request, request, BodyKind.JSON, None)},
            definition,
            OutboundNetworkPolicy(),
            outbound_guard=AllowOutbound(),  # type: ignore[arg-type]
        )
        result = await WorkflowScheduler(executor).run(
            definition,
            context=ExecutionContext(runtime_variables={"cases": [{"id": 4}, {"id": 7}]}),
        )

    assert result.status == "passed"
    assert [path for path, _ in seen] == ["/records/4", "/records/7"]
    assert all("__FLOWTEST_CONTROL_" not in body for _, body in seen)


def test_unbound_control_input_is_rejected_before_http() -> None:
    marker = control_placeholder("request", "input.missing")
    request = PreparedRequest(HttpMethod.GET, f"https://example.test/{marker}", (), None, ())
    with pytest.raises(Exception, match="未绑定"):
        _apply_control_templates(request, "request", ExecutionContext())


@pytest.mark.asyncio
async def test_no_request_loop_still_consumes_shared_instance_budget() -> None:
    payload = _definition()
    payload["nodes"][1]["configuration"]["policy"]["on_error"] = "continue_collect"
    definition = WorkflowDefinition.model_validate(payload)
    executor = CountingExecutor(definition)

    result = await WorkflowScheduler(executor).run(
        definition,
        context=ExecutionContext(
            runtime_variables={"cases": [1, 2, 3]},
            node_instance_budget=RequestBudget(4),
        ),
    )

    loop = next(record for record in result.records if record.node_id == "loop")
    assert executor.calls == [(0, 1), (1, 2)]
    assert loop.output["items"][2]["nodes"][0]["error_code"] == ("NODE_INSTANCE_BUDGET_EXHAUSTED")
    assert result.status == "failed"


def _try_definition(*, fail_try: bool, expected: bool = False, fail_finally: bool = False) -> dict:
    payload = _branch_definition(
        "flow.control.try",
        {
            "try_body": {"kind": "inline", "region_id": "try_region"},
            "catches": [
                {
                    "id": "known",
                    "label": "已知错误",
                    "error_codes": ["CASE_FAIL"],
                    "body": {"kind": "inline", "region_id": "catch_region"},
                }
            ],
            "finally_body": {"kind": "inline", "region_id": "finally_region"},
            "expected_error_codes": ["CASE_FAIL"] if expected else [],
        },
        [("try", "try_region"), ("catch:known", "catch_region"), ("finally", "finally_region")],
    )
    payload["run_policy"]["cleanup_request_budget"] = 10
    if fail_try:
        payload["regions"][0]["nodes"] = [
            _node("try_fail", "flow.control.fail", {"code": "CASE_FAIL", "message": "受控失败"})
        ]
        payload["regions"][0]["entry_node_id"] = "try_fail"
        payload["regions"][0]["exit_node_ids"] = ["try_fail"]
    if fail_finally:
        payload["regions"][2]["nodes"] = [
            _node(
                "finally_fail", "flow.control.fail", {"code": "CLEANUP_FAIL", "message": "清理失败"}
            )
        ]
        payload["regions"][2]["entry_node_id"] = "finally_fail"
        payload["regions"][2]["exit_node_ids"] = ["finally_fail"]
    return payload


@pytest.mark.parametrize(
    "field,codes",
    [
        ("catch", [" "]),
        ("catch", [" CASE_FAIL"]),
        ("catch", ["CASE_FAIL", "CASE_FAIL"]),
        ("catch", ["x" * 101]),
        ("expected", [" "]),
        ("expected", ["CASE_FAIL "]),
        ("expected", ["CASE_FAIL", "CASE_FAIL"]),
        ("expected", ["x" * 101]),
    ],
)
def test_try_rejects_invalid_error_codes(field: str, codes: list[str]) -> None:
    payload = _try_definition(fail_try=False)
    configuration = payload["nodes"][1]["configuration"]
    if field == "catch":
        configuration["catches"][0]["error_codes"] = codes
    else:
        configuration["expected_error_codes"] = codes
    with pytest.raises(ValidationError, match="error codes"):
        WorkflowDefinition.model_validate(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("expected,final_status", [(False, "failed"), (True, "passed")])
async def test_try_catch_finally_preserves_declared_verdict(
    expected: bool, final_status: str
) -> None:
    definition = WorkflowDefinition.model_validate(
        _try_definition(fail_try=True, expected=expected)
    )
    executor = BranchExecutor(definition)
    result = await WorkflowScheduler(executor).run(definition)
    assert result.status == final_status
    assert executor.visited == ["catch_region_step", "finally_region_step"]
    assert result.records[1].output["original_error"]["code"] == "CASE_FAIL"
    assert result.records[1].output["catch_id"] == "known"


@pytest.mark.asyncio
async def test_try_unknown_write_skips_catch_but_runs_finally() -> None:
    payload = _try_definition(fail_try=False)
    payload["nodes"][1]["configuration"]["catches"][0]["error_codes"] = [
        "SIDE_EFFECT_OUTCOME_UNKNOWN"
    ]
    payload["regions"][0]["nodes"][0] = {
        "id": "try_region_step",
        "type": "api",
        "name": "写入",
        "position": {"x": 0, "y": 0},
        "config": {"api_definition_id": "00000000-0000-0000-0000-000000000001"},
    }
    definition = WorkflowDefinition.model_validate(payload)
    now = datetime.now(UTC)
    instance_id = _instance_id(("region", "try_region", "try"), "try_region_step")
    reserved = NodeRunRecord(
        node_id=instance_id,
        node_type=NodeType.API,
        name="写入",
        status=NodeStatus.RUNNING,
        attempts=1,
        output=None,
        result=NodeResult(status=NodeStatus.CANCELLED, request_attempts=1),
        error_code=None,
        error_message=None,
        started_at=now,
        completed_at=now,
        input_hash="a" * 64,
    )
    context = ExecutionContext()
    context.nested_checkpoint_records[instance_id] = reserved
    executor = BranchExecutor(definition)
    result = await WorkflowScheduler(executor).run(
        definition, context=context, resume_records=(reserved,)
    )
    assert executor.visited == ["finally_region_step"]
    assert result.records[1].error_code == "SIDE_EFFECT_OUTCOME_UNKNOWN"
    assert result.status == "failed"

    unknown = context.nested_checkpoint_records[instance_id]
    assert unknown.error_code == "SIDE_EFFECT_OUTCOME_UNKNOWN"
    again = await WorkflowScheduler(BranchExecutor(definition)).run(
        definition,
        resume_records=(*result.records, unknown),
    )
    assert again.status == "failed"
    assert again.records[1].error_code == "SIDE_EFFECT_OUTCOME_UNKNOWN"

    missing_parent = await WorkflowScheduler(BranchExecutor(definition)).run(
        definition,
        resume_records=(unknown,),
    )
    assert missing_parent.status == "failed"
    assert missing_parent.unknown_outcome


@pytest.mark.asyncio
async def test_try_unknown_finally_write_is_reported_as_unknown() -> None:
    payload = _try_definition(fail_try=False)
    payload["regions"][2]["nodes"][0] = {
        "id": "finally_region_step",
        "type": "api",
        "name": "清理写入",
        "position": {"x": 0, "y": 0},
        "config": {"api_definition_id": "00000000-0000-0000-0000-000000000001"},
    }
    definition = WorkflowDefinition.model_validate(payload)
    now = datetime.now(UTC)
    instance_id = _instance_id(("region", "finally_region", "finally"), "finally_region_step")
    reserved = NodeRunRecord(
        node_id=instance_id,
        node_type=NodeType.API,
        name="清理写入",
        status=NodeStatus.RUNNING,
        attempts=1,
        output=None,
        result=NodeResult(status=NodeStatus.CANCELLED, request_attempts=1),
        error_code=None,
        error_message=None,
        started_at=now,
        completed_at=now,
        input_hash="b" * 64,
        phase=WorkflowPhase.CLEANUP,
    )
    context = ExecutionContext()
    context.nested_checkpoint_records[instance_id] = reserved
    executor = BranchExecutor(definition)
    result = await WorkflowScheduler(executor).run(
        definition, context=context, resume_records=(reserved,)
    )
    assert executor.visited == ["try_region_step"]
    assert result.records[1].error_code == "SIDE_EFFECT_OUTCOME_UNKNOWN"
    assert result.status == "failed"

    unknown = context.nested_checkpoint_records[instance_id]
    second_executor = BranchExecutor(definition)
    missing_parent = await WorkflowScheduler(second_executor).run(
        definition,
        resume_records=(unknown,),
    )
    assert missing_parent.status == "failed"
    assert missing_parent.unknown_outcome
    assert second_executor.visited == []


@pytest.mark.asyncio
async def test_try_finally_failure_is_visible_when_main_passed() -> None:
    definition = WorkflowDefinition.model_validate(
        _try_definition(fail_try=False, fail_finally=True)
    )
    executor = BranchExecutor(definition)
    result = await WorkflowScheduler(executor).run(definition)
    assert result.status == "failed"
    assert result.records[1].error_code == "FINALLY_FAILED"
    assert result.records[1].output["finally_error"]["code"] == "CLEANUP_FAIL"
    assert executor.visited == ["try_region_step"]


@pytest.mark.asyncio
async def test_completed_inline_and_workflow_cleanup_are_not_repeated_after_parent_loss() -> None:
    payload = _try_definition(fail_try=False)
    payload["nodes"].append(
        {
            "id": "global_cleanup_step",
            "type": "api",
            "name": "流程清理",
            "position": {"x": 0, "y": 200},
            "config": {"api_definition_id": "00000000-0000-0000-0000-000000000001"},
            "phase": "cleanup",
            "cleanup_for": ["loop"],
        }
    )
    definition = WorkflowDefinition.model_validate(payload)
    first_context = ExecutionContext()
    first_executor = BranchExecutor(definition)
    first = await WorkflowScheduler(first_executor).run(definition, context=first_context)

    assert first.status == "passed"
    assert first.main_status == "passed"
    assert first.cleanup_status == "passed"
    assert first_executor.visited == [
        "try_region_step",
        "finally_region_step",
        "global_cleanup_step",
    ]

    retained = tuple(record for record in first.records if record.node_id != "loop") + tuple(
        first_context.nested_checkpoint_records.values()
    )
    recovered_executor = BranchExecutor(definition)
    recovered = await WorkflowScheduler(recovered_executor).run(definition, resume_records=retained)

    assert recovered.status == "passed"
    assert recovered.main_status == "passed"
    assert recovered.cleanup_status == "passed"
    assert recovered_executor.visited == []


def test_try_requires_cleanup_budget() -> None:
    payload = _try_definition(fail_try=False)
    payload["run_policy"].pop("cleanup_request_budget")
    with pytest.raises(ValidationError, match="separate cleanup request budget"):
        WorkflowDefinition.model_validate(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("force,expect_finally", [(False, True), (True, False)])
async def test_try_cancellation_runs_or_skips_finally_by_policy(
    force: bool, expect_finally: bool
) -> None:
    payload = _try_definition(fail_try=False)
    payload["run_policy"]["force_cancel_skips_cleanup"] = force
    definition = WorkflowDefinition.model_validate(payload)
    entered = asyncio.Event()

    class WaitingExecutor(BranchExecutor):
        async def execute(self, node, context: ExecutionContext):
            if node.id == "try_region_step":
                entered.set()
                await asyncio.Event().wait()
            return await super().execute(node, context)

    executor = WaitingExecutor(definition)
    token = CancellationToken()
    task = asyncio.create_task(WorkflowScheduler(executor).run(definition, cancellation=token))
    await asyncio.wait_for(entered.wait(), timeout=1)
    token.cancel(force=force)
    result = await asyncio.wait_for(task, timeout=1)
    assert result.status == "cancelled"
    assert ("finally_region_step" in executor.visited) is expect_finally


def _return_node(node_id: str = "return_value") -> dict:
    return _node(
        node_id,
        "flow.control.return",
        {"outputs": {"result": {"kind": "literal", "value": 42}}},
    )


@pytest.mark.asyncio
async def test_return_requires_subflow_call_and_skips_following_nodes() -> None:
    payload = _definition()
    payload["regions"] = []
    payload["nodes"][1] = _return_node("loop")
    definition = WorkflowDefinition.model_validate(payload)
    executor = CountingExecutor(definition)

    root = await WorkflowScheduler(executor).run(definition)
    assert root.status == "failed"
    assert root.records[1].error_code == "RETURN_OUTSIDE_CALL"

    called = await WorkflowScheduler(executor).run(
        definition, context=ExecutionContext(allow_return=True)
    )
    assert called.status == "passed"
    assert called.control_signal == "return"
    assert called.return_output == {"result": 42}
    assert called.records[2].status == "skipped"


@pytest.mark.asyncio
async def test_nested_return_runs_finally_and_preserves_output() -> None:
    payload = _try_definition(fail_try=False)
    payload["regions"][0]["nodes"] = [_return_node()]
    payload["regions"][0]["entry_node_id"] = "return_value"
    payload["regions"][0]["exit_node_ids"] = ["return_value"]
    definition = WorkflowDefinition.model_validate(payload)
    executor = BranchExecutor(definition)

    result = await WorkflowScheduler(executor).run(
        definition, context=ExecutionContext(allow_return=True)
    )

    assert result.status == "passed"
    assert result.control_signal == "return"
    assert result.return_output == {"result": 42}
    assert result.records[2].status == "skipped"
    assert executor.visited == ["finally_region_step"]
