import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import JsonValue

from app.engine.contracts import (
    ApiNodeConfig,
    NodeStatus,
    NodeType,
    RetryCategory,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowRunStatus,
)


@dataclass(frozen=True, slots=True)
class NodeExecutionError(Exception):
    code: str
    message: str
    category: RetryCategory | None = None
    output: JsonValue = None

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class NodeRunRecord:
    node_id: str
    node_type: NodeType
    name: str
    status: NodeStatus
    attempts: int
    output: JsonValue
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class WorkflowRunResult:
    status: WorkflowRunStatus
    records: tuple[NodeRunRecord, ...]
    context: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class NodeStatusUpdate:
    node_id: str
    node_type: NodeType
    name: str
    status: NodeStatus
    attempts: int
    error_code: str | None
    error_message: str | None
    occurred_at: datetime


NodeStatusCallback = Callable[[NodeStatusUpdate], Awaitable[None]]


@dataclass(slots=True)
class ExecutionContext:
    runtime_variables: dict[str, JsonValue] = field(default_factory=dict)
    _node_outputs: dict[str, JsonValue] = field(default_factory=dict)

    def output_of(self, node_id: str) -> JsonValue:
        return self._node_outputs.get(node_id)

    def record_output(self, node_id: str, output: JsonValue) -> None:
        self._node_outputs[node_id] = output

    def snapshot(self) -> dict[str, JsonValue]:
        return {
            "runtime_variables": dict(self.runtime_variables),
            "node_outputs": dict(self._node_outputs),
        }


