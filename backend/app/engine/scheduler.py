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
    CleanupRunWhen,
    DelayNodeConfig,
    NodeStatus,
    NodeType,
    RetryCategory,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPhase,
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
    phase: WorkflowPhase = WorkflowPhase.MAIN
    best_effort: bool = False


@dataclass(frozen=True, slots=True)
class CleanupWarning:
    code: str
    node_id: str
    message: str


@dataclass(frozen=True, slots=True)
class CleanupReport:
    activated_node_ids: tuple[str, ...]
    skipped_node_ids: tuple[str, ...]
    required_failures: tuple[str, ...]
    best_effort_failures: tuple[str, ...]
    warnings: tuple[CleanupWarning, ...]
    force_cancel_skipped: bool = False


@dataclass(frozen=True, slots=True)
class WorkflowRunResult:
    status: WorkflowRunStatus
    records: tuple[NodeRunRecord, ...]
    context: dict[str, JsonValue]
    main_status: WorkflowRunStatus | None = None
    cleanup_status: WorkflowRunStatus | None = None
    cleanup_report: CleanupReport | None = None


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
    started_at: datetime | None = None
    input_hash: str | None = None
    context_snapshot: dict[str, JsonValue] | None = None
    phase: WorkflowPhase = WorkflowPhase.MAIN
    best_effort: bool = False
    request_reserved: bool = False


NodeStatusCallback = Callable[[NodeStatusUpdate], Awaitable[None]]
NESTED_CHECKPOINT_PREFIX = "__nested_request__:"


@dataclass(slots=True)
class RequestBudget:
    remaining: int
    parent: "RequestBudget | None" = None

    def claim(self) -> bool:
        if not self.can_claim():
            return False
        self._consume()
        return True

    def can_claim(self, amount: int = 1) -> bool:
        return (
            amount >= 0
            and self.remaining >= amount
            and (self.parent is None or self.parent.can_claim(amount))
        )

    def _consume(self) -> None:
        self.remaining -= 1
        if self.parent is not None:
            self.parent._consume()


@dataclass(slots=True)
class ExecutionContext:
    workflow_variables: dict[str, JsonValue] = field(default_factory=dict)
    dataset_variables: dict[str, JsonValue] = field(default_factory=dict)
    runtime_variables: dict[str, JsonValue] = field(default_factory=dict)
    _node_outputs: dict[str, JsonValue] = field(default_factory=dict)
    _extracted_variables: dict[str, JsonValue] = field(default_factory=dict)
    _variable_sources: dict[str, JsonValue] = field(default_factory=dict)
    _node_observations: dict[str, list[NodeObservation]] = field(default_factory=dict)
    request_budget: RequestBudget | None = field(default=None, repr=False)
    status_callback: NodeStatusCallback | None = field(default=None, repr=False)
    checkpoint_scope: tuple[str, ...] = field(default=(), repr=False)
    checkpoint_phase: WorkflowPhase | None = field(default=None, repr=False)
    checkpoint_best_effort: bool = field(default=False, repr=False)
    nested_checkpoint_records: dict[str, NodeRunRecord] = field(
        default_factory=dict,
        repr=False,
    )
    reset_retry_budget: bool = field(default=False, repr=False)
    cancellation: "CancellationToken | None" = field(default=None, repr=False)

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
        self._force_event = asyncio.Event()

    def cancel(self, *, force: bool = False) -> None:
        self._event.set()
        if force:
            self._force_event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def force_cancelled(self) -> bool:
        return self._force_event.is_set()

    async def wait(self, *, force_only: bool = False) -> None:
        await (self._force_event if force_only else self._event).wait()


