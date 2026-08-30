import json
from uuid import UUID

from app.domain.protocols import ProtocolKind
from app.engine.contracts import WorkflowDefinition
from app.engine.protocol_nodes import PreparedProtocolNode
from app.services.workflow_plan_codec import decode_execution_plan, encode_execution_plan
from app.services.workflow_runtime import PreparedSubflow
from app.services.workflow_snapshots import PreparedExecution
from app.services.workflows import WorkflowBatchPlan, WorkflowRunPlan

EXECUTION_ID = UUID("00000000-0000-0000-0000-000000000201")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000202")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000203")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000204")


def test_execution_plan_round_trip_preserves_nested_immutable_subflows() -> None:
    definition = _definition()
    prepared_subflow = PreparedSubflow(
        workflow_id=WORKFLOW_ID,
        workflow_version=3,
        fingerprint="f" * 64,
        definition=definition,
        requests={},
        subflows={},
        snapshot={"workflow": {"id": str(WORKFLOW_ID), "version": 3}},
    )
    plan = WorkflowRunPlan(
        execution_id=EXECUTION_ID,
        actor_id=ACTOR_ID,
        project_id=PROJECT_ID,
        workflow_version=1,
        definition=definition,
        prepared=PreparedExecution(
            snapshot={},
            requests={},
            dataset_variables={},
            subflows={"nested": prepared_subflow},
        ),
        runtime_variables={"region": "cn"},
    )

    restored = decode_execution_plan(encode_execution_plan(plan))

    assert isinstance(restored, WorkflowRunPlan)
    assert restored.prepared.subflows["nested"].workflow_version == 3
    assert restored.prepared.subflows["nested"].fingerprint == "f" * 64


def test_v1_execution_plan_without_subflows_remains_decodable() -> None:
    legacy = {
        "kind": "run",
        "execution_id": str(EXECUTION_ID),
        "actor_id": str(ACTOR_ID),
        "project_id": str(PROJECT_ID),
        "workflow_version": 1,
        "definition": _definition().model_dump(mode="json"),
        "prepared": {"snapshot": {}, "requests": {}, "dataset_variables": {}},
        "runtime_variables": {},
    }

    restored = decode_execution_plan(json.dumps(legacy))

    assert isinstance(restored, WorkflowRunPlan)
    assert restored.prepared.subflows == {}


def test_preview_batch_plan_round_trip_preserves_global_runtime_budget() -> None:
    child = WorkflowRunPlan(
        execution_id=EXECUTION_ID,
        actor_id=ACTOR_ID,
        project_id=PROJECT_ID,
        workflow_version=0,
        definition=_definition(),
        prepared=PreparedExecution(snapshot={}, requests={}, dataset_variables={}),
        runtime_variables={},
    )
    plan = WorkflowBatchPlan(
        execution_id=WORKFLOW_ID,
        actor_id=ACTOR_ID,
        project_id=PROJECT_ID,
        workflow_version=0,
        children=(child,),
        concurrency=1,
        max_runtime_seconds=600,
    )

    restored = decode_execution_plan(encode_execution_plan(plan))

    assert isinstance(restored, WorkflowBatchPlan)
    assert restored.max_runtime_seconds == 600


def test_execution_plan_round_trip_preserves_pinned_protocol_schema() -> None:
    schema_id = UUID("00000000-0000-0000-0000-000000000205")
    plan = WorkflowRunPlan(
        execution_id=EXECUTION_ID,
        actor_id=ACTOR_ID,
        project_id=PROJECT_ID,
        workflow_version=1,
        definition=_definition(),
        prepared=PreparedExecution(
            snapshot={},
            requests={},
            dataset_variables={},
            protocol_nodes={
                "graphql": PreparedProtocolNode(
                    protocol=ProtocolKind.GRAPHQL,
                    schema_id=schema_id,
                    schema_version=4,
                    schema_hash="a" * 64,
                    canonical_content=b"type Query { healthy: Boolean! }",
                )
            },
        ),
        runtime_variables={},
    )

    restored = decode_execution_plan(encode_execution_plan(plan))

    assert isinstance(restored, WorkflowRunPlan)
    protocol = restored.prepared.protocol_nodes["graphql"]
    assert protocol.schema_id == schema_id
    assert protocol.schema_version == 4
    assert protocol.canonical_content == b"type Query { healthy: Boolean! }"


def _definition() -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "schema_version": "2.0",
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "name": "开始",
                    "position": {"x": 0, "y": 0},
                    "config": {},
                },
                {
                    "id": "end",
                    "type": "end",
                    "name": "结束",
                    "position": {"x": 200, "y": 0},
                    "config": {},
                },
            ],
            "edges": [{"id": "start-end", "source": "start", "target": "end"}],
        }
    )
