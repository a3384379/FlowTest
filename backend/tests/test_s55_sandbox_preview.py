from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import respx
from httpx import Response
from sqlalchemy import func, select, update
from test_s51_mcp_flow_proposals import (
    _plan_chain,
    _proposal_payload,
    s51_context,  # noqa: F401 - imported pytest fixture
)

from app.core.encryption import secret_box
from app.core.errors import AppError
from app.domain.sandbox_preview import PreviewBudget
from app.engine.contracts import WorkflowDefinition
from app.engine.scheduler import CancellationToken
from app.models.api_assets import Environment, Secret
from app.models.sandbox_preview import SandboxPreviewApproval
from app.models.service_targets import ServiceEndpoint
from app.models.workflows import WorkflowExecution
from app.services.workflow_coordinator import WorkflowRunCoordinator
from app.services.workflow_runtime import PreparedSubflow
from app.services.workflow_snapshots import PreparedExecution, PreparedWorkflow
from app.services.workflows import (
    WorkflowBatchPlan,
    WorkflowRunPlan,
    WorkflowService,
    _bounded_preview_prepared_workflow,
    _validate_preview_target_classification,
)


@pytest.mark.asyncio
async def test_preview_dataset_runtime_budget_spans_queued_and_active_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled: dict[str, str] = {}

    class SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class EventBus:
        async def publish(self, _event: object) -> None:
            return None

    class CoordinatorWorkflowService:
        def __init__(self, _session: object) -> None:
            pass

        async def cancel_incomplete_batch(
            self,
            _execution_id: UUID,
            *,
            error_code: str = "",
            error_message: str = "",
        ) -> None:
            cancelled["code"] = error_code
            cancelled["message"] = error_message

        async def complete_batch(self, execution_id: UUID) -> object:
            return SimpleNamespace(
                id=execution_id,
                status="cancelled",
                error_code=cancelled["code"],
                error_message=cancelled["message"],
            )

    definition = _preview_test_definition(with_cleanup=True)
    prepared = PreparedExecution(snapshot={}, requests={}, dataset_variables={})
    children = tuple(
        WorkflowRunPlan(
            execution_id=uuid4(),
            actor_id=uuid4(),
            project_id=uuid4(),
            workflow_version=0,
            definition=definition,
            prepared=prepared,
            runtime_variables={},
        )
        for _index in range(2)
    )
    coordinator = WorkflowRunCoordinator(
        cast(Any, lambda: SessionContext()),
        cast(Any, EventBus()),
    )
    started: list[UUID] = []
    cleanup_started: list[UUID] = []

    async def slow_execution(
        child: WorkflowRunPlan,
        *,
        cancellation: object | None = None,
    ) -> object:
        started.append(child.execution_id)
        token = cast(CancellationToken, cancellation)
        await token.wait()
        cleanup_started.append(child.execution_id)
        return SimpleNamespace(id=child.execution_id, status="cancelled")

    async def publish_completion(execution: object) -> None:
        del execution

    monkeypatch.setattr(
        "app.services.workflow_coordinator.WorkflowService",
        CoordinatorWorkflowService,
    )
    monkeypatch.setattr(coordinator, "_execute", slow_execution)
    monkeypatch.setattr(coordinator, "_publish_completion", publish_completion)
    completed = await coordinator._execute_batch(
        WorkflowBatchPlan(
            execution_id=uuid4(),
            actor_id=uuid4(),
            project_id=uuid4(),
            workflow_version=0,
            children=children,
            concurrency=1,
            max_runtime_seconds=cast(int, 0.01),
            cleanup_timeout_seconds=cast(int, 0.01),
        )
    )

    assert completed.status == "cancelled"
    assert len(started) == 1
    assert cleanup_started == started
    assert cancelled["code"] == "PREVIEW_RUNTIME_BUDGET_EXCEEDED"