@dataclass(frozen=True, slots=True)
class _AttemptReservation:
    attempts: int
    started_at: datetime | None
    input_hash: str | None


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
        reset_retry_budget: bool = False,
        shared_request_budget: RequestBudget | None = None,
    ) -> WorkflowRunResult:
        run_context = context or ExecutionContext()
        if run_context.status_callback is None:
            run_context.status_callback = on_node_status
        if not run_context.nested_checkpoint_records:
            run_context.nested_checkpoint_records.update(
                {
                    record.node_id: record
                    for record in resume_records
                    if record.node_id.startswith(NESTED_CHECKPOINT_PREFIX)
                }
            )
        run_context.reset_retry_budget = reset_retry_budget
        token = cancellation or CancellationToken()
        run_context.cancellation = token
        main_nodes = tuple(node for node in definition.nodes if node.phase is WorkflowPhase.MAIN)
        main_ids = frozenset(node.id for node in main_nodes)
        main_edges = tuple(
            edge for edge in definition.edges if edge.source in main_ids and edge.target in main_ids
        )
        cleanup_nodes = tuple(
            node for node in definition.nodes if node.phase is WorkflowPhase.CLEANUP
        )
        freeze_main = (
            bool(cleanup_nodes)
            and not reset_retry_budget
            and _phase_checkpoint_complete(main_nodes, resume_records)
        )
        main_resume_records = tuple(
            record for record in resume_records if record.node_id in main_ids
        )
        main_runtime_records = tuple(
            record
            for record in resume_records
            if record.node_id in main_ids
            or (
                record.node_id.startswith(NESTED_CHECKPOINT_PREFIX)
                and record.phase is WorkflowPhase.MAIN
            )
        )
        main_budget = _remaining_request_budget(
            definition.run_policy.request_budget,
            main_nodes,
            resume_attempts,
            reset=reset_retry_budget,
            parent=shared_request_budget,
            resume_records=resume_records,
            phase=WorkflowPhase.MAIN,
        )
        run_context.request_budget = main_budget
        runtime_handle = _schedule_runtime_limit(
            token,
            definition.run_policy.max_runtime_seconds,
            main_runtime_records,
            reset=reset_retry_budget,
        )
        try:
            main = await self._run_phase(
                definition,
                nodes_for_phase=main_nodes,
                edges_for_phase=main_edges,
                context=run_context,
                cancellation=token,
                on_node_status=on_node_status,
                selected_node_ids=selected_node_ids,
                resume_records=main_resume_records,
                resume_attempts=resume_attempts,
                reset_retry_budget=reset_retry_budget,
                preserve_terminal_records=freeze_main,
                request_budget=main_budget,
            )
        finally:
            _cancel_runtime_limit(runtime_handle)
        if not cleanup_nodes or selected_node_ids is not None:
            return WorkflowRunResult(
                status=main.status,
                records=main.records,
                context=main.context,
                main_status=main.status,
            )
        return await self._run_cleanup(
            definition,
            main=main,
            cleanup_nodes=cleanup_nodes,
            context=run_context,
            cancellation=token,
            on_node_status=on_node_status,
            resume_records=resume_records,
            resume_attempts=resume_attempts,
            reset_retry_budget=reset_retry_budget,
            shared_request_budget=shared_request_budget,
        )

    async def _run_cleanup(
        self,
        definition: WorkflowDefinition,
        *,
        main: WorkflowRunResult,
        cleanup_nodes: tuple[WorkflowNode, ...],
        context: ExecutionContext,
        cancellation: CancellationToken,
        on_node_status: NodeStatusCallback | None,
        resume_records: tuple[NodeRunRecord, ...],
        resume_attempts: dict[str, int] | None,
        reset_retry_budget: bool,
        shared_request_budget: RequestBudget | None,
    ) -> WorkflowRunResult:
        activated = _activated_cleanup_nodes(cleanup_nodes, main)
        activated_ids = frozenset(node.id for node in activated)
        if cancellation.force_cancelled and definition.run_policy.force_cancel_skips_cleanup:
            cleanup_records = tuple(
                _record(
                    node,
                    NodeStatus.CANCELLED,
                    error_code="FORCE_CANCEL_SKIPPED_CLEANUP",
                    error_message="强制取消已显式跳过清理",
                )
                for node in cleanup_nodes
            )
            report = _cleanup_report(cleanup_records, activated_ids, force_skipped=True)
            return _combined_result(definition, main, cleanup_records, context, report)
        cleanup_edges = _cleanup_edges(definition, activated)
        cleanup_ids = frozenset(node.id for node in cleanup_nodes)
        request_budget_limit = definition.run_policy.cleanup_request_budget or sum(
            node.cleanup_retry_budget + 1 for node in activated
        )
        request_budget = _remaining_request_budget(
            request_budget_limit,
            activated,
            resume_attempts,
            reset=reset_retry_budget,
            parent=shared_request_budget,
            resume_records=resume_records,
            phase=WorkflowPhase.CLEANUP,
        )
        context.request_budget = request_budget
        cleanup_cancellation = (
            cancellation
            if definition.run_policy.force_cancel_skips_cleanup
            else CancellationToken()
        )
        cleanup_resume_records = tuple(
            record
            for record in resume_records
            if record.node_id in cleanup_ids
            or (
                record.node_id.startswith(NESTED_CHECKPOINT_PREFIX)
                and record.phase is WorkflowPhase.CLEANUP
            )
        )
        cleanup_runtime_handle = _schedule_runtime_limit(
            cleanup_cancellation,
            definition.run_policy.max_runtime_seconds,
            cleanup_resume_records,
            reset=reset_retry_budget,
        )
        try:
            cleanup = await self._run_phase(
                definition,
                nodes_for_phase=cleanup_nodes,
                edges_for_phase=cleanup_edges,
                context=context,
                cancellation=cleanup_cancellation,
                on_node_status=on_node_status,
                selected_node_ids=activated_ids,
                resume_records=tuple(
                    record for record in resume_records if record.node_id in cleanup_ids
                ),
                resume_attempts=resume_attempts,
                reset_retry_budget=reset_retry_budget,
                preserve_terminal_records=False,
                cancellation_force_only=definition.run_policy.force_cancel_skips_cleanup,
                request_budget=request_budget,
                fail_fast_on_error=False,
                excluded_code="CLEANUP_NOT_ACTIVATED",
                excluded_message="清理条件或目标未激活",
            )
        finally:
            _cancel_runtime_limit(cleanup_runtime_handle)
        report = _cleanup_report(cleanup.records, activated_ids)
        return _combined_result(definition, main, cleanup.records, context, report)

    async def _run_phase(
        self,
        definition: WorkflowDefinition,
        *,
        nodes_for_phase: tuple[WorkflowNode, ...],
        edges_for_phase: tuple[WorkflowEdge, ...],
        context: ExecutionContext,
        cancellation: CancellationToken,
        on_node_status: NodeStatusCallback | None,
        selected_node_ids: frozenset[str] | None,
        resume_records: tuple[NodeRunRecord, ...],
        resume_attempts: dict[str, int] | None,
        reset_retry_budget: bool,
        preserve_terminal_records: bool,
        cancellation_force_only: bool = False,
        request_budget: RequestBudget | None = None,
        fail_fast_on_error: bool = True,
        excluded_code: str = "DEBUG_SCOPE_EXCLUDED",
        excluded_message: str = "节点不在本次调试范围内",
    ) -> WorkflowRunResult:
        run_context = context
        token = cancellation
        nodes = {node.id: node for node in nodes_for_phase}
        incoming = _incoming_edges(nodes_for_phase, edges_for_phase)
        statuses = dict.fromkeys(nodes, NodeStatus.PENDING)
        records: dict[str, NodeRunRecord] = {}
        active: dict[asyncio.Task[NodeRunRecord], str] = {}
        notified: dict[str, NodeStatus] = {}
        attempt_offsets = resume_attempts or {}
        reservations = {
            record.node_id: _AttemptReservation(
                attempts=record.attempts,
                started_at=record.started_at,
                input_hash=record.input_hash,
            )
            for record in resume_records
            if record.attempts > 0
        }

        if selected_node_ids is not None:
            _exclude_unselected(
                nodes,
                statuses,
                records,
                selected_node_ids,
                error_code=excluded_code,
                error_message=excluded_message,
            )
        _restore_records(
            nodes,
            statuses,
            records,
            run_context,
            resume_records,
            preserve_terminal=preserve_terminal_records,
        )

        await _notify_status_changes(
            nodes, statuses, records, notified, run_context, on_node_status
        )

        while len(records) < len(nodes):
            if _phase_cancelled(token, force_only=cancellation_force_only):
                await _cancel_active(active)
                _record_remaining(nodes, statuses, records, NodeStatus.CANCELLED, reservations)
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
                reset_retry_budget,
                request_budget,
                on_node_status,
                reservations,
            )
            await _notify_status_changes(
                nodes, statuses, records, notified, run_context, on_node_status
            )
            if not active:
                if len(records) < len(nodes):
                    _record_remaining(nodes, statuses, records, NodeStatus.SKIPPED, reservations)
                    await _notify_status_changes(
                        nodes, statuses, records, notified, run_context, on_node_status
                    )
                break

            cancellation_wait = asyncio.create_task(token.wait(force_only=cancellation_force_only))
            done, _pending = await asyncio.wait(
                {*active, cancellation_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancellation_wait in done:
                await _cancel_active(active)
                _record_remaining(nodes, statuses, records, NodeStatus.CANCELLED, reservations)
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
                    failed = failed or fail_fast_on_error

            await _notify_status_changes(
                nodes, statuses, records, notified, run_context, on_node_status
            )

            if failed and definition.settings.fail_fast:
                await _cancel_active(active)
                _record_remaining(nodes, statuses, records, NodeStatus.CANCELLED, reservations)
                await _notify_status_changes(
                    nodes, statuses, records, notified, run_context, on_node_status
                )
                break

        ordered = tuple(records[node.id] for node in nodes_for_phase)
        status = _workflow_status(ordered)
        return WorkflowRunResult(
            status=status,
            records=ordered,
            context=run_context.snapshot(),
            main_status=(
                status
                if nodes_for_phase and nodes_for_phase[0].phase is WorkflowPhase.MAIN
                else None
            ),
            cleanup_status=(
                status
                if nodes_for_phase and nodes_for_phase[0].phase is WorkflowPhase.CLEANUP
                else None
            ),
        )

    async def _run_node(
        self,
        node: WorkflowNode,
        context: ExecutionContext,
        default_timeout_seconds: int,
        initial_attempts: int = 0,
        reset_retry_budget: bool = False,
        request_budget: RequestBudget | None = None,
        on_node_status: NodeStatusCallback | None = None,
        reservations: dict[str, _AttemptReservation] | None = None,
    ) -> NodeRunRecord:
        started_at = datetime.now(UTC)
        input_hash = _input_hash(node.id, context.snapshot())
        policy = _execution_policy(node, default_timeout_seconds)
        attempts = initial_attempts
        budget_attempts = 0 if reset_retry_budget else initial_attempts
        while True:
            if (
                request_budget is not None
                and _node_consumes_request(node)
                and not request_budget.claim()
            ):
                is_cleanup = node.phase is WorkflowPhase.CLEANUP
                return _failed_record(
                    node,
                    attempts,
                    started_at,
                    NodeExecutionError(
                        code=(
                            "CLEANUP_REQUEST_BUDGET_EXHAUSTED"
                            if is_cleanup
                            else "REQUEST_BUDGET_EXHAUSTED"
                        ),
                        message="清理请求预算已耗尽" if is_cleanup else "请求预算已耗尽",
                    ),
                    input_hash=input_hash,
                )
            attempts += 1
            budget_attempts += 1
            _store_attempt_reservation(
                reservations,
                node_id=node.id,
                attempts=attempts,
                started_at=started_at,
                input_hash=input_hash,
            )
            await _notify_attempt_reserved(
                node,
                attempts=attempts,
                started_at=started_at,
                input_hash=input_hash,
                context=context,
                callback=on_node_status,
            )
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

            if budget_attempts > policy.max_retries or failure.category not in policy.retry_on:
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


def _phase_checkpoint_complete(
    nodes: tuple[WorkflowNode, ...], records: tuple[NodeRunRecord, ...]
) -> bool:
    by_id = {record.node_id: record for record in records}
    return bool(nodes) and all(
        node.id in by_id and by_id[node.id].status.is_terminal for node in nodes
    )


def _remaining_request_budget(
    limit: int | None,
    nodes: tuple[WorkflowNode, ...],
    resume_attempts: dict[str, int] | None,
    *,
    reset: bool,
    parent: RequestBudget | None = None,
    resume_records: tuple[NodeRunRecord, ...] = (),
    phase: WorkflowPhase = WorkflowPhase.MAIN,
) -> RequestBudget | None:
    if limit is None:
        return parent
    used = 0
    if not reset:
        used = sum(
            (resume_attempts or {}).get(node.id, 0)
            for node in nodes
            if _node_consumes_request(node)
        )
        used += _nested_request_attempts(resume_records, phase=phase)
    return RequestBudget(max(limit - used, 0), parent=parent)


def _store_attempt_reservation(
    reservations: dict[str, _AttemptReservation] | None,
    *,
    node_id: str,
    attempts: int,
    started_at: datetime,
    input_hash: str,
) -> None:
    if reservations is not None:
        reservations[node_id] = _AttemptReservation(
            attempts=attempts,
            started_at=started_at,
            input_hash=input_hash,
        )


def _node_consumes_request(node: WorkflowNode) -> bool:
    return node_type_consumes_request(node.effective_type)


def node_type_consumes_request(node_type: NodeType) -> bool:
    return node_type in {
        NodeType.API,
        NodeType.SQL,
        NodeType.REDIS,
        NodeType.CAPABILITY,
    }


def _nested_request_attempts(
    records: tuple[NodeRunRecord, ...],
    *,
    phase: WorkflowPhase,
) -> int:
    attempts: dict[str, int] = {}
    for record in records:
        if (
            record.node_id.startswith(NESTED_CHECKPOINT_PREFIX)
            and record.phase is phase
            and node_type_consumes_request(record.node_type)
        ):
            attempts[record.node_id] = max(attempts.get(record.node_id, 0), record.attempts)
    return sum(attempts.values())


def _schedule_runtime_limit(
    token: CancellationToken,
    limit_seconds: int | None,
    resume_records: tuple[NodeRunRecord, ...],
    *,
    reset: bool,
) -> asyncio.TimerHandle | None:
    if limit_seconds is None:
        return None
    used = 0.0 if reset else _recorded_runtime_seconds(resume_records)
    remaining = limit_seconds - used
    if remaining <= 0:
        token.cancel()
        return None
    return asyncio.get_running_loop().call_later(remaining, token.cancel)


def _recorded_runtime_seconds(records: tuple[NodeRunRecord, ...]) -> float:
    started = [record.started_at for record in records if record.started_at is not None]
    if not started:
        return 0.0
    now = datetime.now(UTC)
    completed = [
        now if record.status is NodeStatus.RUNNING else record.completed_at for record in records
    ]
    return max(0.0, (max(completed) - min(started)).total_seconds())


def _cancel_runtime_limit(handle: asyncio.TimerHandle | None) -> None:
    if handle is not None:
        handle.cancel()


def _phase_cancelled(token: CancellationToken, *, force_only: bool) -> bool:
    return token.force_cancelled if force_only else token.cancelled


def _activated_cleanup_nodes(
    nodes: tuple[WorkflowNode, ...], main: WorkflowRunResult
) -> tuple[WorkflowNode, ...]:
    records = {record.node_id: record for record in main.records}
    outcome = {
        WorkflowRunStatus.PASSED: CleanupRunWhen.SUCCESS,
        WorkflowRunStatus.FAILED: CleanupRunWhen.FAILURE,
        WorkflowRunStatus.CANCELLED: CleanupRunWhen.CANCEL,
    }[main.status]
    return tuple(
        node
        for node in nodes
        if node.run_when in {CleanupRunWhen.ALWAYS, outcome}
        and (
            not node.cleanup_for
            or any(
                target in records and records[target].attempts > 0 for target in node.cleanup_for
            )
        )
    )


def _cleanup_edges(
    definition: WorkflowDefinition, nodes: tuple[WorkflowNode, ...]
) -> tuple[WorkflowEdge, ...]:
    ranks = _main_node_ranks(definition)
    cleanup_ranks = {
        node.id: max((ranks[target] for target in node.cleanup_for), default=0) for node in nodes
    }
    ordered_pairs = sorted(
        (source.id, target.id)
        for source in nodes
        for target in nodes
        if cleanup_ranks[source.id] > cleanup_ranks[target.id]
    )
    return tuple(
        WorkflowEdge(id=f"cleanup-order-{index}", source=source, target=target)
        for index, (source, target) in enumerate(ordered_pairs, start=1)
    )


def _main_node_ranks(definition: WorkflowDefinition) -> dict[str, int]:
    main_ids = {node.id for node in definition.nodes if node.phase is WorkflowPhase.MAIN}
    ranks = dict.fromkeys(main_ids, 0)
    edges = [
        edge for edge in definition.edges if edge.source in main_ids and edge.target in main_ids
    ]
    for _ in range(len(main_ids)):
        changed = False
        for edge in edges:
            candidate = ranks[edge.source] + 1
            if candidate > ranks[edge.target]:
                ranks[edge.target] = candidate
                changed = True
        if not changed:
            break
    return ranks


def _cleanup_report(
    records: tuple[NodeRunRecord, ...],
    activated_ids: frozenset[str],
    *,
    force_skipped: bool = False,
) -> CleanupReport:
    failures = tuple(
        record
        for record in records
        if record.node_id in activated_ids and _cleanup_record_failed(record)
    )
    best_effort = tuple(record.node_id for record in failures if record.best_effort)
    required = tuple(record.node_id for record in failures if not record.best_effort)
    warnings = tuple(
        CleanupWarning(
            code="BEST_EFFORT_CLEANUP_FAILED",
            node_id=record.node_id,
            message=record.error_message or "Best-effort 清理失败",
        )
        for record in failures
        if record.best_effort
    )
    return CleanupReport(
        activated_node_ids=tuple(sorted(activated_ids)),
        skipped_node_ids=tuple(
            record.node_id for record in records if record.node_id not in activated_ids
        ),
        required_failures=required,
        best_effort_failures=best_effort,
        warnings=warnings,
        force_cancel_skipped=force_skipped,
    )


def _cleanup_record_failed(record: NodeRunRecord) -> bool:
    return record.status in {NodeStatus.FAILED, NodeStatus.CANCELLED} or (
        record.status is NodeStatus.SKIPPED and record.error_code != "CLEANUP_NOT_ACTIVATED"
    )


def _combined_result(
    definition: WorkflowDefinition,
    main: WorkflowRunResult,
    cleanup_records: tuple[NodeRunRecord, ...],
    context: ExecutionContext,
    report: CleanupReport,
) -> WorkflowRunResult:
    records = {record.node_id: record for record in (*main.records, *cleanup_records)}
    cleanup_status = _cleanup_run_status(cleanup_records, report)
    status = main.status
    if main.status is WorkflowRunStatus.PASSED and report.required_failures:
        status = WorkflowRunStatus.FAILED
    return WorkflowRunResult(
        status=status,
        records=tuple(records[node.id] for node in definition.nodes),
        context=context.snapshot(),
        main_status=main.status,
        cleanup_status=cleanup_status,
        cleanup_report=report,
    )


def _cleanup_run_status(
    records: tuple[NodeRunRecord, ...], report: CleanupReport
) -> WorkflowRunStatus:
    if report.force_cancel_skipped:
        return WorkflowRunStatus.CANCELLED
    if report.required_failures or report.best_effort_failures:
        return WorkflowRunStatus.FAILED
    if any(record.status is NodeStatus.CANCELLED for record in records):
        return WorkflowRunStatus.CANCELLED
    return WorkflowRunStatus.PASSED


def _execution_policy(node: WorkflowNode, default_timeout_seconds: int) -> _ExecutionPolicy:
    if node.effective_type is NodeType.API:
        config = ApiNodeConfig.model_validate(node.effective_config)
        return _ExecutionPolicy(
            timeout_seconds=(
                node.cleanup_timeout_seconds
                if node.phase is WorkflowPhase.CLEANUP
                else config.timeout_seconds or default_timeout_seconds
            ),
            max_retries=(
                node.cleanup_retry_budget
                if node.phase is WorkflowPhase.CLEANUP
                else config.max_retries
            ),
            retry_on=frozenset(config.retry_on),
            retry_delay_seconds=config.retry_delay_seconds,
        )
    if node.effective_type is NodeType.DELAY:
        delay = DelayNodeConfig.model_validate(node.effective_config)
        return _ExecutionPolicy(
            timeout_seconds=(
                node.cleanup_timeout_seconds
                if node.phase is WorkflowPhase.CLEANUP
                else delay.seconds + 1
            ),
            max_retries=(node.cleanup_retry_budget if node.phase is WorkflowPhase.CLEANUP else 0),
            retry_on=(
                frozenset({RetryCategory.NETWORK_ERROR})
                if node.phase is WorkflowPhase.CLEANUP
                else frozenset()
            ),
            retry_delay_seconds=0,
        )
    return _ExecutionPolicy(
        timeout_seconds=(
            node.cleanup_timeout_seconds
            if node.phase is WorkflowPhase.CLEANUP
            else default_timeout_seconds
        ),
        max_retries=(node.cleanup_retry_budget if node.phase is WorkflowPhase.CLEANUP else 0),
        retry_on=(frozenset(RetryCategory) if node.phase is WorkflowPhase.CLEANUP else frozenset()),
        retry_delay_seconds=0,
    )


class _EdgeState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"


def _incoming_edges(
    nodes: tuple[WorkflowNode, ...], edges: tuple[WorkflowEdge, ...]
) -> dict[str, list[WorkflowEdge]]:
    result: dict[str, list[WorkflowEdge]] = {node.id: [] for node in nodes}
    for edge in edges:
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
        [
            WorkflowNode,
            ExecutionContext,
            int,
            int,
            bool,
            RequestBudget | None,
            NodeStatusCallback | None,
            dict[str, _AttemptReservation] | None,
        ],
        Coroutine[Any, Any, NodeRunRecord],
    ],
    attempt_offsets: dict[str, int],
    reset_retry_budget: bool,
    request_budget: RequestBudget | None,
    on_node_status: NodeStatusCallback | None,
    reservations: dict[str, _AttemptReservation],
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
                reset_retry_budget,
                request_budget,
                on_node_status,
                reservations,
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
    record = records.get(edge.source)
    if record is not None and record.phase is WorkflowPhase.CLEANUP and record.status.is_terminal:
        return _EdgeState.ACTIVE
    if status is NodeStatus.SKIPPED:
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
    reservations: dict[str, _AttemptReservation],
) -> None:
    for node_id, node in nodes.items():
        if node_id not in records:
            reservation = reservations.get(node_id) if status is NodeStatus.CANCELLED else None
            statuses[node_id] = status
            records[node_id] = _record(
                node,
                status,
                attempts=reservation.attempts if reservation is not None else 0,
                started_at=reservation.started_at if reservation is not None else None,
                input_hash=reservation.input_hash if reservation is not None else None,
            )


