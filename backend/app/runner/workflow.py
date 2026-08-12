import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import cast
from uuid import UUID

import httpx
from pydantic import JsonValue

from app.core.logging import redact
from app.domain.network import OutboundNetworkPolicy
from app.engine.scheduler import (
    CancellationToken,
    ExecutionContext,
    NodeStatusUpdate,
    WorkflowRunResult,
    WorkflowScheduler,
)
from app.observability.tracing import TracingNodeExecutor
from app.runner.results import (
    RunnerBatchChildResult,
    RunnerBatchExecutionResult,
    RunnerExecutionResult,
    RunnerSingleExecutionResult,
    RunnerWorkflowResult,
)
from app.services.workflow_runtime import WorkflowNodeExecutor
from app.services.workflows import WorkflowBatchPlan, WorkflowExecutionPlan, WorkflowRunPlan

RunnerProgressCallback = Callable[[UUID, NodeStatusUpdate], Awaitable[None]]


class RemoteWorkflowExecutor:
    """Executes an immutable plan without persisting a terminal database state."""

    async def execute(
        self,
        plan: WorkflowExecutionPlan,
        *,
        network_policy: OutboundNetworkPolicy,
        cancellation: CancellationToken,
        on_progress: RunnerProgressCallback | None = None,
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
                    )
                    return RunnerBatchChildResult(
                        execution_id=child.execution_id,
                        result=RunnerWorkflowResult.from_domain(result),
                    )

            children = await asyncio.gather(*(execute_child(child) for child in plan.children))
            return RunnerBatchExecutionResult(
                execution_id=plan.execution_id,
                children=tuple(children),
            )
        result = await self._execute_run(
            plan,
            network_policy=network_policy,
            cancellation=cancellation,
            on_progress=on_progress,
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

            try:
                result = await WorkflowScheduler(TracingNodeExecutor(node_executor)).run(
                    plan.definition,
                    context=ExecutionContext(
                        workflow_variables=cast(dict[str, JsonValue], plan.definition.variables),
                        dataset_variables=plan.prepared.dataset_variables,
                        runtime_variables=cast(dict[str, JsonValue], plan.runtime_variables),
                    ),
                    cancellation=cancellation,
                    on_node_status=publish,
                )
            finally:
                await node_executor.close()
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
            context=cast(dict[str, JsonValue], redact(result.context)),
        )
