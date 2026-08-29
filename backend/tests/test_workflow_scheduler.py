import asyncio
from collections import defaultdict
from dataclasses import replace
from datetime import timedelta

import pytest
from pydantic import JsonValue, ValidationError

from app.engine.contracts import NodeStatus, RetryCategory, WorkflowDefinition, WorkflowNode
from app.engine.scheduler import (
    CancellationToken,
    ExecutionContext,
    NodeExecutionError,
    NodeRunRecord,
    NodeStatusUpdate,
    WorkflowScheduler,
)
from app.observability.tracing import TracingNodeExecutor


class ControlledExecutor:
    def __init__(self, behaviors: dict[str, dict[str, object]] | None = None) -> None:
        self.attempts: defaultdict[str, int] = defaultdict(int)
        self.executed: list[str] = []
        self.running = 0
        self.max_running = 0
        self.behaviors = behaviors or {}

    async def execute(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        self.attempts[node.id] += 1
        self.executed.append(node.id)
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


@pytest.mark.asyncio
async def test_tracing_preserves_retryable_node_error() -> None:
    executor = ControlledExecutor(
        {"api": {"failures": 1, "category": RetryCategory.SERVER_ERROR.value}}
    )
    definition = workflow(
        middle_nodes=[api_node("api", max_retries=1)],
        edges=[
            {"id": "start-api", "source": "start", "target": "api"},
            {"id": "api-end", "source": "api", "target": "end"},
        ],
    )

    result = await WorkflowScheduler(TracingNodeExecutor(executor)).run(definition)

    record = next(item for item in result.records if item.node_id == "api")
    assert record.status is NodeStatus.PASSED
    assert record.attempts == 2


def workflow(
    *,
    middle_nodes: list[dict[str, object]],
    edges: list[dict[str, str]],
    fail_fast: bool = True,
    timeout: int = 30,
    run_policy: dict[str, object] | None = None,
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
            "run_policy": run_policy or {},
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


def cleanup_node(
    node_id: str,
    *,
    cleanup_for: list[str] | None = None,
    run_when: str = "always",
    best_effort: bool = False,
    retry_budget: int = 0,
    timeout: int = 30,
) -> dict[str, object]:
    node = api_node(node_id)
    node.update(
        {
            "phase": "cleanup",
            "run_when": run_when,
            "cleanup_for": cleanup_for or [],
            "best_effort": best_effort,
            "cleanup_timeout_seconds": timeout,
            "cleanup_retry_budget": retry_budget,
        }
    )
    return node


@pytest.mark.asyncio
async def test_scheduler_runs_cleanup_after_main_and_reports_both_results() -> None:
    definition = workflow(
        middle_nodes=[api_node("create"), cleanup_node("delete", cleanup_for=["create"])],
        edges=[
            {"id": "s-create", "source": "start", "target": "create"},
            {"id": "create-e", "source": "create", "target": "end"},
        ],
    )
    executor = ControlledExecutor()

    result = await WorkflowScheduler(executor).run(definition)

    assert result.status == "passed"
    assert result.main_status == "passed"
    assert result.cleanup_status == "passed"
    assert executor.executed == ["start", "create", "end", "delete"]
    assert result.cleanup_report is not None
    assert result.cleanup_report.activated_node_ids == ("delete",)


@pytest.mark.asyncio
async def test_scheduler_preserves_main_failure_when_required_cleanup_passes() -> None:
    definition = workflow(
        middle_nodes=[
            api_node("create"),
            cleanup_node("delete", cleanup_for=["create"], run_when="failure"),
        ],
        edges=[
            {"id": "s-create", "source": "start", "target": "create"},
            {"id": "create-e", "source": "create", "target": "end"},
        ],
    )

    result = await WorkflowScheduler(
        ControlledExecutor({"create": {"permanent_failure": True}})
    ).run(definition)

    assert result.status == "failed"
    assert result.main_status == "failed"
    assert result.cleanup_status == "passed"
    assert next(item for item in result.records if item.node_id == "delete").status == "passed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("best_effort", "expected_status", "warning_count"),
    [(False, "failed", 0), (True, "passed", 1)],
)
async def test_scheduler_reports_cleanup_failure_without_rewriting_main_result(
    best_effort: bool,
    expected_status: str,
    warning_count: int,
) -> None:
    definition = workflow(
        middle_nodes=[
            api_node("create"),
            cleanup_node("delete", cleanup_for=["create"], best_effort=best_effort),
        ],
        edges=[
            {"id": "s-create", "source": "start", "target": "create"},
            {"id": "create-e", "source": "create", "target": "end"},
        ],
    )

    result = await WorkflowScheduler(
        ControlledExecutor({"delete": {"permanent_failure": True}})
    ).run(definition)

    assert result.status == expected_status
    assert result.main_status == "passed"
    assert result.cleanup_status == "failed"
    assert result.cleanup_report is not None
    assert len(result.cleanup_report.warnings) == warning_count


@pytest.mark.asyncio
async def test_graceful_cancel_runs_cleanup_and_force_cancel_can_skip_it() -> None:
    definition = workflow(
        middle_nodes=[
            api_node("slow"),
            cleanup_node("delete", cleanup_for=["slow"], run_when="cancel"),
        ],
        edges=[
            {"id": "s-slow", "source": "start", "target": "slow"},
            {"id": "slow-e", "source": "slow", "target": "end"},
        ],
        run_policy={"force_cancel_skips_cleanup": True},
    )

    graceful_token = CancellationToken()
    graceful_executor = ControlledExecutor({"slow": {"delay": 5}})
    graceful_task = asyncio.create_task(
        WorkflowScheduler(graceful_executor).run(definition, cancellation=graceful_token)
    )
    await asyncio.sleep(0.02)
    graceful_token.cancel()
    graceful = await graceful_task

    assert graceful.status == "cancelled"
    assert graceful.cleanup_status == "passed"
    assert graceful_executor.attempts["delete"] == 1
    graceful_slow = next(record for record in graceful.records if record.node_id == "slow")
    assert graceful_slow.attempts == 1
    assert graceful_slow.input_hash is not None

    force_token = CancellationToken()
    force_executor = ControlledExecutor({"slow": {"delay": 5}})
    force_task = asyncio.create_task(
        WorkflowScheduler(force_executor).run(definition, cancellation=force_token)
    )
    await asyncio.sleep(0.02)
    force_token.cancel(force=True)
    forced = await force_task

    assert forced.status == "cancelled"
    assert forced.cleanup_status == "cancelled"
    assert force_executor.attempts["delete"] == 0
    assert forced.cleanup_report is not None
    assert forced.cleanup_report.force_cancel_skipped is True


@pytest.mark.asyncio
async def test_force_cancel_runs_cleanup_when_snapshot_policy_requires_it() -> None:
    definition = workflow(
        middle_nodes=[
            api_node("slow"),
            cleanup_node("delete", run_when="cancel"),
        ],
        edges=[
            {"id": "s-slow", "source": "start", "target": "slow"},
            {"id": "slow-e", "source": "slow", "target": "end"},
        ],
        run_policy={"force_cancel_skips_cleanup": False},
    )
    token = CancellationToken()
    executor = ControlledExecutor({"slow": {"delay": 5}})
    task = asyncio.create_task(WorkflowScheduler(executor).run(definition, cancellation=token))
    await asyncio.sleep(0.02)
    token.cancel(force=True)

    result = await task

    assert result.status == "cancelled"
    assert result.cleanup_status == "passed"
    assert executor.attempts["delete"] == 1
    assert result.cleanup_report is not None
    assert result.cleanup_report.force_cancel_skipped is False


@pytest.mark.asyncio
async def test_cleanup_has_bounded_retry_request_budget_and_reverse_ordering() -> None:
    definition = workflow(
        middle_nodes=[
            api_node("parent"),
            api_node("child"),
            cleanup_node("cleanup-parent", cleanup_for=["parent"]),
            cleanup_node(
                "cleanup-child",
                cleanup_for=["child"],
                retry_budget=1,
            ),
        ],
        edges=[
            {"id": "s-parent", "source": "start", "target": "parent"},
            {"id": "parent-child", "source": "parent", "target": "child"},
            {"id": "child-e", "source": "child", "target": "end"},
        ],
        run_policy={"cleanup_request_budget": 2},
    )
    executor = ControlledExecutor({"cleanup-child": {"failures": 1}})

    result = await WorkflowScheduler(executor).run(definition)

    assert result.status == "failed"
    child = next(item for item in result.records if item.node_id == "cleanup-child")
    parent = next(item for item in result.records if item.node_id == "cleanup-parent")
    assert child.attempts == 2
    assert parent.error_code == "CLEANUP_REQUEST_BUDGET_EXHAUSTED"
    assert parent.started_at is not None
    assert child.completed_at <= parent.started_at


def test_structural_cleanup_requires_an_explicit_request_budget() -> None:
    structural_cleanup = {
        "id": "cleanup-subflow",
        "type": "subflow",
        "name": "Cleanup subflow",
        "position": {"x": 100, "y": 100},
        "config": {
            "workflow_id": "00000000-0000-0000-0000-000000000001",
            "workflow_version": 1,
        },
        "phase": "cleanup",
    }
    edges = [{"id": "start-end", "source": "start", "target": "end"}]

    with pytest.raises(ValidationError, match="explicit cleanup request budget"):
        workflow(middle_nodes=[structural_cleanup], edges=edges)

    definition = workflow(
        middle_nodes=[structural_cleanup],
        edges=edges,
        run_policy={"cleanup_request_budget": 2},
    )
    assert definition.run_policy.cleanup_request_budget == 2


@pytest.mark.asyncio
async def test_cleanup_reclaim_preserves_consumed_request_budget() -> None:
    definition = workflow(
        middle_nodes=[
            api_node("create"),
            cleanup_node("cleanup-a", cleanup_for=["create"]),
            cleanup_node("cleanup-b", cleanup_for=["create"], retry_budget=1),
        ],
        edges=[
            {"id": "s-create", "source": "start", "target": "create"},
            {"id": "create-e", "source": "create", "target": "end"},
        ],
        run_policy={"cleanup_request_budget": 2},
    )
    initial = await WorkflowScheduler(ControlledExecutor()).run(definition)
    resumed_records = tuple(
        record
        for record in initial.records
        if record.phase == "main" or record.node_id == "cleanup-a"
    )
    resume_attempts = {record.node_id: record.attempts for record in resumed_records}
    executor = ControlledExecutor({"cleanup-b": {"failures": 1}})

    reclaimed = await WorkflowScheduler(executor).run(
        definition,
        resume_records=resumed_records,
        resume_attempts=resume_attempts,
    )

    cleanup_b = next(record for record in reclaimed.records if record.node_id == "cleanup-b")
    assert executor.attempts == {"cleanup-b": 1}
    assert cleanup_b.error_code == "CLEANUP_REQUEST_BUDGET_EXHAUSTED"


@pytest.mark.asyncio
async def test_main_request_budget_is_bounded_across_reclaim() -> None:
    definition = workflow(
        middle_nodes=[api_node("request-a"), api_node("request-b", max_retries=1)],
        edges=[
            {"id": "s-a", "source": "start", "target": "request-a"},
            {"id": "a-b", "source": "request-a", "target": "request-b"},
            {"id": "b-e", "source": "request-b", "target": "end"},
        ],
        run_policy={"request_budget": 2},
    )
    initial = await WorkflowScheduler(ControlledExecutor()).run(definition)
    resumed_records = tuple(
        record for record in initial.records if record.node_id in {"start", "request-a"}
    )
    resume_attempts = {record.node_id: record.attempts for record in resumed_records}
    executor = ControlledExecutor({"request-b": {"failures": 1}})

    reclaimed = await WorkflowScheduler(executor).run(
        definition,
        resume_records=resumed_records,
        resume_attempts=resume_attempts,
    )

    request_b = next(record for record in reclaimed.records if record.node_id == "request-b")
    assert executor.attempts == {"request-b": 1}
    assert request_b.error_code == "REQUEST_BUDGET_EXHAUSTED"


@pytest.mark.asyncio
async def test_budget_rejection_does_not_activate_cleanup_for_undispatched_node() -> None:
    definition = workflow(
        middle_nodes=[
            api_node("request-a"),
            api_node("request-b"),
            cleanup_node("cleanup-b", cleanup_for=["request-b"], run_when="failure"),
        ],
        edges=[
            {"id": "s-a", "source": "start", "target": "request-a"},
            {"id": "a-b", "source": "request-a", "target": "request-b"},
            {"id": "b-e", "source": "request-b", "target": "end"},
        ],
        run_policy={"request_budget": 1},
    )
    executor = ControlledExecutor()

    result = await WorkflowScheduler(executor).run(definition)

    request_b = next(record for record in result.records if record.node_id == "request-b")
    assert request_b.attempts == 0
    assert request_b.error_code == "REQUEST_BUDGET_EXHAUSTED"
    assert "request-b" not in executor.executed
    assert "cleanup-b" not in executor.executed
    assert result.cleanup_report is not None
    assert "cleanup-b" not in result.cleanup_report.activated_node_ids


@pytest.mark.asyncio
async def test_network_capabilities_consume_request_budget_and_reserve_attempts() -> None:
    def capability_node(node_id: str) -> dict[str, object]:
        return {
            "id": node_id,
            "type": "capability",
            "name": node_id,
            "position": {"x": 100, "y": 0},
            "capability_id": "graphql.request",
            "capability_version": "3.0.0",
            "configuration": {},
            "bindings": [],
        }

    definition = workflow(
        middle_nodes=[capability_node("query-a"), capability_node("query-b")],
        edges=[
            {"id": "s-a", "source": "start", "target": "query-a"},
            {"id": "a-b", "source": "query-a", "target": "query-b"},
            {"id": "b-e", "source": "query-b", "target": "end"},
        ],
        run_policy={"request_budget": 1},
    )
    updates: list[NodeStatusUpdate] = []
    executor = ControlledExecutor()

    async def capture(update: NodeStatusUpdate) -> None:
        updates.append(update)

    result = await WorkflowScheduler(executor).run(
        definition,
        on_node_status=capture,
    )

    query_b = next(record for record in result.records if record.node_id == "query-b")
    assert executor.executed == ["start", "query-a"]
    assert query_b.attempts == 0
    assert query_b.error_code == "REQUEST_BUDGET_EXHAUSTED"
    query_a_running = next(
        update
        for update in updates
        if update.node_id == "query-a" and update.status is NodeStatus.RUNNING
    )
    assert query_a_running.request_reserved is True


@pytest.mark.asyncio
async def test_main_runtime_limit_cancels_work_and_still_allows_cleanup() -> None:
    definition = workflow(
        middle_nodes=[
            api_node("slow"),
            cleanup_node("delete", run_when="cancel"),
        ],
        edges=[
            {"id": "s-slow", "source": "start", "target": "slow"},
            {"id": "slow-e", "source": "slow", "target": "end"},
        ],
        run_policy={"max_runtime_seconds": 1},
    )
    executor = ControlledExecutor({"slow": {"delay": 2}})

    result = await WorkflowScheduler(executor).run(definition)

    assert result.main_status == "cancelled"
    assert result.cleanup_status == "passed"
    assert executor.attempts["delete"] == 1


@pytest.mark.asyncio
async def test_main_runtime_limit_accounts_for_reclaim_checkpoint_time() -> None:
    definition = workflow(
        middle_nodes=[api_node("request")],
        edges=[
            {"id": "s-request", "source": "start", "target": "request"},
            {"id": "request-e", "source": "request", "target": "end"},
        ],
        run_policy={"max_runtime_seconds": 1},
    )
    initial = await WorkflowScheduler(ControlledExecutor()).run(definition)
    start = initial.records[0]
    expired_start = replace(
        start,
        started_at=start.completed_at - timedelta(seconds=2),
    )
    executor = ControlledExecutor()

    reclaimed = await WorkflowScheduler(executor).run(
        definition,
        resume_records=(expired_start,),
        resume_attempts={"start": 1},
    )

    assert reclaimed.main_status == "cancelled"
    assert executor.executed == []


@pytest.mark.asyncio
async def test_non_api_cleanup_uses_declared_cleanup_timeout() -> None:
    cleanup_delay = {
        "id": "cleanup-delay",
        "type": "delay",
        "name": "Cleanup delay",
        "position": {"x": 200, "y": 100},
        "config": {"seconds": 5},
        "phase": "cleanup",
        "cleanup_for": ["create"],
        "cleanup_timeout_seconds": 1,
    }
    definition = workflow(
        middle_nodes=[api_node("create"), cleanup_delay],
        edges=[
            {"id": "s-create", "source": "start", "target": "create"},
            {"id": "create-e", "source": "create", "target": "end"},
        ],
    )
    executor = ControlledExecutor({"cleanup-delay": {"delay": 2}})

    result = await WorkflowScheduler(executor).run(definition)

    cleanup = next(record for record in result.records if record.node_id == "cleanup-delay")
    assert cleanup.status == "failed"
    assert cleanup.error_code == "NODE_TIMEOUT"


@pytest.mark.asyncio
async def test_best_effort_cleanup_failure_does_not_block_required_cleanup() -> None:
    definition = workflow(
        middle_nodes=[
            api_node("parent"),
            api_node("child"),
            cleanup_node("cleanup-parent", cleanup_for=["parent"]),
            cleanup_node("cleanup-child", cleanup_for=["child"], best_effort=True),
        ],
        edges=[
            {"id": "s-parent", "source": "start", "target": "parent"},
            {"id": "parent-child", "source": "parent", "target": "child"},
            {"id": "child-e", "source": "child", "target": "end"},
        ],
    )
    executor = ControlledExecutor({"cleanup-child": {"permanent_failure": True}})

    result = await WorkflowScheduler(executor).run(definition)

    assert executor.executed[-2:] == ["cleanup-child", "cleanup-parent"]
    assert result.status == "passed"
    assert result.cleanup_report is not None
    assert result.cleanup_report.required_failures == ()
    assert result.cleanup_report.best_effort_failures == ("cleanup-child",)


@pytest.mark.asyncio
async def test_runner_reclaim_freezes_complete_main_result_before_cleanup_resume() -> None:
    definition = workflow(
        middle_nodes=[
            api_node("create"),
            cleanup_node("delete", cleanup_for=["create"], run_when="failure"),
        ],
        edges=[
            {"id": "s-create", "source": "start", "target": "create"},
            {"id": "create-e", "source": "create", "target": "end"},
        ],
    )
    first = await WorkflowScheduler(
        ControlledExecutor({"create": {"permanent_failure": True}})
    ).run(definition)
    main_records = tuple(record for record in first.records if record.phase == "main")
    resume_attempts = {record.node_id: record.attempts for record in main_records}
    reclaimed_executor = ControlledExecutor()

    reclaimed = await WorkflowScheduler(reclaimed_executor).run(
        definition,
        resume_records=main_records,
        resume_attempts=resume_attempts,
    )

    assert reclaimed.main_status == "failed"
    assert reclaimed.cleanup_status == "passed"
    assert reclaimed_executor.executed == ["delete"]


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
    api_running = next(
        update
        for update in updates
        if update.node_id == "api" and update.status is NodeStatus.RUNNING
    )
    assert api_running.attempts == 1
    assert api_running.started_at is not None
    assert api_running.input_hash is not None
    assert api_running.request_reserved is True


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
async def test_scheduler_resumes_completed_nodes_and_continues_attempt_numbers() -> None:
    definition = workflow(
        middle_nodes=[api_node("api")],
        edges=[
            {"id": "s-a", "source": "start", "target": "api"},
            {"id": "a-e", "source": "api", "target": "end"},
        ],
    )
    first = await WorkflowScheduler(ControlledExecutor({"api": {"permanent_failure": True}})).run(
        definition
    )
    first_by_id = {record.node_id: record for record in first.records}
    assert first.status == "failed"
    assert first_by_id["api"].input_hash is not None

    resumed_executor = ControlledExecutor()
    resumed = await WorkflowScheduler(resumed_executor).run(
        definition,
        resume_records=(first_by_id["start"],),
        resume_attempts={
            "start": first_by_id["start"].attempts,
            "api": first_by_id["api"].attempts,
        },
    )

    assert resumed.status == "passed"
    assert resumed_executor.attempts == {"api": 1, "end": 1}
    assert resumed.records[1].attempts == 2


@pytest.mark.asyncio
async def test_scheduler_retry_resets_failed_node_budget_without_reusing_attempt_number() -> None:
    definition = workflow(
        middle_nodes=[api_node("api", max_retries=1)],
        edges=[
            {"id": "s-a", "source": "start", "target": "api"},
            {"id": "a-e", "source": "api", "target": "end"},
        ],
    )
    first = await WorkflowScheduler(ControlledExecutor({"api": {"failures": 2}})).run(definition)
    first_by_id = {record.node_id: record for record in first.records}
    assert first_by_id["api"].status is NodeStatus.FAILED
    assert first_by_id["api"].attempts == 2

    resumed = await WorkflowScheduler(ControlledExecutor({"api": {"failures": 1}})).run(
        definition,
        resume_records=(first_by_id["start"],),
        resume_attempts={"start": 1, "api": 2},
    )
    assert resumed.status == "failed"
    assert resumed.records[1].attempts == 3

    retried_executor = ControlledExecutor({"api": {"failures": 1}})
    retried = await WorkflowScheduler(retried_executor).run(
        definition,
        resume_records=(first_by_id["start"],),
        resume_attempts={"start": 1, "api": 2},
        reset_retry_budget=True,
    )
    assert retried.status == "passed"
    assert retried_executor.attempts == {"api": 2, "end": 1}
    assert retried.records[1].attempts == 4


@pytest.mark.asyncio
async def test_scheduler_restores_checkpoint_output_and_emits_snapshot() -> None:
    definition = workflow(
        middle_nodes=[api_node("api")],
        edges=[
            {"id": "s-a", "source": "start", "target": "api"},
            {"id": "a-e", "source": "api", "target": "end"},
        ],
    )
    initial = await WorkflowScheduler(ControlledExecutor()).run(definition)
    records: dict[str, NodeRunRecord] = {record.node_id: record for record in initial.records}
    context = ExecutionContext()
    context.restore_checkpoint(
        node_id="start",
        output={"restored": True},
        extracted_variables={"from_checkpoint": "yes"},
    )
    updates: list[NodeStatusUpdate] = []

    async def capture(update: NodeStatusUpdate) -> None:
        updates.append(update)

    resumed = await WorkflowScheduler(ControlledExecutor()).run(
        definition,
        context=context,
        resume_records=(records["start"], records["api"]),
        on_node_status=capture,
    )

    assert resumed.context["node_outputs"]["start"] == records["start"].output
    assert resumed.context["extracted_variables"]["from_checkpoint"] == "yes"
    restored_api = next(item for item in updates if item.node_id == "api")
    assert restored_api.input_hash == records["api"].input_hash
    assert restored_api.context_snapshot is not None


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
