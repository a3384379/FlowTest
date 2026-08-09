from typing import Protocol
from uuid import UUID

from celery import Celery

from app.services.workflows import WorkflowExecutionPlan


class WorkflowDispatcher(Protocol):
    def start(self, plan: WorkflowExecutionPlan) -> None: ...


class TestPlanDispatcher(Protocol):
    def start_test_plan(self, run_id: UUID) -> None: ...


class CeleryTaskDispatcher:
    def __init__(self, celery: Celery) -> None:
        self._celery = celery

    def start(self, plan: WorkflowExecutionPlan) -> None:
        self._celery.send_task("flowtest.run_workflow", args=[str(plan.execution_id)])

    def start_test_plan(self, run_id: UUID) -> None:
        self._celery.send_task("flowtest.run_test_plan", args=[str(run_id)])
