import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import cast
from uuid import UUID

import httpx
from pydantic import JsonValue

from app.core.logging import redact
from app.domain.network import OutboundNetworkPolicy
from app.engine.contracts import NodeStatus
from app.engine.results import NodeResult
from app.engine.scheduler import (
    CancellationToken,
    ExecutionContext,
    NodeRunRecord,
    NodeStatusUpdate,
    RequestBudget,
    WorkflowRunResult,
    WorkflowScheduler,
    node_type_consumes_request,
)
from app.observability.tracing import TracingNodeExecutor
from app.runner.results import (
    RunnerBatchChildResult,
    RunnerBatchExecutionResult,
    RunnerExecutionResult,
    RunnerSingleExecutionResult,
    RunnerWorkflowResult,
)
from app.schemas.runner_fabric import RunnerCheckpointResume
from app.services.workflow_runtime import WorkflowNodeExecutor
from app.services.workflows import WorkflowBatchPlan, WorkflowExecutionPlan, WorkflowRunPlan

RunnerProgressCallback = Callable[[UUID, NodeStatusUpdate], Awaitable[None]]


class PreviewRuntimeBudgetExceeded(RuntimeError):
    """The governed dataset preview exceeded its shared wall-clock budget."""


class RemoteWorkflowExecutor:
    """Executes an immutable plan without persisting a terminal database state."""

    async def execute(
        self,
        plan: WorkflowExecutionPlan,
        *,
        network_policy: OutboundNetworkPolicy,
        cancellation: CancellationToken,
        on_progress: RunnerProgressCallback | None = None,
        resume_checkpoints: dict[str, list[RunnerCheckpointResume]] | None = None,
        reset_retry_budget: bool = False,
    ) -> RunnerExecutionResult:
        if isinstance(plan, WorkflowBatchPlan):
            semaphore = asyncio.Semaphore(plan.concurrency)

            async def execute_child(child: WorkflowRunPlan) -> RunnerBatchChildResult:
                async with semaphore:
                    result = await self._execute_run(
                        child,
                        network_policy=network_policy,
                        cancellation=cancellation,
                        on_progress=on_progress,
                        resume_checkpoints=(resume_checkpoints or {}).get(
                            str(child.execution_id), []
                        ),
                        reset_retry_budget=reset_retry_budget,
                    )
                    return RunnerBatchChildResult(
                        execution_id=child.execution_id,
                        result=RunnerWorkflowResult.from_domain(result),
                    )

            tasks = [asyncio.create_task(execute_child(child)) for child in plan.children]
            if plan.max_runtime_seconds is None:
                children = await asyncio.gather(*tasks)
            else:
                _done, pending = await asyncio.wait(
                    tasks,
                    timeout=plan.max_runtime_seconds,
                )
                if pending:
                    cancellation.cancel()
                    _done, cleanup_pending = await asyncio.wait(
                        pending,
                        timeout=plan.cleanup_timeout_seconds or 1,
                    )
                    for task in cleanup_pending:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise PreviewRuntimeBudgetExceeded(
                        "Sandbox Preview dataset runtime budget exceeded"
                    )
                children = [task.result() for task in tasks]
            return RunnerBatchExecutionResult(
                execution_id=plan.execution_id,
                children=tuple(children),
            )
        result = await self._execute_run(
            plan,
            network_policy=network_policy,
            cancellation=cancellation,
            on_progress=on_progress,
            resume_checkpoints=(resume_checkpoints or {}).get(str(plan.execution_id), []),
            reset_retry_budget=reset_retry_budget,
        )
        return RunnerSingleExecutionResult(
            execution_id=plan.execution_id,
            result=RunnerWorkflowResult.from_domain(result),
        )

    async def _execute_run(
        self,
        plan: WorkflowRunPlan,
        *,
        network_policy: OutboundNetworkPolicy,
        cancellation: CancellationToken,
        on_progress: RunnerProgressCallback | None,
        resume_checkpoints: list[RunnerCheckpointResume],
        reset_retry_budget: bool,
    ) -> WorkflowRunResult:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            node_executor = WorkflowNodeExecutor(
                client,
                plan.prepared.requests,
                plan.definition,
                network_policy,
                subflows=plan.prepared.subflows,
                data_nodes=plan.prepared.data_nodes,
                protocol_nodes=plan.prepared.protocol_nodes,
                event_nodes=plan.prepared.event_nodes,
            )

            async def publish(update: NodeStatusUpdate) -> None:
                if on_progress is not None:
                    await on_progress(plan.execution_id, update)

            context = ExecutionContext(
                workflow_variables=cast(dict[str, JsonValue], plan.definition.variables),
                dataset_variables=plan.prepared.dataset_variables,
                runtime_variables=cast(dict[str, JsonValue], plan.runtime_variables),
            )
            resume_records = tuple(_resume_record(item) for item in resume_checkpoints)
            resume_attempts = {
                node_id: max(
                    item.attempts for item in resume_checkpoints if item.node_id == node_id
                )
                for node_id in {item.node_id for item in resume_checkpoints}
            }
            for item in resume_checkpoints:
                context.restore_checkpoint(
                    node_id=item.node_id,
                    output=item.output,
                    extracted_variables=item.extracted_variables,
                )
            request_budget = _remaining_request_budget(plan.request_budget, resume_records)
            try:
                result = await WorkflowScheduler(TracingNodeExecutor(node_executor)).run(
                    plan.definition,
                    context=context,
                    cancellation=cancellation,
                    on_node_status=publish,
                    resume_records=resume_records,
                    resume_attempts=resume_attempts,
                    reset_retry_budget=reset_retry_budget,
                    shared_request_budget=request_budget,
                )
            finally:
                await node_executor.close()
        context_snapshot = cast(dict[str, JsonValue], redact(result.context))
        if plan.request_budget is not None and request_budget is not None:
            context_snapshot["preview_request_budget"] = {
                "limit": plan.request_budget,
                "used": plan.request_budget - request_budget.remaining,
                "remaining": request_budget.remaining,
            }
        return WorkflowRunResult(
            status=result.status,
            records=tuple(
                replace(
                    record,
                    output=cast(JsonValue, redact(record.output)),
                    result=record.result.model_copy(
                        update={"output": cast(JsonValue, redact(record.result.output))}
                    ),
                )
                for record in result.records
            ),
            context=context_snapshot,
            main_status=result.main_status,
            cleanup_status=result.cleanup_status,
            cleanup_report=result.cleanup_report,
        )


def _remaining_request_budget(
    limit: int | None,
    records: tuple[NodeRunRecord, ...],
) -> RequestBudget | None:
    if limit is None:
        return None
    attempts: dict[str, int] = {}
    for record in records:
        if node_type_consumes_request(record.node_type):
            attempts[record.node_id] = max(attempts.get(record.node_id, 0), record.attempts)
    return RequestBudget(max(limit - sum(attempts.values()), 0))


def _resume_record(checkpoint: RunnerCheckpointResume) -> NodeRunRecord:
    result = checkpoint.result or NodeResult(status=NodeStatus.CANCELLED)
    return NodeRunRecord(
        node_id=checkpoint.node_id,
        node_type=checkpoint.node_type,
        name=checkpoint.name,
        status=checkpoint.status,
        attempts=checkpoint.attempts,
        output=checkpoint.output,
        result=result,
        error_code=checkpoint.error_code,
        error_message=checkpoint.error_message,
        started_at=checkpoint.started_at,
        completed_at=checkpoint.completed_at,
        input_hash=checkpoint.input_hash,
        phase=checkpoint.phase,
        best_effort=checkpoint.best_effort,
    )