def _exclude_unselected(
    nodes: dict[str, WorkflowNode],
    statuses: dict[str, NodeStatus],
    records: dict[str, NodeRunRecord],
    selected_node_ids: frozenset[str],
    *,
    error_code: str,
    error_message: str,
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
            error_code=error_code,
            error_message=error_message,
        )


def _restore_records(
    nodes: dict[str, WorkflowNode],
    statuses: dict[str, NodeStatus],
    records: dict[str, NodeRunRecord],
    context: ExecutionContext,
    resume_records: tuple[NodeRunRecord, ...],
    *,
    preserve_terminal: bool,
) -> None:
    for record in resume_records:
        node = nodes.get(record.node_id)
        if node is None:
            raise ValueError(f"Resume checkpoint references unknown node: {record.node_id}")
        if not preserve_terminal and record.status not in {
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
        phase=node.phase,
        best_effort=node.best_effort,
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
        if status is NodeStatus.RUNNING and record is None:
            notified[node_id] = status
            continue
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
                started_at=record.started_at if record else None,
                input_hash=record.input_hash if record else None,
                context_snapshot=context.snapshot(),
                phase=nodes[node_id].phase,
                best_effort=nodes[node_id].best_effort,
            )
        )
        notified[node_id] = status


async def _notify_attempt_reserved(
    node: WorkflowNode,
    *,
    attempts: int,
    started_at: datetime,
    input_hash: str,
    context: ExecutionContext,
    callback: NodeStatusCallback | None,
) -> None:
    if callback is None:
        return
    await callback(
        NodeStatusUpdate(
            node_id=node.id,
            node_type=node.type,
            name=node.name,
            status=NodeStatus.RUNNING,
            attempts=attempts,
            error_code=None,
            error_message=None,
            result=None,
            occurred_at=started_at,
            started_at=started_at,
            input_hash=input_hash,
            context_snapshot=context.snapshot(),
            phase=node.phase,
            best_effort=node.best_effort,
            request_reserved=_node_consumes_request(node),
        )
    )


def _input_hash(node_id: str, context_snapshot: dict[str, JsonValue]) -> str:
    encoded = json.dumps(
        {"node_id": node_id, "context": context_snapshot},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