def test_preview_recursively_requires_and_bounds_subflow_cleanup() -> None:
    unsafe_leaf = _preview_test_definition(with_cleanup=False)
    safe_parent = _preview_test_definition(with_cleanup=True, subflow=True)
    unsafe_prepared = _preview_test_prepared_workflow(safe_parent, unsafe_leaf)

    with pytest.raises(AppError) as error_info:
        _bounded_preview_prepared_workflow(unsafe_prepared, PreviewBudget())
    assert error_info.value.code == "PREVIEW_CLEANUP_REQUIRED"

    budget = PreviewBudget(
        max_nodes=100,
        max_requests=10,
        max_dataset_rows=20,
        max_parallelism=2,
        max_runtime_seconds=120,
    )
    bounded = _bounded_preview_prepared_workflow(
        _preview_test_prepared_workflow(
            safe_parent,
            _preview_test_definition(with_cleanup=True),
        ),
        budget,
    )
    parent = bounded.runs[0].subflows["outer"]
    leaf = parent.subflows["nested"]
    for subflow in (parent, leaf):
        assert subflow.definition.settings.concurrency == 2
        assert subflow.definition.run_policy.request_budget == 10
        assert subflow.definition.run_policy.cleanup_request_budget == 10
        assert subflow.definition.run_policy.max_runtime_seconds == 120
    snapshot_policy = leaf.snapshot["workflow"]["definition"]["run_policy"]
    assert snapshot_policy["max_runtime_seconds"] == 120


def test_preview_rejects_targets_without_environment_classification() -> None:
    payload = _preview_test_definition(with_cleanup=True).model_dump(mode="json")
    payload["nodes"][1] = {
        "id": "work",
        "type": "capability",
        "name": "GraphQL production target",
        "position": {"x": 180, "y": 0},
        "capability_id": "graphql.request",
        "capability_version": "3.0.0",
        "configuration": {
            "schema_id": "00000000-0000-0000-0000-000000000301",
            "endpoint": "https://production.example.test/graphql",
            "operation": "query Health { health }",
        },
        "bindings": [],
    }
    definition = WorkflowDefinition.model_validate(payload)

    with pytest.raises(AppError) as error_info:
        _validate_preview_target_classification(definition, {})
    assert error_info.value.code == "PREVIEW_TARGET_CLASSIFICATION_REQUIRED"


