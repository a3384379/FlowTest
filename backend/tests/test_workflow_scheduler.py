import asyncio
from collections import defaultdict

import pytest
from pydantic import JsonValue, ValidationError

from app.engine.contracts import NodeStatus, RetryCategory, WorkflowDefinition, WorkflowNode
from app.engine.scheduler import (
    CancellationToken,
    ExecutionContext,
    NodeExecutionError,
    NodeStatusUpdate,
    WorkflowScheduler,
)


class ControlledExecutor:
    def __init__(self, behaviors: dict[str, dict[str, object]] | None = None) -> None:
        self.attempts: defaultdict[str, int] = defaultdict(int)
        self.running = 0
        self.max_running = 0
        self.behaviors = behaviors or {}

    async def execute(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        self.attempts[node.id] += 1
        if node.type.value in {"start", "end"}:
            return None
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            behavior = self.behaviors.get(node.id, {})
            delay = float(behavior.get("delay", 0))
            if delay:
                await asyncio.sleep(delay)
            failures = int(behavior.get("failures", 0))
            if self.attempts[node.id] <= failures:
                category = RetryCategory(str(behavior.get("category", "network_error")))
                raise NodeExecutionError("TRANSIENT", "temporary failure", category)
            if behavior.get("permanent_failure"):
                raise NodeExecutionError("PERMANENT", "permanent failure")
            return {"node": node.id, "attempt": self.attempts[node.id]}
        finally:
            self.running -= 1


def workflow(
    *,
    middle_nodes: list[dict[str, object]],
    edges: list[dict[str, str]],
    fail_fast: bool = True,
    timeout: int = 30,
) -> WorkflowDefinition:
    nodes: list[dict[str, object]] = [
        {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
        *middle_nodes,
        {"id": "end", "type": "end", "name": "结束", "position": {"x": 300, "y": 0}},
    ]
    return WorkflowDefinition.model_validate(
        {
            "nodes": nodes,
            "edges": edges,
            "settings": {
                "fail_fast": fail_fast,
                "concurrency": 20,
                "default_timeout_seconds": timeout,
            },
        }
    )


def api_node(node_id: str, **config: object) -> dict[str, object]:
    return {
        "id": node_id,
        "type": "api",
        "name": node_id.upper(),
        "position": {"x": 100, "y": 0},
        "config": {
            "api_definition_id": "00000000-0000-0000-0000-000000000001",
            **config,
        },
    }


@pytest.mark.asyncio
async def test_scheduler_runs_independent_branches_in_parallel() -> None:
    definition = workflow(
        middle_nodes=[
            api_node("a"),
            api_node("b"),
            api_node("c"),
            api_node("d"),
        ],
        edges=[
            {"id": "s-a", "source": "start", "target": "a"},
            {"id": "a-b", "source": "a", "target": "b"},
            {"id": "a-c", "source": "a", "target": "c"},
            {"id": "b-d", "source": "b", "target": "d"},
            {"id": "c-d", "source": "c", "target": "d"},
            {"id": "d-e", "source": "d", "target": "end"},
        ],
    )
    executor = ControlledExecutor({"b": {"delay": 0.02}, "c": {"delay": 0.02}})

    result = await WorkflowScheduler(executor).run(definition)

    assert result.status == "passed"
    assert executor.max_running == 2
    assert [record.status for record in result.records] == [
        NodeStatus.PASSED,
        NodeStatus.PASSED,
        NodeStatus.PASSED,
        NodeStatus.PASSED,
        NodeStatus.PASSED,
        NodeStatus.PASSED,
    ]
    assert result.context["node_outputs"]["a"] == {"node": "a", "attempt": 1}


@pytest.mark.asyncio
async def test_scheduler_reports_pending_running_and_terminal_node_states() -> None:
    definition = workflow(
        middle_nodes=[api_node("api")],
        edges=[
            {"id": "s-a", "source": "start", "target": "api"},
            {"id": "a-e", "source": "api", "target": "end"},
        ],
    )
    updates: list[NodeStatusUpdate] = []

    async def capture(update: NodeStatusUpdate) -> None:
        updates.append(update)

    result = await WorkflowScheduler(ControlledExecutor()).run(definition, on_node_status=capture)

    assert result.status is not None
    by_node: dict[str, list[NodeStatus]] = defaultdict(list)
    for update in updates:
        by_node[update.node_id].append(update.status)
    assert by_node == {
        "start": [NodeStatus.PENDING, NodeStatus.RUNNING, NodeStatus.PASSED],
        "api": [NodeStatus.PENDING, NodeStatus.RUNNING, NodeStatus.PASSED],
        "end": [NodeStatus.PENDING, NodeStatus.RUNNING, NodeStatus.PASSED],
    }


@pytest.mark.asyncio
async def test_scheduler_retries_only_configured_transient_failures() -> None:
    definition = workflow(
        middle_nodes=[api_node("api", max_retries=2)],
        edges=[
            {"id": "s-a", "source": "start", "target": "api"},
            {"id": "a-e", "source": "api", "target": "end"},
        ],
    )
    executor = ControlledExecutor({"api": {"failures": 2}})

    result = await WorkflowScheduler(executor).run(definition)

    api_record = result.records[1]
    assert result.status == "passed"
    assert api_record.attempts == 3


@pytest.mark.asyncio
async def test_scheduler_propagates_failure_without_stopping_independent_branch() -> None:
    definition = workflow(
        middle_nodes=[
            api_node("failed"),
            api_node("independent"),
            api_node("dependent"),
        ],
        edges=[
            {"id": "s-f", "source": "start", "target": "failed"},
            {"id": "s-i", "source": "start", "target": "independent"},
            {"id": "f-d", "source": "failed", "target": "dependent"},
            {"id": "d-e", "source": "dependent", "target": "end"},
            {"id": "i-e", "source": "independent", "target": "end"},
        ],
        fail_fast=False,
    )

    result = await WorkflowScheduler(
        ControlledExecutor({"failed": {"permanent_failure": True}})
    ).run(definition)

    by_id = {record.node_id: record.status for record in result.records}
    assert result.status == "failed"
    assert by_id == {
        "start": NodeStatus.PASSED,
        "failed": NodeStatus.FAILED,
        "independent": NodeStatus.PASSED,
        "dependent": NodeStatus.SKIPPED,
        "end": NodeStatus.SKIPPED,
    }


@pytest.mark.asyncio
async def test_scheduler_cancels_running_and_pending_nodes() -> None:
    definition = workflow(
        middle_nodes=[api_node("slow")],
        edges=[
            {"id": "s-a", "source": "start", "target": "slow"},
            {"id": "a-e", "source": "slow", "target": "end"},
        ],
    )
    token = CancellationToken()
    executor = ControlledExecutor({"slow": {"delay": 5}})
    task = asyncio.create_task(WorkflowScheduler(executor).run(definition, cancellation=token))
    await asyncio.sleep(0.02)
    token.cancel()

    result = await task

    assert result.status == "cancelled"
    assert result.records[1].status is NodeStatus.CANCELLED
    assert result.records[2].status is NodeStatus.CANCELLED


@pytest.mark.asyncio
async def test_scheduler_debug_scope_executes_only_selected_ancestors() -> None:
    definition = workflow(
        middle_nodes=[api_node("first"), api_node("breakpoint"), api_node("after")],
        edges=[
            {"id": "s-f", "source": "start", "target": "first"},
            {"id": "f-b", "source": "first", "target": "breakpoint"},
            {"id": "b-a", "source": "breakpoint", "target": "after"},
            {"id": "a-e", "source": "after", "target": "end"},
        ],
    )
    executor = ControlledExecutor()

    result = await WorkflowScheduler(executor).run(
        definition,
        selected_node_ids=frozenset({"start", "first"}),
    )

    by_id = {record.node_id: record for record in result.records}
    assert executor.attempts == {"start": 1, "first": 1}
    assert by_id["breakpoint"].status is NodeStatus.SKIPPED
    assert by_id["breakpoint"].error_code == "DEBUG_SCOPE_EXCLUDED"
    assert result.status == "passed"


@pytest.mark.asyncio
async def test_scheduler_debug_scope_rejects_unknown_nodes() -> None:
    definition = workflow(
        middle_nodes=[api_node("api")],
        edges=[
            {"id": "s-a", "source": "start", "target": "api"},
            {"id": "a-e", "source": "api", "target": "end"},
        ],
    )

    with pytest.raises(ValueError, match="unknown"):
        await WorkflowScheduler(ControlledExecutor()).run(
            definition,
            selected_node_ids=frozenset({"missing"}),
        )


def test_contract_rejects_unreachable_and_dangling_nodes() -> None:
    with pytest.raises(ValidationError, match="unreachable from start"):
        workflow(
            middle_nodes=[api_node("connected"), api_node("orphan")],
            edges=[
                {"id": "s-c", "source": "start", "target": "connected"},
                {"id": "c-e", "source": "connected", "target": "end"},
                {"id": "o-e", "source": "orphan", "target": "end"},
            ],
        )

    with pytest.raises(ValidationError, match="without a path to end"):
        workflow(
            middle_nodes=[api_node("connected"), api_node("dead")],
            edges=[
                {"id": "s-c", "source": "start", "target": "connected"},
                {"id": "c-e", "source": "connected", "target": "end"},
                {"id": "s-d", "source": "start", "target": "dead"},
            ],
        )
