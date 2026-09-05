from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from test_s59_affected_flows_api import _draft

from app.domain.affected_flows import OperationSelector
from app.domain.change_regression import OperationIdentity
from app.domain.proposal_provenance import proposal_origin
from app.models.workflows import Workflow
from app.services.affected_flows import AffectedFlowService, _OperationChange, _Scan


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ("v6-flow-proposal-source-v1", "mcp"),
        ("v6-repair-proposal-source-v1", "repair"),
        ("v6-maintenance-proposal-source-v1", "maintenance"),
        ("unknown", "import"),
        (None, "import"),
    ],
)
def test_only_persisted_provenance_determines_origin(schema: str | None, expected: str) -> None:
    assert (
        proposal_origin({"proposal_schema_version": schema, "source_ref": "repair://spoof"})
        == expected
    )
    assert (
        proposal_origin({"source_ref": "mcp://spoof", "proposal_origin": "maintenance"}) == "import"
    )


def _workflow() -> Workflow:
    return Workflow(
        id=uuid4(),
        project_id=uuid4(),
        name="Budget test",
        draft_revision=1,
        draft_definition=_draft(uuid4(), None),
        created_by_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_node_budget_is_shared_across_workflows() -> None:
    scan = _Scan([], [], [], remaining_nodes=3)
    async with AsyncSession() as session:
        service = AffectedFlowService(session)
        first, second = _workflow(), _workflow()
        # No API lookup is necessary: budget is exhausted before entering the next graph.
        first.draft_definition = {
            "nodes": first.draft_definition["nodes"][::2],
            "edges": [{"id": "only", "source": "start", "target": "end"}],
        }
        await service._workflow_reasons(scan, first, first.project_id)
        assert scan.remaining_nodes == 1
        await service._workflow_reasons(scan, second, second.project_id)
    assert scan.exhausted
    assert scan.diagnostics[-1].code == "ANALYSIS_BUDGET_EXCEEDED"
    assert scan.diagnostics[-1].workflow_id == second.id


@pytest.mark.asyncio
async def test_unique_identity_budget_prevents_additional_database_queries() -> None:
    scan = _Scan([], [], [], identities={(uuid4(), None): None for _ in range(100)})
    workflow = _workflow()
    async with AsyncSession() as session:
        service = AffectedFlowService(session)
        await service._workflow_reasons(scan, workflow, workflow.project_id)
    assert scan.exhausted
    assert len(scan.identities) == 100
    assert scan.diagnostics[-1].code == "ANALYSIS_BUDGET_EXCEEDED"


@pytest.mark.asyncio
async def test_comparison_budget_is_reserved_before_matching() -> None:
    workflow = _workflow()
    from uuid import UUID

    api_id = UUID(workflow.draft_definition["nodes"][1]["config"]["api_definition_id"])
    identity = OperationIdentity(
        api_definition_id=str(api_id),
        api_version=1,
        portable_operation_ref="orders.read",
        service_key="orders",
        method="GET",
        normalized_path="/orders/{}",
        contract_fingerprint="a" * 64,
    )
    scan = _Scan(
        [],
        [
            _OperationChange(
                "impact://test", OperationSelector(method="GET", normalized_path="/orders/{}")
            )
        ],
        [],
        identities={(api_id, None): identity},
        remaining_comparisons=0,
    )
    async with AsyncSession() as session:
        service = AffectedFlowService(session)
        reasons = await service._workflow_reasons(scan, workflow, workflow.project_id)
    assert not reasons
    assert scan.exhausted
    assert scan.remaining_comparisons == 0