@pytest.mark.asyncio
async def test_accepted_proposal_requires_sandbox_and_consumes_approval_once(
    s51_context: dict[str, Any],  # noqa: F811 - pytest injects the imported fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_context, plan, compilation = await _plan_chain(s51_context, with_cleanup=True)
    client = s51_context["client"]
    proposed = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers={**s51_context["mcp_headers"], "Idempotency-Key": "s55-proposal"},
        json={
            **_proposal_payload(s51_context, test_context, plan, compilation),
            "dry_run": False,
        },
    )
    assert proposed.status_code == 202, proposed.text
    change_set_id = proposed.json()["change_set_id"]
    reviewed = await client.post(
        f"/api/v1/projects/{s51_context['project_id']}/flow-specs/change-sets/"
        f"{change_set_id}/review",
        headers=s51_context["user_headers"],
        json={"accept": True, "note": "S55 sandbox preview review"},
    )
    assert reviewed.status_code == 200, reviewed.text

    production = await client.post(
        f"/api/v1/projects/{s51_context['project_id']}/flow-specs/change-sets/"
        f"{change_set_id}/preview-approvals",
        headers=s51_context["user_headers"],
        json={
            "environment_id": str(s51_context["production_environment_id"]),
            "executor_service_account_id": str(s51_context["service_account_id"]),
        },
    )
    assert production.status_code == 403
    assert production.json()["error"]["code"] == "PRODUCTION_PREVIEW_FORBIDDEN"

    target_bound = await client.post(
        f"/api/v1/projects/{s51_context['project_id']}/flow-specs/change-sets/"
        f"{change_set_id}/preview-approvals",
        headers=s51_context["user_headers"],
        json={
            "environment_id": str(s51_context["sandbox_environment_id"]),
            "executor_service_account_id": str(s51_context["service_account_id"]),
        },
    )
    assert target_bound.status_code == 201, target_bound.text
    assert len(target_bound.json()["environment_fingerprint"]) == 64
    async with s51_context["sessions"]() as session:
        endpoint = await session.scalar(
            select(ServiceEndpoint).where(
                ServiceEndpoint.environment_id == s51_context["sandbox_environment_id"]
            )
        )
        assert endpoint is not None
        original_base_url = endpoint.base_url
        endpoint.base_url = "https://changed-target.example.test"
        await session.commit()
    target_changed = await client.post(
        f"/api/v1/mcp/flow/proposals/{change_set_id}/preview-executions",
        headers={
            **s51_context["mcp_headers"],
            "Idempotency-Key": "s55-preview-changed-target",
        },
        json={
            "project_id": str(s51_context["project_id"]),
            "environment_id": str(s51_context["sandbox_environment_id"]),
            "approval_id": target_bound.json()["id"],
            "runtime_variables": {},
            "runtime_headers": {},
        },
    )
    assert target_changed.status_code == 409, target_changed.text
    assert target_changed.json()["error"]["code"] == "PREVIEW_APPROVAL_TARGET_CHANGED"
    async with s51_context["sessions"]() as session:
        endpoint = await session.scalar(
            select(ServiceEndpoint).where(
                ServiceEndpoint.environment_id == s51_context["sandbox_environment_id"]
            )
        )
        assert endpoint is not None
        endpoint.base_url = original_base_url
        await session.commit()
    input_changed = await client.post(
        f"/api/v1/mcp/flow/proposals/{change_set_id}/preview-executions",
        headers={
            **s51_context["mcp_headers"],
            "Idempotency-Key": "s55-preview-changed-input",
        },
        json={
            "project_id": str(s51_context["project_id"]),
            "environment_id": str(s51_context["sandbox_environment_id"]),
            "approval_id": target_bound.json()["id"],
            "runtime_variables": {"host": "production.example.test"},
            "runtime_headers": {},
        },
    )
    assert input_changed.status_code == 409, input_changed.text
    assert input_changed.json()["error"]["code"] == "PREVIEW_APPROVAL_INPUT_MISMATCH"

    async with s51_context["sessions"]() as session:
        endpoint = await session.scalar(
            select(ServiceEndpoint).where(
                ServiceEndpoint.environment_id == s51_context["sandbox_environment_id"]
            )
        )
        assert endpoint is not None
        endpoint.base_url = "https://{{secret.host}}"
        endpoint.secret_refs = ["host"]
        associated_data = (
            f"{s51_context['project_id']}:{s51_context['sandbox_environment_id']}:host".encode()
        )
        encrypted = secret_box.encrypt(
            "sandbox.example.test",
            associated_data=associated_data,
        )
        secret = Secret(
            project_id=s51_context["project_id"],
            environment_id=s51_context["sandbox_environment_id"],
            name="host",
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            created_by_id=endpoint.created_by_id,
        )
        session.add(secret)
        await session.commit()
    secret_bound = await client.post(
        f"/api/v1/projects/{s51_context['project_id']}/flow-specs/change-sets/"
        f"{change_set_id}/preview-approvals",
        headers=s51_context["user_headers"],
        json={
            "environment_id": str(s51_context["sandbox_environment_id"]),
            "executor_service_account_id": str(s51_context["service_account_id"]),
        },
    )
    assert secret_bound.status_code == 201, secret_bound.text
    async with s51_context["sessions"]() as session:
        secret = await session.scalar(
            select(Secret).where(
                Secret.environment_id == s51_context["sandbox_environment_id"],
                Secret.name == "host",
            )
        )
        assert secret is not None
        encrypted = secret_box.encrypt(
            "production.example.test",
            associated_data=(
                f"{s51_context['project_id']}:{s51_context['sandbox_environment_id']}:host"
            ).encode(),
        )
        secret.ciphertext = encrypted.ciphertext
        secret.nonce = encrypted.nonce
        await session.commit()
    secret_changed = await client.post(
        f"/api/v1/mcp/flow/proposals/{change_set_id}/preview-executions",
        headers={
            **s51_context["mcp_headers"],
            "Idempotency-Key": "s55-preview-changed-secret",
        },
        json={
            "project_id": str(s51_context["project_id"]),
            "environment_id": str(s51_context["sandbox_environment_id"]),
            "approval_id": secret_bound.json()["id"],
            "runtime_variables": {},
            "runtime_headers": {},
        },
    )
    assert secret_changed.status_code == 409, secret_changed.text
    assert secret_changed.json()["error"]["code"] == "PREVIEW_APPROVAL_TARGET_CHANGED"
    async with s51_context["sessions"]() as session:
        endpoint = await session.scalar(
            select(ServiceEndpoint).where(
                ServiceEndpoint.environment_id == s51_context["sandbox_environment_id"]
            )
        )
        secret = await session.scalar(
            select(Secret).where(
                Secret.environment_id == s51_context["sandbox_environment_id"],
                Secret.name == "host",
            )
        )
        assert endpoint is not None and secret is not None
        endpoint.base_url = original_base_url
        endpoint.secret_refs = []
        await session.delete(secret)
        await session.commit()

    original_prepare = WorkflowService.prepare_preview_execution

    async def prepare_with_reversible_target_race(
        service: WorkflowService,
        **kwargs: Any,
    ) -> tuple[WorkflowExecution, WorkflowRunPlan | WorkflowBatchPlan]:
        execution, plan = await original_prepare(service, **kwargs)
        assert isinstance(plan, WorkflowRunPlan)
        node_id, prepared_request = next(iter(plan.prepared.requests.items()))
        raced_request = replace(
            prepared_request,
            request=replace(
                prepared_request.request,
                url="https://raced-target.example.test/health",
            ),
        )
        raced_prepared = replace(
            plan.prepared,
            requests={**plan.prepared.requests, node_id: raced_request},
        )
        return execution, replace(plan, prepared=raced_prepared)

    with monkeypatch.context() as race_patch:
        race_patch.setattr(
            WorkflowService,
            "prepare_preview_execution",
            prepare_with_reversible_target_race,
        )
        raced_target = await client.post(
            f"/api/v1/mcp/flow/proposals/{change_set_id}/preview-executions",
            headers={
                **s51_context["mcp_headers"],
                "Idempotency-Key": "s55-preview-raced-target",
            },
            json={
                "project_id": str(s51_context["project_id"]),
                "environment_id": str(s51_context["sandbox_environment_id"]),
                "approval_id": target_bound.json()["id"],
                "runtime_variables": {},
                "runtime_headers": {},
            },
        )
    assert raced_target.status_code == 409, raced_target.text
    assert raced_target.json()["error"]["code"] == "PREVIEW_APPROVAL_TARGET_CHANGED"

    async def prepare_then_reclassify(
        service: WorkflowService,
        **kwargs: Any,
    ) -> tuple[WorkflowExecution, WorkflowRunPlan | WorkflowBatchPlan]:
        execution, plan = await original_prepare(service, **kwargs)
        await service._session.execute(
            update(Environment)
            .where(Environment.id == s51_context["sandbox_environment_id"])
            .values(classification="production")
        )
        return execution, plan

    with monkeypatch.context() as classification_patch:
        classification_patch.setattr(
            WorkflowService,
            "prepare_preview_execution",
            prepare_then_reclassify,
        )
        reclassified = await client.post(
            f"/api/v1/mcp/flow/proposals/{change_set_id}/preview-executions",
            headers={
                **s51_context["mcp_headers"],
                "Idempotency-Key": "s55-preview-reclassified",
            },
            json={
                "project_id": str(s51_context["project_id"]),
                "environment_id": str(s51_context["sandbox_environment_id"]),
                "approval_id": target_bound.json()["id"],
                "runtime_variables": {},
                "runtime_headers": {},
            },
        )
    assert reclassified.status_code == 403, reclassified.text
    assert reclassified.json()["error"]["code"] == "PRODUCTION_PREVIEW_FORBIDDEN"
    async with s51_context["sessions"]() as session:
        environment = await session.get(Environment, s51_context["sandbox_environment_id"])
        assert environment is not None
        environment.classification = "sandbox"
        await session.commit()

    approved = await client.post(
        f"/api/v1/projects/{s51_context['project_id']}/flow-specs/change-sets/"
        f"{change_set_id}/preview-approvals",
        headers=s51_context["user_headers"],
        json={
            "environment_id": str(s51_context["sandbox_environment_id"]),
            "executor_service_account_id": str(s51_context["service_account_id"]),
            "runtime_variables": {"approved_target": "sandbox"},
            "budget": {
                "max_nodes": 100,
                "max_requests": 10,
                "max_dataset_rows": 20,
                "max_parallelism": 2,
                "max_runtime_seconds": 120,
            },
        },
    )
    assert approved.status_code == 201, approved.text
    approval_id = approved.json()["id"]
    execute_payload = {
        "project_id": str(s51_context["project_id"]),
        "environment_id": str(s51_context["sandbox_environment_id"]),
        "approval_id": approval_id,
        "runtime_variables": {"approved_target": "sandbox"},
        "runtime_headers": {},
    }
    execution_headers = {
        **s51_context["mcp_headers"],
        "Idempotency-Key": "s55-preview-execution",
    }
    executed = await client.post(
        f"/api/v1/mcp/flow/proposals/{change_set_id}/preview-executions",
        headers=execution_headers,
        json=execute_payload,
    )
    assert executed.status_code == 202, executed.text
    execution = executed.json()["execution"]
    assert execution["run_purpose"] == "preview"
    assert execution["workflow_id"] is None
    assert execution["workflow_version_id"] is None
    assert execution["source_change_set_id"] == change_set_id
    assert execution["preview_approval_id"] == approval_id
    assert execution["preview_budget"]["max_requests"] == 10
    assert execution["preview_evidence"]["proposal_fingerprint"]
    assert execution["preview_evidence"]["context_fingerprint"]

    repeated = await client.post(
        f"/api/v1/mcp/flow/proposals/{change_set_id}/preview-executions",
        headers=execution_headers,
        json=execute_payload,
    )
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["execution"]["id"] == execution["id"]

    replayed = await client.post(
        f"/api/v1/mcp/flow/proposals/{change_set_id}/preview-executions",
        headers={**s51_context["mcp_headers"], "Idempotency-Key": "s55-preview-replay"},
        json=execute_payload,
    )
    assert replayed.status_code == 409
    assert replayed.json()["error"]["code"] == "PREVIEW_APPROVAL_REPLAYED"

    async with s51_context["sessions"]() as session:
        approval = await session.get(SandboxPreviewApproval, UUID(approval_id))
        assert approval is not None and approval.consumed_at is not None
        assert str(approval.execution_id) == execution["id"]
        assert await session.scalar(select(func.count()).select_from(WorkflowExecution)) == 1
    assert len(s51_context["coordinator"].plans) == 1
    dispatched = s51_context["coordinator"].plans[0]
    assert dispatched.request_budget == 10
    assert dispatched.definition.settings.concurrency == 2
    assert dispatched.definition.run_policy.max_runtime_seconds == 120
    assert any(node.phase.value == "cleanup" for node in dispatched.definition.nodes)

    with respx.mock:
        request = respx.get("https://sandbox.example.test/health").mock(
            side_effect=[Response(200, json={"phase": "main"}), Response(200, json={})]
        )
        async with s51_context["sessions"]() as session:
            model = await session.get(WorkflowExecution, UUID(execution["id"]))
            assert model is not None
            completed, nodes = await WorkflowService(session).run_prepared(
                execution=model,
                plan=dispatched,
            )
    assert request.call_count == 2
    assert completed.status == "passed"
    assert completed.cleanup_status == "passed"
    assert len(nodes) >= 2
    assert completed.preview_evidence["execution_snapshot"]
    assert completed.preview_evidence["cleanup_result"]["activated_node_ids"] == ["cleanup-health"]
    assert completed.preview_evidence["cleanup_result"]["required_failures"] == []
    assert completed.preview_evidence["budget_usage"]["requests"] == {
        "limit": 10,
        "used": 2,
        "remaining": 8,
    }
    assert completed.preview_evidence["redactions"] == []

    report = await client.get(
        f"/api/v1/projects/{s51_context['project_id']}/reports/executions/{execution['id']}",
        headers=s51_context["user_headers"],
    )
    assert report.status_code == 200, report.text
    assert report.json()["summary"]["workflow_id"] is None
    assert report.json()["summary"]["workflow_name"] == "Sandbox Preview"

    replayed_node = await client.post(
        f"/api/v1/projects/{s51_context['project_id']}/workflow-executions/"
        f"{execution['id']}/nodes/health-check/replay",
        headers=s51_context["user_headers"],
    )
    assert replayed_node.status_code == 409, replayed_node.text
    assert replayed_node.json()["error"]["code"] == "PREVIEW_REPLAY_FORBIDDEN"

    async with s51_context["sessions"]() as session:
        failed_preview = await session.get(WorkflowExecution, UUID(execution["id"]))
        assert failed_preview is not None
        failed_preview.status = "failed"
        await session.commit()
    for command_type in ("resume", "retry"):
        recovered = await client.post(
            f"/api/v1/projects/{s51_context['project_id']}/workflow-executions/"
            f"{execution['id']}/{command_type}",
            headers={
                **s51_context["user_headers"],
                "Idempotency-Key": f"s55-preview-{command_type}",
            },
        )
        assert recovered.status_code == 409, recovered.text
        assert recovered.json()["error"]["code"] == "PREVIEW_RECOVERY_FORBIDDEN"