class NodeExecutor(Protocol):
    async def execute(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue: ...


class CancellationToken:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


class WorkflowScheduler:
    def __init__(self, executor: NodeExecutor) -> None:
        self._executor = executor

    async def run(
        self,
        definition: WorkflowDefinition,
        *,
        context: ExecutionContext | None = None,
        cancellation: CancellationToken | None = None,
        on_node_status: NodeStatusCallback | None = None,
    ) -> WorkflowRunResult:
        run_context = context or ExecutionContext()
        token = cancellation or CancellationToken()
        nodes = {node.id: node for node in definition.nodes}
        predecessors = _predecessors(definition)
        statuses = dict.fromkeys(nodes, NodeStatus.PENDING)
        records: dict[str, NodeRunRecord] = {}
        active: dict[asyncio.Task[NodeRunRecord], str] = {}
        notified: dict[str, NodeStatus] = {}

        await _notify_status_changes(nodes, statuses, records, notified, on_node_status)

        while len(records) < len(nodes):
            if token.cancelled:
                await _cancel_active(active)
                _record_remaining(nodes, statuses, records, NodeStatus.CANCELLED)
                await _notify_status_changes(nodes, statuses, records, notified, on_node_status)
                break

            _skip_blocked(nodes, predecessors, statuses, records)
            _schedule_ready(
                definition,
                nodes,
                predecessors,
                statuses,
                active,
                run_context,
                self._run_node,
            )
            await _notify_status_changes(nodes, statuses, records, notified, on_node_status)
            if not active:
                if len(records) < len(nodes):
                    _record_remaining(nodes, statuses, records, NodeStatus.SKIPPED)
                    await _notify_status_changes(nodes, statuses, records, notified, on_node_status)
                break

            cancellation_wait = asyncio.create_task(token.wait())
            done, _pending = await asyncio.wait(
                {*active, cancellation_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancellation_wait in done:
                await _cancel_active(active)
                _record_remaining(nodes, statuses, records, NodeStatus.CANCELLED)
                await _notify_status_changes(nodes, statuses, records, notified, on_node_status)
                break
            cancellation_wait.cancel()
            await asyncio.gather(cancellation_wait, return_exceptions=True)

            failed = False
            completed_tasks = [task for task in tuple(active) if task in done]
            for task in completed_tasks:
                node_id = active.pop(task)
                record = task.result()
                records[node_id] = record
                statuses[node_id] = record.status
                if record.status is NodeStatus.PASSED:
                    run_context.record_output(node_id, record.output)
                else:
                    failed = True

            await _notify_status_changes(nodes, statuses, records, notified, on_node_status)

            if failed and definition.settings.fail_fast:
                await _cancel_active(active)
                _record_remaining(nodes, statuses, records, NodeStatus.CANCELLED)
                await _notify_status_changes(nodes, statuses, records, notified, on_node_status)
                break

        ordered = tuple(records[node.id] for node in definition.nodes)
        status = _workflow_status(ordered)
        return WorkflowRunResult(status=status, records=ordered, context=run_context.snapshot())

    async def _run_node(
        self,
        node: WorkflowNode,
        context: ExecutionContext,
        default_timeout_seconds: int,
    ) -> NodeRunRecord:
        started_at = datetime.now(UTC)
        policy = _execution_policy(node, default_timeout_seconds)
        attempts = 0
        while True:
            attempts += 1
            failure: NodeExecutionError
            try:
                async with asyncio.timeout(policy.timeout_seconds):
                    output = await self._executor.execute(node, context)
                return _record(
                    node,
                    NodeStatus.PASSED,
                    attempts=attempts,
                    output=output,
                    started_at=started_at,
                )
            except TimeoutError:
                failure = NodeExecutionError(
                    code="NODE_TIMEOUT",
                    message=f"节点在 {policy.timeout_seconds} 秒后超时",
                    category=RetryCategory.NETWORK_ERROR,
                )
            except NodeExecutionError as caught:
                failure = caught
            except asyncio.CancelledError:
                raise
            except Exception:
                return _failed_record(
                    node,
                    attempts,
                    started_at,
                    NodeExecutionError(
                        code="NODE_EXECUTION_ERROR",
                        message="节点执行发生未预期错误",
                    ),
                )

            if attempts > policy.max_retries or failure.category not in policy.retry_on:
                return _failed_record(node, attempts, started_at, failure)
            if policy.retry_delay_seconds:
                await asyncio.sleep(policy.retry_delay_seconds)


@dataclass(frozen=True, slots=True)
class _ExecutionPolicy:
    timeout_seconds: int
    max_retries: int
    retry_on: frozenset[RetryCategory]
    retry_delay_seconds: float


def _execution_policy(node: WorkflowNode, default_timeout_seconds: int) -> _ExecutionPolicy:
    if node.type is NodeType.API:
        config = ApiNodeConfig.model_validate(node.config)
        return _ExecutionPolicy(
            timeout_seconds=config.timeout_seconds or default_timeout_seconds,
            max_retries=config.max_retries,
            retry_on=frozenset(config.retry_on),
            retry_delay_seconds=config.retry_delay_seconds,
        )
    return _ExecutionPolicy(
        timeout_seconds=default_timeout_seconds,
        max_retries=0,
        retry_on=frozenset(),
        retry_delay_seconds=0,
    )


def _predecessors(definition: WorkflowDefinition) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {node.id: set() for node in definition.nodes}
    for edge in definition.edges:
        result[edge.target].add(edge.source)
    return result


def _skip_blocked(
    nodes: dict[str, WorkflowNode],
    predecessors: dict[str, set[str]],
    statuses: dict[str, NodeStatus],
    records: dict[str, NodeRunRecord],
) -> None:
    changed = True
    while changed:
        changed = False
        for node_id, node in nodes.items():
            if statuses[node_id] is not NodeStatus.PENDING:
                continue
            dependencies = predecessors[node_id]
            if (
                dependencies
                and all(statuses[item].is_terminal for item in dependencies)
                and any(statuses[item] is not NodeStatus.PASSED for item in dependencies)
            ):
                record = _record(node, NodeStatus.SKIPPED)
                statuses[node_id] = record.status
                records[node_id] = record
                changed = True


def _schedule_ready(
    definition: WorkflowDefinition,
    nodes: dict[str, WorkflowNode],
    predecessors: dict[str, set[str]],
    statuses: dict[str, NodeStatus],
    active: dict[asyncio.Task[NodeRunRecord], str],
    context: ExecutionContext,
    runner: Callable[[WorkflowNode, ExecutionContext, int], Coroutine[Any, Any, NodeRunRecord]],
) -> None:
    capacity = definition.settings.concurrency - len(active)
    if capacity <= 0:
        return
    ready = [
        node
        for node_id, node in nodes.items()
        if statuses[node_id] is NodeStatus.PENDING
        and all(statuses[item] is NodeStatus.PASSED for item in predecessors[node_id])
    ]
    for node in ready[:capacity]:
        statuses[node.id] = NodeStatus.RUNNING
        task: asyncio.Task[NodeRunRecord] = asyncio.create_task(
            runner(node, context, definition.settings.default_timeout_seconds)
        )
        active[task] = node.id


async def _cancel_active(active: dict[asyncio.Task[NodeRunRecord], str]) -> None:
    for task in active:
        task.cancel()
    await asyncio.gather(*active, return_exceptions=True)
    active.clear()


def _record_remaining(
    nodes: dict[str, WorkflowNode],
    statuses: dict[str, NodeStatus],
    records: dict[str, NodeRunRecord],
    status: NodeStatus,
) -> None:
    for node_id, node in nodes.items():
        if node_id not in records:
            statuses[node_id] = status
            records[node_id] = _record(node, status)


def _failed_record(
    node: WorkflowNode,
    attempts: int,
    started_at: datetime,
    error: NodeExecutionError,
) -> NodeRunRecord:
    return _record(
        node,
        NodeStatus.FAILED,
        attempts=attempts,
        output=error.output,
        error_code=error.code,
        error_message=error.message,
        started_at=started_at,
    )


def _record(
    node: WorkflowNode,
    status: NodeStatus,
    *,
    attempts: int = 0,
    output: JsonValue = None,
    error_code: str | None = None,
    error_message: str | None = None,
    started_at: datetime | None = None,
) -> NodeRunRecord:
    return NodeRunRecord(
        node_id=node.id,
        node_type=node.type,
        name=node.name,
        status=status,
        attempts=attempts,
        output=output,
        error_code=error_code,
        error_message=error_message,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )


def _workflow_status(records: tuple[NodeRunRecord, ...]) -> WorkflowRunStatus:
    if any(record.status is NodeStatus.FAILED for record in records):
        return WorkflowRunStatus.FAILED
    if any(record.status is NodeStatus.CANCELLED for record in records):
        return WorkflowRunStatus.CANCELLED
    return WorkflowRunStatus.PASSED


async def _notify_status_changes(
    nodes: dict[str, WorkflowNode],
    statuses: dict[str, NodeStatus],
    records: dict[str, NodeRunRecord],
    notified: dict[str, NodeStatus],
    callback: NodeStatusCallback | None,
) -> None:
    if callback is None:
        return
    for node_id, status in statuses.items():
        if notified.get(node_id) is status:
            continue
        record = records.get(node_id)
        await callback(
            NodeStatusUpdate(
                node_id=node_id,
                node_type=nodes[node_id].type,
                name=nodes[node_id].name,
                status=status,
                attempts=record.attempts if record else 0,
                error_code=record.error_code if record else None,
                error_message=record.error_message if record else None,
                occurred_at=record.completed_at if record else datetime.now(UTC),
            )
        )
        notified[node_id] = status
