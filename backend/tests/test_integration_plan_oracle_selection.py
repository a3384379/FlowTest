"""Generated response schemas apply only to their explicit scenario set."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from test_s50_integration_plans import s50_session as s50_session

from app.domain.test_engineering import ContractResponse, OperationContract, fingerprint_contract
from app.models.access import Project, User
from app.models.api_assets import APIDefinition, APIVersion
from app.services.integration_plans import IntegrationPlanAssetService, OperationPlanSelection


@pytest.mark.asyncio
async def test_success_selection_does_not_acquire_unselected_error_response_schema(
    s50_session: tuple[AsyncSession, User, Project],
) -> None:
    session, actor, project = s50_session
    success_schema = {
        "type": "object",
        "required": ["resource_id"],
        "properties": {"resource_id": {"type": "string"}},
    }
    error_schema = {
        "type": "object",
        "required": ["detail"],
        "properties": {"detail": {"type": "array", "items": {"type": "string"}}},
    }
    contract = OperationContract(
        operation="resources.read",
        method="GET",
        path="/resources",
        responses={
            "200": ContractResponse(description="成功", schema=success_schema),
            "422": ContractResponse(description="校验失败", schema=error_schema),
        },
    )
    definition = APIDefinition(
        project_id=project.id,
        name="resources.read",
        current_version=1,
        is_active=True,
        created_by_id=actor.id,
    )
    session.add(definition)
    await session.flush()
    session.add(
        APIVersion(
            api_definition_id=definition.id,
            service_id=None,
            version=1,
            method=contract.method,
            path=contract.path,
            query_parameters=[],
            headers={},
            variables={},
            body_kind="none",
            body=None,
            auth_kind="none",
            auth_config={},
            extraction_rules=[],
            assertions=[],
            canonical_contract=contract.model_dump(mode="json", by_alias=True),
            contract_fingerprint=fingerprint_contract(contract),
            contract_completeness="complete",
            created_by_id=actor.id,
        )
    )
    await session.commit()
    selected = await IntegrationPlanAssetService(session)._selected_operation(
        project_id=project.id,
        selection=OperationPlanSelection(definition_id=definition.id, api_version=1),
    )
    schemas = [oracle.expected for oracle in selected.oracles if oracle.kind == "schema"]
    assert success_schema in schemas
    assert error_schema not in schemas
    assert [oracle.expected for oracle in selected.oracles if oracle.kind == "status"] == [200]
