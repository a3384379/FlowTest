from typing import Protocol
from uuid import UUID

from celery import Celery

from app.observability.tracing import current_trace_headers
from app.services.workflows import WorkflowExecutionPlan


class WorkflowDispatcher(Protocol):
    def start(self, plan: WorkflowExecutionPlan) -> None: ...


class TestPlanDispatcher(Protocol):
    def start_test_plan(self, run_id: UUID, *, queue_name: str, priority: int) -> None: ...


class CeleryTaskDispatcher:
    def __init__(self, celery: Celery) -> None:
        self._celery = celery

    def start(self, plan: WorkflowExecutionPlan) -> None:
        queue_name = _workflow_queue(plan)
        self._celery.send_task(
            "flowtest.run_workflow",
            args=[str(plan.execution_id)],
            queue=queue_name,
            priority=5,
            headers=current_trace_headers(),
        )

    def start_test_plan(self, run_id: UUID, *, queue_name: str, priority: int) -> None:
        self._celery.send_task(
            "flowtest.run_test_plan",
            args=[str(run_id)],
            queue=queue_name,
            priority=priority,
            headers=current_trace_headers(),
        )


def _workflow_queue(plan: WorkflowExecutionPlan) -> str:
    definitions = (
        [child.definition for child in plan.children]
        if hasattr(plan, "children")
        else [plan.definition]
    )
    if any(
        node.type.value in {"sql", "redis"}
        for definition in definitions
        for node in definition.nodes
    ):
        return "data"
    return "general"
