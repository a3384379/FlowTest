import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import JsonValue

from app.engine.contracts import (
    ApiNodeConfig,
    DelayNodeConfig,
    NodeStatus,
    NodeType,
    RetryCategory,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowRunStatus,
)
from app.engine.results import NodeObservation, NodeResult, normalize_node_result


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
    result: NodeResult
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime
    input_hash: str | None = None


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
    result: NodeResult | None
    occurred_at: datetime
    input_hash: str | None = None
    context_snapshot: dict[str, JsonValue] | None = None


NodeStatusCallback = Callable[[NodeStatusUpdate], Awaitable[None]]


@dataclass(slots=True)
class ExecutionContext:
    workflow_variables: dict[str, JsonValue] = field(default_factory=dict)
    dataset_variables: dict[str, JsonValue] = field(default_factory=dict)
    runtime_variables: dict[str, JsonValue] = field(default_factory=dict)
    _node_outputs: dict[str, JsonValue] = field(default_factory=dict)
    _extracted_variables: dict[str, JsonValue] = field(default_factory=dict)
    _variable_sources: dict[str, JsonValue] = field(default_factory=dict)
    _node_observations: dict[str, list[NodeObservation]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._record_scope(self.workflow_variables, "workflow")
        self._record_scope(self.dataset_variables, "dataset")
        self._record_scope(self.runtime_variables, "runtime")

    def output_of(self, node_id: str) -> JsonValue:
        return self._node_outputs.get(node_id)

    def record_output(self, node_id: str, output: JsonValue) -> None:
        self._node_outputs[node_id] = output

    def record_observation(self, node_id: str, observation: NodeObservation) -> None:
        self._node_observations.setdefault(node_id, []).append(observation)

    def observations_of(self, node_id: str) -> tuple[NodeObservation, ...]:
        return tuple(self._node_observations.get(node_id, ()))

    def record_variable(
        self,
        name: str,
        value: JsonValue,
        *,
        node_id: str,
        path: str,
    ) -> None:
        self._extracted_variables[name] = value
        if name not in self.dataset_variables and name not in self.runtime_variables:
            self._variable_sources[name] = {
                "scope": "workflow",
                "node_id": node_id,
                "path": path,
            }

    def variable(self, name: str) -> JsonValue:
        if name in self.runtime_variables:
            return self.runtime_variables[name]
        if name in self.dataset_variables:
            return self.dataset_variables[name]
        if name in self._extracted_variables:
            return self._extracted_variables[name]
        return self.workflow_variables.get(name)

    def resolved_variables(self) -> dict[str, JsonValue]:
        return {
            **self.workflow_variables,
            **self._extracted_variables,
            **self.dataset_variables,
            **self.runtime_variables,
        }

    def snapshot(self) -> dict[str, JsonValue]:
        return {
            "runtime_variables": dict(self.runtime_variables),
            "workflow_variables": dict(self.workflow_variables),
            "dataset_variables": dict(self.dataset_variables),
            "resolved_variables": self.resolved_variables(),
            "extracted_variables": dict(self._extracted_variables),
            "variable_sources": dict(self._variable_sources),
            "node_outputs": dict(self._node_outputs),
        }

    def restore_checkpoint(
        self,
        *,
        node_id: str,
        output: JsonValue,
        extracted_variables: dict[str, JsonValue],
    ) -> None:
        self._node_outputs[node_id] = output
        self._extracted_variables.update(extracted_variables)

    def _record_scope(self, values: dict[str, JsonValue], scope: str) -> None:
        for name in values:
            self._variable_sources[name] = {"scope": scope, "node_id": None, "path": name}


class NodeExecutor(Protocol):
    async def execute(
        self, node: WorkflowNode, context: ExecutionContext
    ) -> NodeResult | JsonValue: ...


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
        selected_node_ids: frozenset[str] | None = None,
        resume_records: tuple[NodeRunRecord, ...] = (),
        resume_attempts: dict[str, int] | None = None,
    ) -> WorkflowRunResult:
        run_context = context or ExecutionContext()
        token = cancellation or CancellationToken()
        nodes = {node.id: node for node in definition.nodes}
        incoming = _incoming_edges(definition)
        statuses = dict.fromkeys(nodes, NodeStatus.PENDING)
        records: dict[str, NodeRunRecord] = {}
        active: dict[asyncio.Task[NodeRunRecord], str] = {}
        notified: dict[str, NodeStatus] = {}
        attempt_offsets = resume_attempts or {}

        if selected_node_ids is not None:
            _exclude_unselected(nodes, statuses, records, selected_node_ids)
        _restore_records(nodes, statuses, records, run_context, resume_records)

        await _notify_status_changes(
            nodes, statuses, records, notified, run_context, on_node_status
        )

        while len(records) < len(nodes):
            if token.cancelled:
                await _cancel_active(active)
                _record_remaining(nodes, statuses, records, NodeStatus.CANCELLED)
                await _notify_status_changes(
                    nodes, statuses, records, notified, run_context, on_node_status
                )
                break

            _skip_blocked(nodes, incoming, statuses, records, run_context)
            _schedule_ready(
                definition,
                nodes,
                incoming,
                statuses,
                records,
                active,
                run_context,
                self._run_node,
                attempt_offsets,
            )
            await _notify_status_changes(
                nodes, statuses, records, notified, run_context, on_node_status
            )
            if not active:
                if len(records) < len(nodes):
                    _record_remaining(nodes, statuses, records, NodeStatus.SKIPPED)
                    await _notify_status_changes(
                        nodes, statuses, records, notified, run_context, on_node_status
                    )
                break

            cancellation_wait = asyncio.create_task(token.wait())
            done, _pending = await asyncio.wait(
                {*active, cancellation_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancellation_wait in done:
                await _cancel_active(active)
                _record_remaining(nodes, statuses, records, NodeStatus.CANCELLED)
                await _notify_status_changes(
                    nodes, statuses, records, notified, run_context, on_node_status
                )
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

            await _notify_status_changes(
                nodes, statuses, records, notified, run_context, on_node_status
            )

            if failed and definition.settings.fail_fast:
                await _cancel_active(active)
                _record_remaining(nodes, statuses, records, NodeStatus.CANCELLED)
                await _notify_status_changes(
                    nodes, statuses, records, notified, run_context, on_node_status
                )
                break

        ordered = tuple(records[node.id] for node in definition.nodes)
        status = _workflow_status(ordered)
        return WorkflowRunResult(status=status, records=ordered, context=run_context.snapshot())

    async def _run_node(
        self,
        node: WorkflowNode,
        context: ExecutionContext,
        default_timeout_seconds: int,
        initial_attempts: int = 0,
    ) -> NodeRunRecord:
        started_at = datetime.now(UTC)
        input_hash = _input_hash(node.id, context.snapshot())
        policy = _execution_policy(node, default_timeout_seconds)
        attempts = initial_attempts
        while True:
            attempts += 1
            failure: NodeExecutionError
            try:
                async with asyncio.timeout(policy.timeout_seconds):
                    result = normalize_node_result(await self._executor.execute(node, context))
                observations = context.observations_of(node.id)
                if observations and not result.observations:
                    result = result.model_copy(update={"observations": observations})
                error = result.error
                return _record(
                    node,
                    result.status,
                    attempts=attempts,
                    output=result.output,
                    result=result,
                    error_code=error.code if error else None,
                    error_message=error.message if error else None,
                    started_at=started_at,
                    input_hash=input_hash,
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
                    observations=context.observations_of(node.id),
                    input_hash=input_hash,
                )

            if attempts > policy.max_retries or failure.category not in policy.retry_on:
                return _failed_record(
                    node,
                    attempts,
                    started_at,
                    failure,
                    observations=context.observations_of(node.id),
                    input_hash=input_hash,
                )
            if policy.retry_delay_seconds:
                await asyncio.sleep(policy.retry_delay_seconds)


@dataclass(frozen=True, slots=True)
class _ExecutionPolicy:
    timeout_seconds: float
    max_retries: int
    retry_on: frozenset[RetryCategory]
    retry_delay_seconds: float


def _execution_policy(node: WorkflowNode, default_timeout_seconds: int) -> _ExecutionPolicy:
    if node.effective_type is NodeType.API:
        config = ApiNodeConfig.model_validate(node.effective_config)
        return _ExecutionPolicy(
            timeout_seconds=config.timeout_seconds or default_timeout_seconds,
            max_retries=config.max_retries,
            retry_on=frozenset(config.retry_on),
            retry_delay_seconds=config.retry_delay_seconds,
        )
    if node.effective_type is NodeType.DELAY:
        delay = DelayNodeConfig.model_validate(node.effective_config)
        return _ExecutionPolicy(
            timeout_seconds=delay.seconds + 1,
            max_retries=0,
            retry_on=frozenset(),
            retry_delay_seconds=0,
        )
    return _ExecutionPolicy(
        timeout_seconds=default_timeout_seconds,
        max_retries=0,
        retry_on=frozenset(),
        retry_delay_seconds=0,
    )


class _EdgeState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"


def _incoming_edges(definition: WorkflowDefinition) -> dict[str, list[WorkflowEdge]]:
    result: dict[str, list[WorkflowEdge]] = {node.id: [] for node in definition.nodes}
    for edge in definition.edges:
        result[edge.target].append(edge)
    return result


def _skip_blocked(
    nodes: dict[str, WorkflowNode],
    incoming: dict[str, list[WorkflowEdge]],
    statuses: dict[str, NodeStatus],
    records: dict[str, NodeRunRecord],
    context: ExecutionContext,
) -> None:
    changed = True
    while changed:
        changed = False
        for node_id, node in nodes.items():
            if statuses[node_id] is not NodeStatus.PENDING:
                continue
            states = [_edge_state(edge, statuses, records, context) for edge in incoming[node_id]]
            if states and _edges_require_skip(states):
                branch_not_selected = _EdgeState.BLOCKED not in states
                record = _record(
                    node,
                    NodeStatus.SKIPPED,
                    error_code=(
                        "BRANCH_NOT_SELECTED" if branch_not_selected else "UPSTREAM_BLOCKED"
                    ),
                    error_message=(
                        "条件分支未被选择" if branch_not_selected else "上游节点未成功完成"
                    ),
                )
                statuses[node_id] = record.status
                records[node_id] = record
                changed = True


def _schedule_ready(
    definition: WorkflowDefinition,
    nodes: dict[str, WorkflowNode],
    incoming: dict[str, list[WorkflowEdge]],
    statuses: dict[str, NodeStatus],
    records: dict[str, NodeRunRecord],
    active: dict[asyncio.Task[NodeRunRecord], str],
    context: ExecutionContext,
    runner: Callable[
        [WorkflowNode, ExecutionContext, int, int], Coroutine[Any, Any, NodeRunRecord]
    ],
    attempt_offsets: dict[str, int],
) -> None:
    capacity = definition.settings.concurrency - len(active)
    if capacity <= 0:
        return
    ready = [
        node
        for node_id, node in nodes.items()
        if statuses[node_id] is NodeStatus.PENDING
        and _edges_are_ready(
            [_edge_state(edge, statuses, records, context) for edge in incoming[node_id]]
        )
    ]
    for node in ready[:capacity]:
        statuses[node.id] = NodeStatus.RUNNING
        task: asyncio.Task[NodeRunRecord] = asyncio.create_task(
            runner(
                node,
                context,
                definition.settings.default_timeout_seconds,
                attempt_offsets.get(node.id, 0),
            )
        )
        active[task] = node.id


def _edge_state(
    edge: WorkflowEdge,
    statuses: dict[str, NodeStatus],
    records: dict[str, NodeRunRecord],
    context: ExecutionContext,
) -> _EdgeState:
    status = statuses[edge.source]
    if status in {NodeStatus.PENDING, NodeStatus.RUNNING}:
        return _EdgeState.PENDING
    if status is NodeStatus.SKIPPED:
        record = records.get(edge.source)
        return (
            _EdgeState.INACTIVE
            if record is not None and record.error_code == "BRANCH_NOT_SELECTED"
            else _EdgeState.BLOCKED
        )
    if status in {NodeStatus.FAILED, NodeStatus.CANCELLED}:
        return _EdgeState.BLOCKED
    if edge.condition is None:
        return _EdgeState.ACTIVE
    output = context.output_of(edge.source)
    matched = output.get("matched") if isinstance(output, dict) else None
    if not isinstance(matched, bool):
        return _EdgeState.BLOCKED
    expected = edge.condition == "true"
    return _EdgeState.ACTIVE if matched is expected else _EdgeState.INACTIVE


def _edges_are_ready(states: list[_EdgeState]) -> bool:
    if not states:
        return True
    return (
        _EdgeState.PENDING not in states
        and _EdgeState.BLOCKED not in states
        and (_EdgeState.ACTIVE in states)
    )


def _edges_require_skip(states: list[_EdgeState]) -> bool:
    if _EdgeState.PENDING in states:
        return False
    return _EdgeState.BLOCKED in states or _EdgeState.ACTIVE not in states


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


def _exclude_unselected(
    nodes: dict[str, WorkflowNode],
    statuses: dict[str, NodeStatus],
    records: dict[str, NodeRunRecord],
    selected_node_ids: frozenset[str],
) -> None:
    unknown = selected_node_ids - nodes.keys()
    if unknown:
        raise ValueError(f"Debug scope references unknown nodes: {sorted(unknown)}")
    for node_id, node in nodes.items():
        if node_id in selected_node_ids:
            continue
        statuses[node_id] = NodeStatus.SKIPPED
        records[node_id] = _record(
            node,
            NodeStatus.SKIPPED,
            error_code="DEBUG_SCOPE_EXCLUDED",
            error_message="节点不在本次调试范围内",
        )


def _restore_records(
    nodes: dict[str, WorkflowNode],
    statuses: dict[str, NodeStatus],
    records: dict[str, NodeRunRecord],
    context: ExecutionContext,
    resume_records: tuple[NodeRunRecord, ...],
) -> None:
    for record in resume_records:
        node = nodes.get(record.node_id)
        if node is None:
            raise ValueError(f"Resume checkpoint references unknown node: {record.node_id}")
        if record.status not in {
            NodeStatus.PASSED,
            NodeStatus.SKIPPED,
        }:
            continue
        statuses[record.node_id] = record.status
        records[record.node_id] = record
        if record.status is NodeStatus.PASSED:
            context.record_output(record.node_id, record.output)


def _failed_record(
    node: WorkflowNode,
    attempts: int,
    started_at: datetime,
    error: NodeExecutionError,
    *,
    observations: tuple[NodeObservation, ...] = (),
    input_hash: str | None = None,
) -> NodeRunRecord:
    return _record(
        node,
        NodeStatus.FAILED,
        attempts=attempts,
        output=error.output,
        error_code=error.code,
        error_message=error.message,
        result=NodeResult.failed(
            code=error.code,
            message=error.message,
            output=error.output,
            retryable=error.category is not None,
            observations=observations,
        ),
        started_at=started_at,
        input_hash=input_hash,
    )


def _record(
    node: WorkflowNode,
    status: NodeStatus,
    *,
    attempts: int = 0,
    output: JsonValue = None,
    result: NodeResult | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    started_at: datetime | None = None,
    input_hash: str | None = None,
) -> NodeRunRecord:
    return NodeRunRecord(
        node_id=node.id,
        node_type=node.type,
        name=node.name,
        status=status,
        attempts=attempts,
        output=output,
        result=result
        or NodeResult(
            status=status,
            output=output,
            error=(
                None
                if error_code is None or error_message is None
                else {
                    "code": error_code,
                    "message": error_message,
                    "retryable": False,
                }
            ),
        ),
        error_code=error_code,
        error_message=error_message,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        input_hash=input_hash,
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
    context: ExecutionContext,
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
                result=record.result if record else None,
                occurred_at=record.completed_at if record else datetime.now(UTC),
                input_hash=record.input_hash if record else None,
                context_snapshot=context.snapshot(),
            )
        )
        notified[node_id] = status


def _input_hash(node_id: str, context_snapshot: dict[str, JsonValue]) -> str:
    encoded = json.dumps(
        {"node_id": node_id, "context": context_snapshot},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