def _preview_test_definition(
    *,
    with_cleanup: bool,
    subflow: bool = False,
) -> WorkflowDefinition:
    work_node = {
        "id": "work",
        "type": "subflow" if subflow else "api",
        "name": "Work",
        "position": {"x": 180, "y": 0},
        "config": (
            {
                "workflow_id": "00000000-0000-0000-0000-000000000101",
                "workflow_version": 1,
            }
            if subflow
            else {"api_definition_id": "00000000-0000-0000-0000-000000000201"}
        ),
    }
    nodes = [
        {
            "id": "start",
            "type": "start",
            "name": "Start",
            "position": {"x": 0, "y": 0},
            "config": {},
        },
        work_node,
        {
            "id": "end",
            "type": "end",
            "name": "End",
            "position": {"x": 360, "y": 0},
            "config": {},
        },
    ]
    if with_cleanup:
        nodes.append(
            {
                "id": "cleanup",
                "type": "api",
                "name": "Cleanup",
                "position": {"x": 180, "y": 160},
                "config": {"api_definition_id": "00000000-0000-0000-0000-000000000202"},
                "phase": "cleanup",
                "cleanup_for": ["work"],
            }
        )
    return WorkflowDefinition.model_validate(
        {
            "schema_version": "2.0",
            "nodes": nodes,
            "edges": [
                {"id": "start-work", "source": "start", "target": "work"},
                {"id": "work-end", "source": "work", "target": "end"},
            ],
            "settings": {"concurrency": 9},
            "run_policy": {
                "request_budget": 200,
                "cleanup_request_budget": 200,
                "max_runtime_seconds": 900,
            },
        }
    )


def _preview_test_prepared_workflow(
    parent_definition: WorkflowDefinition,
    leaf_definition: WorkflowDefinition,
) -> PreparedWorkflow:
    leaf = PreparedSubflow(
        workflow_id=UUID("00000000-0000-0000-0000-000000000102"),
        workflow_version=1,
        fingerprint="a" * 64,
        definition=leaf_definition,
        requests={},
        subflows={},
        snapshot={"workflow": {"definition": leaf_definition.model_dump(mode="json")}},
    )
    parent = PreparedSubflow(
        workflow_id=UUID("00000000-0000-0000-0000-000000000101"),
        workflow_version=1,
        fingerprint="b" * 64,
        definition=parent_definition,
        requests={},
        subflows={"nested": leaf},
        snapshot={
            "workflow": {"definition": parent_definition.model_dump(mode="json")},
            "subflows": {"nested": leaf.snapshot},
        },
    )
    prepared = PreparedExecution(
        snapshot={"subflows": {"outer": parent.snapshot}},
        requests={},
        dataset_variables={},
        subflows={"outer": parent},
    )
    return PreparedWorkflow(snapshot=prepared.snapshot, runs=(prepared,))
