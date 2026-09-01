from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.errors import AppError
from app.core.security import password_service
from app.domain.flow_spec_v2 import FlowSpecV2
from app.domain.integration_plans import (
    CompilerEvidenceTrace,
    IntegrationPlan,
    IntegrationPlannerRequest,
    PlanActor,
    PlanBindingCandidate,
    PlanBranch,
    PlanCleanupRequirement,
    PlanDatabasePredicate,
    PlanDatabaseRead,
    PlanDataRecipe,
    PlanOracle,
    PlanOracleValueSource,
    PlanPrecondition,
    PlanRequestTemplate,
    PlanRequestValue,
    PlanStep,
    PlanTargetEnvironment,
    ReusableAuthSubflowEvidence,
    SelectedOperationEvidence,
    build_integration_plan,
    compile_integration_plan,
    integration_plan_fingerprint,
    normalize_integration_plan,
    seal_integration_plan,
    validate_integration_plan,
)
from app.domain.test_design import OracleSpec, ScenarioCandidate, ScenarioRequest
from app.domain.test_engineering import (
    ContractAuth,
    ContractParameter,
    ContractRequestBody,
    ContractResponse,
    OperationContract,
    fingerprint_contract,
)
from app.engine.contracts import MappingTargetLocation, WorkflowDefinition
from app.models import Base
from app.models.access import Project, User
from app.models.api_assets import APIDefinition, APIVersion
from app.models.artifacts import Artifact
from app.models.data_sources import Credential
from app.models.organizations import Organization
from app.models.service_targets import Service
from app.models.workflows import Workflow, WorkflowVersion
from app.schemas.flow_spec import FlowSpecImportRequest
from app.services.api_assets import APIAssetService
from app.services.change_regression import ChangeRegressionService
from app.services.flow_spec import FlowSpecImportProvenance, FlowSpecService
from app.services.integration_plans import (
    ExistingAuthWorkflowSelection,
    IntegrationPlanAssetCommand,
    IntegrationPlanAssetService,
    OperationPlanSelection,
)
from app.services.test_engineering import TestEngineeringService


@pytest.fixture
async def s50_session() -> AsyncIterator[tuple[AsyncSession, User, Project]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        actor = User(
            email="s50-admin@example.test",
            display_name="S50 administrator",
            password_hash=password_service.hash("unused-test-password"),
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        organization = Organization(
            name="S50 organization",
            slug="s50-organization",
            description="",
            enabled=True,
            created_by_id=None,
        )
        session.add_all([actor, organization])
        await session.flush()
        organization.created_by_id = actor.id
        project = Project(
            organization_id=organization.id,
            name="S50 project",
            created_by_id=actor.id,
        )
        session.add(project)
        await session.flush()
        yield session, actor, project
    await engine.dispose()


@pytest.mark.asyncio
async def test_historical_api_contract_keeps_its_original_service_identity(
    s50_session: tuple[AsyncSession, User, Project],
) -> None:
    session, actor, project = s50_session
    old_service = Service(
        project_id=project.id,
        service_key="legacy-orders",
        name="Legacy orders",
        description="",
        owner_team=None,
        service_type="http",
        enabled=True,
        created_by_id=actor.id,
    )
    current_service = Service(
        project_id=project.id,
        service_key="orders",
        name="Orders",
        description="",
        owner_team=None,
        service_type="http",
        enabled=True,
        created_by_id=actor.id,
    )
    session.add_all([old_service, current_service])
    await session.flush()
    legacy_contract = OperationContract(
        operation="orders.get",
        method="GET",
        path="/orders/{id}",
        service=None,
        responses={"200": ContractResponse(description="OK")},
        source_ref="contract://legacy-orders/orders.get",
        revision="1",
    )
    legacy_fingerprint = fingerprint_contract(legacy_contract)
    definition = APIDefinition(
        project_id=project.id,
        folder_id=None,
        service_id=old_service.id,
        name="orders.get",
        description="",
        current_version=1,
        is_active=True,
        import_key="orders.get",
        import_fingerprint=legacy_fingerprint,
        import_source="s50-history-test",
        import_source_key="orders.get",
        created_by_id=actor.id,
    )
    session.add(definition)
    await session.flush()
    legacy_version = APIVersion(
        api_definition_id=definition.id,
        service_id=old_service.id,
        version=1,
        method=legacy_contract.method,
        path=legacy_contract.path,
        query_parameters=[],
        headers={},
        variables={},
        body_kind="none",
        body=None,
        auth_kind="none",
        auth_config={},
        extraction_rules=[],
        assertions=[],
        canonical_contract=legacy_contract.model_dump(mode="json", by_alias=True),
        contract_fingerprint=legacy_fingerprint,
        contract_completeness="complete",
        created_by_id=actor.id,
    )
    session.add(legacy_version)
    await session.commit()

    migrated_plan = await IntegrationPlanAssetService(session).build(
        actor=actor,
        project_id=project.id,
        command=IntegrationPlanAssetCommand(
            context_revision_id=UUID("00000000-0000-0000-0000-000000000050"),
            context_fingerprint="5" * 64,
            objective="Plan an API whose immutable contract predates service identity",
            actors=(
                PlanActor(
                    id="operator",
                    role="integration tester",
                    evidence_refs=["context://s50/migrated-service-actor"],
                ),
            ),
            preconditions=(),
            target_environment=PlanTargetEnvironment(
                key="test",
                source_ref="environment://test",
                evidence_refs=["environment://test/revision/1"],
            ),
            operations=(OperationPlanSelection(definition_id=definition.id),),
        ),
    )
    assert migrated_plan.operations[0].service_ref == old_service.service_key
    assert migrated_plan.operations[0].contract_fingerprint == legacy_fingerprint

    await APIAssetService(session).update_definition(
        actor=actor,
        project_id=project.id,
        definition_id=definition.id,
        name=None,
        description=None,
        folder_id=None,
        change_folder=False,
        service_id=current_service.id,
        change_service=True,
    )

    resolved_contract = await TestEngineeringService(session).contract_for_api(
        project_id=project.id,
        definition_id=definition.id,
        version_number=1,
    )
    assert resolved_contract.service is None
    assert fingerprint_contract(resolved_contract) == legacy_fingerprint
    assert legacy_version.contract_fingerprint == legacy_fingerprint
    assert legacy_version.canonical_contract["service"] is None

    resolved_identity = await ChangeRegressionService(session)._operation_identity(
        project_id=project.id,
        definition_id=definition.id,
        version_number=1,
    )
    assert resolved_identity is not None
    identity, regression_contract = resolved_identity
    assert regression_contract.service is None
    assert identity.service_key == old_service.service_key
    assert identity.contract_fingerprint == legacy_fingerprint

    current_contract = await TestEngineeringService(session).contract_for_api(
        project_id=project.id,
        definition_id=definition.id,
        version_number=2,
    )
    assert current_contract.service == current_service.service_key

    portable = await FlowSpecService(session)._portable_spec(
        definition=WorkflowDefinition.model_validate(_auth_workflow_definition(definition.id)),
        project_id=project.id,
        name="Pinned legacy service",
        description="",
        evidence=[],
    )
    portable_payload = portable.model_dump(mode="json")
    assert portable_payload["services"][0]["ref"] == old_service.service_key
    assert portable_payload["operations"][0]["service_ref"] == old_service.service_key
    request_node = next(node for node in portable_payload["nodes"] if node["id"] == "login")
    assert request_node["target"]["service_ref"] == old_service.service_key

    operation_ref = portable_payload["operations"][0]["ref"]
    mappings = await FlowSpecService(session)._resolve_mappings(
        project_id=project.id,
        spec=portable,
        service_mappings={old_service.service_key: old_service.id},
        operation_mappings={operation_ref: definition.id},
        operation_version_mappings={operation_ref: 1},
    )
    assert mappings.operation_versions[operation_ref] == 1


def test_golden_plan_compiles_to_executable_traceable_flowspec() -> None:
    plan = _golden_plan()
    result = compile_integration_plan(plan)

    assert validate_integration_plan(plan).valid is True
    assert result.importable is True
    assert result.validation is not None and result.validation.valid is True
    assert result.compatibility is not None and result.compatibility.compatible is True
    assert result.flow_spec is not None
    assert result.flow_spec_fingerprint is not None
    assert compile_integration_plan(plan).flow_spec_fingerprint == result.flow_spec_fingerprint
    assert [item.status for item in result.passes] == ["completed"] * 10
    assert result.flow_spec.bindings == []
    assert result.flow_spec.assertions == []
    assert result.flow_spec.cleanup == []
    assert all(parameter.source.value != "secret_ref" for parameter in result.flow_spec.parameters)

    extract = next(node for node in result.flow_spec.nodes if node.kind == "extract")
    assert extract.config["source_node_id"] == "orders-create"
    assert extract.config["expression"] == "body.id"
    query_edge = next(
        edge
        for edge in result.flow_spec.edges
        if edge.source == extract.id and edge.target == "orders-query"
    )
    assert query_edge.mappings[0].target.location is MappingTargetLocation.QUERY
    assert query_edge.mappings[0].target.key == "id"
    auth_edge = next(
        edge
        for edge in result.flow_spec.edges
        if edge.source == "auth-login" and edge.target == "orders-create"
    )
    assert auth_edge.mappings[0].transform.template == "Bearer {{value}}"
    assert any(node.kind == "assert" for node in result.flow_spec.nodes)
    assert _trace(result.node_evidence, extract.id)
    assert _trace(result.edge_evidence, query_edge.id)
    query_asserts = [
        node
        for node in result.flow_spec.nodes
        if node.kind == "assert" and node.config["source_node_id"] == "orders-query"
    ]
    assert len(query_asserts) == 3
    assert not any(
        edge.source == "orders-query" and edge.target == "end" for edge in result.flow_spec.edges
    )
    assert any(
        edge.source in {node.id for node in query_asserts} and edge.target == "end"
        for edge in result.flow_spec.edges
    )
    create_assert = next(
        node
        for node in result.flow_spec.nodes
        if node.kind == "assert" and node.config["source_node_id"] == "orders-create"
    )
    assert not any(
        edge.source == "orders-create" and edge.target in {extract.id, "orders-query"}
        for edge in result.flow_spec.edges
    )
    assert {edge.target for edge in result.flow_spec.edges if edge.source == create_assert.id} >= {
        extract.id,
        "orders-query",
    }


def test_plan_contract_is_strict_and_fingerprint_is_canonical() -> None:
    plan = _golden_plan()
    payload = plan.model_dump(mode="json")
    with pytest.raises(ValidationError):
        IntegrationPlan.model_validate({**payload, "unsupported_runtime_switch": True})

    reordered = plan.model_copy(
        update={
            "operations": list(reversed(plan.operations)),
            "oracles": list(reversed(plan.oracles)),
            "plan_fingerprint": "0" * 64,
        }
    )
    resealed = seal_integration_plan(reordered)
    assert integration_plan_fingerprint(resealed) == plan.plan_fingerprint
    assert normalize_integration_plan(resealed).plan_fingerprint == plan.plan_fingerprint


def test_selected_operation_evidence_accepts_full_service_key_contract() -> None:
    service_ref = "orders-" + ("a" * 153)
    operation = _selected_operation(
        ref="orders.create",
        contract=_response_contract("orders.create", "/orders", "service-key"),
        status=200,
    )

    validated = SelectedOperationEvidence.model_validate(
        {**operation.model_dump(mode="json"), "service_ref": service_ref}
    )

    assert validated.service_ref == service_ref


def test_multiple_binding_candidates_are_retained_without_guessing() -> None:
    first = _selected_operation(
        ref="orders.first",
        contract=_response_contract("orders.first", "/first", "a"),
        status=200,
    )
    second = _selected_operation(
        ref="orders.second",
        contract=_response_contract("orders.second", "/second", "b"),
        status=200,
    )
    target = _selected_operation(
        ref="orders.query",
        contract=OperationContract(
            operation="orders.query",
            method="GET",
            path="/query",
            service="orders",
            parameters=[
                ContractParameter(
                    name="id",
                    location="query",
                    required=True,
                    schema={"type": "string"},
                    source_ref="contract://orders/query/id",
                )
            ],
            responses={"200": ContractResponse(description="OK")},
            source_ref="contract://orders/query",
        ),
        status=200,
    )
    plan = build_integration_plan(_planner_request([first, second, target]))

    binding = next(item for item in plan.bindings if item.target.step_id == "orders-query")
    assert len(binding.candidates) == 2
    assert binding.selected_candidate_id is None
    assert binding.requires_review is True
    assert {item.code for item in plan.unresolved_items} == {"MULTIPLE_BINDING_CANDIDATES"}
    compilation = compile_integration_plan(plan)
    assert compilation.importable is False
    assert compilation.flow_spec is None
    assert {item.code for item in compilation.diagnostics} >= {
        "MULTIPLE_BINDING_CANDIDATES",
        "BINDING_SELECTION_REQUIRED",
    }


def test_missing_evidence_and_unsupported_runtime_targets_block_compilation() -> None:
    target = _selected_operation(
        ref="orders.query",
        contract=OperationContract(
            operation="orders.query",
            method="GET",
            path="/orders/{id}",
            service="orders",
            parameters=[
                ContractParameter(
                    name="id",
                    location="path",
                    required=True,
                    schema={"type": "string"},
                    source_ref="contract://orders/query/id",
                )
            ],
            responses={"200": ContractResponse(description="OK")},
            source_ref="contract://orders/query",
        ),
        status=200,
    )
    missing = build_integration_plan(_planner_request([target]))
    assert validate_integration_plan(missing).valid is False
    assert compile_integration_plan(missing).flow_spec is None
    assert {item.code for item in missing.unresolved_items} == {"BINDING_EVIDENCE_MISSING"}

    executable = _golden_plan()
    query_binding = next(
        item for item in executable.bindings if item.target.step_id == "orders-query"
    )
    path_binding = query_binding.model_copy(
        update={"target": query_binding.target.model_copy(update={"location": "path"})}
    )
    changed = seal_integration_plan(
        executable.model_copy(
            update={
                "bindings": [
                    path_binding if item.id == query_binding.id else item
                    for item in executable.bindings
                ],
                "plan_fingerprint": "0" * 64,
            }
        )
    )
    compilation = compile_integration_plan(changed)
    assert compilation.importable is False
    assert {item.code for item in compilation.diagnostics} >= {"BINDING_TARGET_RUNTIME_UNSUPPORTED"}


@pytest.mark.parametrize(
    "request_template",
    [
        PlanRequestTemplate(),
        PlanRequestTemplate(body_kind="json", body=[]),
        PlanRequestTemplate(body_kind="raw", body="{}"),
    ],
)
def test_body_mapping_requires_an_object_json_request_body(
    request_template: PlanRequestTemplate,
) -> None:
    plan = _golden_plan()
    query_binding = next(item for item in plan.bindings if item.target.step_id == "orders-query")
    body_binding = query_binding.model_copy(
        update={"target": query_binding.target.model_copy(update={"location": "body"})}
    )
    changed = seal_integration_plan(
        plan.model_copy(
            update={
                "operations": [
                    operation.model_copy(update={"request": request_template})
                    if operation.ref == "orders.query"
                    else operation
                    for operation in plan.operations
                ],
                "bindings": [
                    body_binding if item.id == query_binding.id else item for item in plan.bindings
                ],
                "plan_fingerprint": "0" * 64,
            }
        )
    )

    compilation = compile_integration_plan(changed)

    assert compilation.importable is False
    assert {item.code for item in compilation.diagnostics} >= {"BODY_MAPPING_REQUIRES_JSON_OBJECT"}


def test_body_mapping_accepts_an_object_json_request_body() -> None:
    plan = _golden_plan()
    query_binding = next(item for item in plan.bindings if item.target.step_id == "orders-query")
    body_binding = query_binding.model_copy(
        update={"target": query_binding.target.model_copy(update={"location": "body"})}
    )
    changed = seal_integration_plan(
        plan.model_copy(
            update={
                "operations": [
                    operation.model_copy(
                        update={"request": PlanRequestTemplate(body_kind="json", body={})}
                    )
                    if operation.ref == "orders.query"
                    else operation
                    for operation in plan.operations
                ],
                "bindings": [
                    body_binding if item.id == query_binding.id else item for item in plan.bindings
                ],
                "plan_fingerprint": "0" * 64,
            }
        )
    )

    compilation = compile_integration_plan(changed)

    assert compilation.importable is True
    assert compilation.flow_spec is not None


def test_body_mapping_rejects_nested_path_below_an_existing_scalar() -> None:
    plan = _golden_plan()
    query_binding = next(item for item in plan.bindings if item.target.step_id == "orders-query")
    body_binding = query_binding.model_copy(
        update={
            "target": query_binding.target.model_copy(update={"location": "body", "key": "user.id"})
        }
    )
    changed = seal_integration_plan(
        plan.model_copy(
            update={
                "operations": [
                    operation.model_copy(
                        update={
                            "request": PlanRequestTemplate(body_kind="json", body={"user": "fixed"})
                        }
                    )
                    if operation.ref == "orders.query"
                    else operation
                    for operation in plan.operations
                ],
                "bindings": [
                    body_binding if item.id == query_binding.id else item for item in plan.bindings
                ],
                "plan_fingerprint": "0" * 64,
            }
        )
    )

    compilation = compile_integration_plan(changed)

    assert compilation.importable is False
    assert {item.code for item in compilation.diagnostics} >= {"BODY_MAPPING_TARGET_PATH_CONFLICT"}


def test_body_mapping_rejects_parent_and_child_targets_on_the_same_operation() -> None:
    plan = _golden_plan()
    query_binding = next(item for item in plan.bindings if item.target.step_id == "orders-query")
    parent = query_binding.model_copy(
        update={
            "id": "orders-query-user",
            "target": query_binding.target.model_copy(update={"location": "body", "key": "user"}),
        }
    )
    child = query_binding.model_copy(
        update={
            "id": "orders-query-user-id",
            "target": query_binding.target.model_copy(
                update={"location": "body", "key": "user.id"}
            ),
        }
    )
    changed = seal_integration_plan(
        plan.model_copy(
            update={
                "operations": [
                    operation.model_copy(
                        update={"request": PlanRequestTemplate(body_kind="json", body={})}
                    )
                    if operation.ref == "orders.query"
                    else operation
                    for operation in plan.operations
                ],
                "bindings": [
                    parent,
                    child,
                    *[item for item in plan.bindings if item.id != query_binding.id],
                ],
                "plan_fingerprint": "0" * 64,
            }
        )
    )

    compilation = compile_integration_plan(changed)

    assert compilation.importable is False
    assert {item.code for item in compilation.diagnostics} >= {"BODY_MAPPING_TARGET_PATH_CONFLICT"}


def test_selected_scenario_path_and_cookie_inputs_fail_closed_without_disappearing() -> None:
    target = _selected_operation(
        ref="orders.localized",
        contract=OperationContract(
            operation="orders.localized",
            method="GET",
            path="/tenants/{tenantId}/orders",
            service="orders",
            parameters=[
                ContractParameter(
                    name="tenantId",
                    location="path",
                    required=True,
                    schema={"type": "string"},
                    source_ref="contract://orders/localized/tenant-id",
                ),
                ContractParameter(
                    name="locale",
                    location="cookie",
                    required=True,
                    schema={"type": "string"},
                    source_ref="contract://orders/localized/locale",
                ),
            ],
            responses={"200": ContractResponse(description="OK")},
            source_ref="contract://orders/localized",
        ),
        status=200,
        scenario=ScenarioCandidate(
            id="orders.localized.happy",
            kind="happy_path",
            title="Query localized orders",
            request=ScenarioRequest(
                path_parameters={"tenantId": "tenant-57"},
                cookies={"locale": "zh-CN"},
            ),
            expected_category="success",
            evidence_refs=["scenario://orders/localized/happy"],
        ),
    )

    plan = build_integration_plan(_planner_request([target]))

    unsupported = [
        item
        for item in plan.unresolved_items
        if item.code == "SCENARIO_REQUEST_INPUT_RUNTIME_UNSUPPORTED"
    ]
    assert len(unsupported) == 2
    assert {item.candidate_refs[0] for item in unsupported} == {
        "cookie:locale",
        "path:tenantId",
    }
    assert "BINDING_EVIDENCE_MISSING" not in {item.code for item in plan.unresolved_items}
    assert validate_integration_plan(plan).valid is False
    assert compile_integration_plan(plan).flow_spec is None


def test_untrusted_expressions_headers_and_secret_refs_fail_closed() -> None:
    with pytest.raises(ValidationError):
        PlanRequestTemplate(
            headers=[PlanRequestValue(name="X-Test", value="safe\r\nInjected: value")]
        )

    plan = _golden_plan()
    query_binding = next(item for item in plan.bindings if item.target.step_id == "orders-query")
    invalid_candidate = query_binding.candidates[0].model_copy(update={"path": "["})
    invalid_binding = query_binding.model_copy(update={"candidates": [invalid_candidate]})
    invalid_expression = seal_integration_plan(
        plan.model_copy(
            update={
                "bindings": [
                    invalid_binding if item.id == query_binding.id else item
                    for item in plan.bindings
                ],
                "plan_fingerprint": "0" * 64,
            }
        )
    )
    expression_result = compile_integration_plan(invalid_expression)
    assert expression_result.flow_spec is None
    assert {item.code for item in expression_result.diagnostics} >= {"INVALID_PLAN_EXPRESSION"}

    schema_oracle = next(item for item in plan.oracles if item.kind == "schema")
    external_schema = schema_oracle.model_copy(
        update={"expected": {"$ref": "http://metadata.internal/schema.json"}}
    )
    external_schema_plan = seal_integration_plan(
        plan.model_copy(
            update={
                "oracles": [
                    external_schema if item.id == schema_oracle.id else item
                    for item in plan.oracles
                ],
                "plan_fingerprint": "0" * 64,
            }
        )
    )
    external_schema_result = compile_integration_plan(external_schema_plan)
    assert external_schema_result.flow_spec is None
    assert {item.code for item in external_schema_result.diagnostics} >= {
        "EXTERNAL_SCHEMA_REF_FORBIDDEN"
    }

    login = plan.operations[0]
    secret_request = login.request.model_copy(
        update={
            "headers": [PlanRequestValue(name="X-Access-Token", value="secret://s50/access-token")]
        }
    )
    secret_plan = seal_integration_plan(
        plan.model_copy(
            update={
                "operations": [
                    login.model_copy(update={"request": secret_request}),
                    *plan.operations[1:],
                ],
                "plan_fingerprint": "0" * 64,
            }
        )
    )
    assert validate_integration_plan(secret_plan).valid is True
    secret_result = compile_integration_plan(secret_plan)
    assert secret_result.flow_spec is None
    assert {item.code for item in secret_result.diagnostics} >= {
        "SECRET_REFERENCE_RUNTIME_UNSUPPORTED"
    }

    nested_secret_request = login.request.model_copy(
        update={"body": {"users": [{"password": "plaintext"}]}}
    )
    nested_secret_plan = seal_integration_plan(
        plan.model_copy(
            update={
                "operations": [
                    login.model_copy(update={"request": nested_secret_request}),
                    *plan.operations[1:],
                ],
                "plan_fingerprint": "0" * 64,
            }
        )
    )
    nested_secret_result = compile_integration_plan(nested_secret_plan)
    assert nested_secret_result.flow_spec is None
    assert {item.code for item in nested_secret_result.diagnostics} >= {"SECRET_LITERAL_FORBIDDEN"}


def test_runtime_data_recipe_compiles_without_unsupported_metadata() -> None:
    plan = _golden_plan()
    query_binding = next(item for item in plan.bindings if item.target.step_id == "orders-query")
    runtime_candidate = PlanBindingCandidate(
        id="runtime-tenant-id",
        source_kind="runtime_variable",
        variable_name="tenant.id",
        path='variables."tenant.id"',
        value_type="string",
        confidence=1,
        evidence_refs=["context://runtime/tenant-id"],
    )
    runtime_binding = query_binding.model_copy(
        update={
            "candidates": [runtime_candidate],
            "selected_candidate_id": runtime_candidate.id,
            "capture_variable": None,
            "evidence_refs": runtime_candidate.evidence_refs,
        }
    )
    changed = seal_integration_plan(
        plan.model_copy(
            update={
                "bindings": [
                    runtime_binding if item.id == query_binding.id else item
                    for item in plan.bindings
                ],
                "data_recipes": [
                    PlanDataRecipe(
                        id="runtime-tenant-id",
                        kind="runtime",
                        name="tenant.id",
                        evidence_refs=["context://runtime/tenant-id"],
                    )
                ],
                "plan_fingerprint": "0" * 64,
            }
        )
    )
    result = compile_integration_plan(changed)

    assert result.importable is True
    assert result.flow_spec is not None
    assert result.flow_spec.parameters[0].description == ""
    runtime_edge = next(
        edge
        for edge in result.flow_spec.edges
        if edge.source == "start" and edge.target == "orders-query" and edge.mappings
    )
    assert runtime_edge.mappings[0].source.path == 'variables."tenant.id"'


def test_dataset_and_cleanup_contract_compile_without_top_level_downgrade() -> None:
    plan = _golden_plan()
    dataset_id = UUID("00000000-0000-0000-0000-000000000053")
    changed = seal_integration_plan(
        plan.model_copy(
            update={
                "steps": [
                    PlanStep(
                        id="fixture-data",
                        kind="dataset",
                        name="Fixture Data",
                        data_recipe_ref="fixture-data",
                        evidence_refs=["dataset://fixture-data/revision/1"],
                    ),
                    *plan.steps,
                ],
                "data_recipes": [
                    PlanDataRecipe(
                        id="fixture-data",
                        kind="dataset",
                        name="fixture_data",
                        artifact_id=dataset_id,
                        evidence_refs=["dataset://fixture-data/revision/1"],
                    )
                ],
                "cleanup_requirements": [
                    PlanCleanupRequirement(
                        id="cleanup-order",
                        operation_ref="orders.create",
                        cleanup_for_step_ids=["orders-create"],
                        evidence_refs=["contract://orders/cleanup"],
                    )
                ],
                "plan_fingerprint": "0" * 64,
            }
        )
    )
    result = compile_integration_plan(changed)

    assert result.importable is True
    assert isinstance(result.flow_spec, FlowSpecV2)
    dataset = next(node for node in result.flow_spec.nodes if node.kind == "dataset")
    assert dataset.config["artifact_id"] == str(dataset_id)
    assert result.flow_spec.cleanup[0].id == "cleanup-order"
    assert result.flow_spec.cleanup[0].cleanup_for == ["orders-create"]
    assert result.flow_spec.run_policy.cleanup_request_budget == 1
    assert result.compiler_version == "flowtest-integration-plan-compiler-s54-v1"
    assert "CLEANUP_RUNTIME_DEFERRED" not in {item.code for item in result.diagnostics}


def test_duplicate_response_evidence_is_deduplicated_and_unknown_types_block() -> None:
    source = _selected_operation(
        ref="evidence.source",
        contract=OperationContract(
            operation="evidence.source",
            method="POST",
            path="/source",
            service="orders",
            responses={
                status: ContractResponse(
                    description="OK",
                    schema={"type": "object", "properties": {"id": {"type": "string"}}},
                )
                for status in ("200", "201")
            },
            source_ref="contract://evidence/source",
        ),
        status=200,
    )
    target = _selected_operation(
        ref="evidence.target",
        contract=OperationContract(
            operation="evidence.target",
            method="GET",
            path="/target",
            service="orders",
            parameters=[
                ContractParameter(
                    name="id",
                    location="query",
                    required=True,
                    schema={"type": "string"},
                    source_ref="contract://evidence/target/id",
                )
            ],
            responses={"200": ContractResponse(description="OK")},
            source_ref="contract://evidence/target",
        ),
        status=200,
    )
    plan = build_integration_plan(_planner_request([source, target]))

    assert len(plan.bindings[0].candidates) == 1
    assert compile_integration_plan(plan).importable is True

    unknown_source = source.model_copy(
        update={
            "contract": source.contract.model_copy(
                update={
                    "responses": {
                        "200": ContractResponse(
                            description="OK",
                            schema={"type": "object", "properties": {"id": {}}},
                        )
                    }
                }
            )
        }
    )
    unknown_target = target.model_copy(
        update={
            "contract": target.contract.model_copy(
                update={
                    "parameters": [target.contract.parameters[0].model_copy(update={"schema_": {}})]
                }
            )
        }
    )
    unknown_plan = build_integration_plan(_planner_request([unknown_source, unknown_target]))
    assert {item.code for item in unknown_plan.unresolved_items} == {"BINDING_TYPE_CONFLICT"}
    assert compile_integration_plan(unknown_plan).flow_spec is None


def test_single_branch_compiles_to_condition_edges() -> None:
    selected = [
        _selected_operation(
            ref=f"branch.{name}",
            contract=OperationContract(
                operation=f"branch.{name}",
                method="GET",
                path=f"/{name}",
                service="orders",
                responses={"200": ContractResponse(description="OK")},
                source_ref=f"contract://branch/{name}",
            ),
            status=200,
        )
        for name in ("source", "true", "false", "join")
    ]
    base = build_integration_plan(_planner_request(selected))
    plan = seal_integration_plan(
        base.model_copy(
            update={
                "branches": [
                    PlanBranch(
                        id="status-branch",
                        source_step_id="branch-source",
                        expression="body.enabled",
                        expected=True,
                        true_step_id="branch-true",
                        false_step_id="branch-false",
                        join_step_id="branch-join",
                        evidence_refs=["contract://branch/enabled"],
                    )
                ],
                "plan_fingerprint": "0" * 64,
            }
        )
    )
    compilation = compile_integration_plan(plan)

    assert compilation.importable is True
    assert compilation.flow_spec is not None
    condition = next(node for node in compilation.flow_spec.nodes if node.kind == "condition")
    outgoing = [edge for edge in compilation.flow_spec.edges if edge.source == condition.id]
    assert {edge.condition for edge in outgoing} == {"true", "false"}
    assert _trace(compilation.node_evidence, condition.id) == ["contract://branch/enabled"]


def test_existing_auth_evidence_is_reused_as_subflow_without_secret_read() -> None:
    protected = _selected_operation(
        ref="orders.protected",
        contract=OperationContract(
            operation="orders.protected",
            method="GET",
            path="/protected",
            service="orders",
            auth=ContractAuth(
                required=True,
                kind="bearer",
                location="header",
                name="Authorization",
                source_ref="workflow://auth/contract",
            ),
            responses={"200": ContractResponse(description="OK")},
            source_ref="contract://orders/protected",
        ),
        status=200,
    )
    request = _planner_request([protected]).model_copy(
        update={
            "reusable_auth_subflow": ReusableAuthSubflowEvidence(
                step_id="existing-auth",
                name="Existing Auth",
                workflow_id=UUID("00000000-0000-0000-0000-000000000099"),
                workflow_version=3,
                token_path="nodes[?node_id=='login']|[0].output.body.token",
                evidence_refs=["workflow://auth/version/3"],
                confidence=1,
            )
        }
    )
    plan = build_integration_plan(request)
    compilation = compile_integration_plan(plan)

    assert compilation.importable is True
    assert compilation.flow_spec is not None
    subflow = next(node for node in compilation.flow_spec.nodes if node.kind == "subflow")
    assert subflow.config == {
        "workflow_id": "00000000-0000-0000-0000-000000000099",
        "workflow_version": 3,
    }
    binding = plan.bindings[0]
    assert binding.candidates[0].source_step_id == "existing-auth"
    assert binding.candidates[0].secret_ref is None


def test_existing_operation_credential_reference_uses_inherited_auth() -> None:
    protected = _selected_operation(
        ref="orders.credential-protected",
        contract=OperationContract(
            operation="orders.credential-protected",
            method="GET",
            path="/credential-protected",
            service="orders",
            auth=ContractAuth(
                required=True,
                kind="bearer",
                location="header",
                name="Authorization",
                source_ref="contract://orders/credential-protected/auth",
            ),
            responses={"200": ContractResponse(description="OK")},
            source_ref="contract://orders/credential-protected",
        ),
        status=200,
    ).model_copy(update={"credential_refs": ["secret://orders-api-token"]})

    plan = build_integration_plan(_planner_request([protected]))
    result = compile_integration_plan(plan)

    assert plan.operations[0].credential_refs == ["secret://orders-api-token"]
    assert plan.operations[0].request.auth_mode == "inherit"
    assert plan.bindings == []
    assert result.importable is True
    assert result.flow_spec is not None
    operation_node = next(node for node in result.flow_spec.nodes if node.kind == "http")
    assert operation_node.config["request_overrides"] == {"auth_mode": "inherit"}
    assert all(parameter.source.value != "secret_ref" for parameter in result.flow_spec.parameters)


def test_s53_builder_emits_v2_plan_with_database_step_and_cross_api_oracle() -> None:
    create = _selected_operation(
        ref="orders.create",
        contract=OperationContract(
            operation="orders.create",
            method="POST",
            path="/orders",
            service="orders",
            responses={
                "201": ContractResponse(
                    description="Created",
                    schema={
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                    },
                )
            },
            source_ref="contract://orders/create",
        ),
        status=201,
    )
    query = _selected_operation(
        ref="orders.query",
        contract=OperationContract(
            operation="orders.query",
            method="GET",
            path="/orders",
            service="orders",
            parameters=[
                ContractParameter(
                    name="id",
                    location="query",
                    required=True,
                    schema={"type": "string"},
                    source_ref="contract://orders/query/id",
                )
            ],
            responses={
                "200": ContractResponse(
                    description="OK",
                    schema={
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                    },
                )
            },
            source_ref="contract://orders/query",
        ),
        status=200,
    )
    database_read = PlanDatabaseRead(
        id="orders-db-read",
        name="Read created order",
        credential_id=UUID("00000000-0000-0000-0000-000000000053"),
        dialect="postgresql",
        table="public.orders",
        columns=["id"],
        predicates=[
            PlanDatabasePredicate(
                column="id",
                parameter="order_id",
                variable_name="orders-create-id",
            )
        ],
        source_ref="database://orders/schema/revision/53",
        applies_to=["orders-create", "orders-query"],
        evidence_refs=["database://orders/schema/revision/53"],
    )
    cross_api = PlanOracle(
        id="query-create-id",
        step_id="orders-query",
        kind="cross_api",
        expression="body.id",
        expected_source=PlanOracleValueSource(
            step_id="orders-create",
            expression="body.id",
        ),
        confidence=1,
        source_ref="context://s53/oracle/create-query-id",
        applies_to=["orders-create", "orders-query"],
        evidence_refs=["context://s53/oracle/create-query-id"],
    )
    request = _planner_request([create, query]).model_copy(
        update={"database_reads": [database_read], "additional_oracles": [cross_api]}
    )

    plan = build_integration_plan(request)
    result = compile_integration_plan(plan)

    assert plan.schema_version == "flowtest-integration-plan-v2"
    assert plan.fingerprint_version == "flowtest-integration-plan-fingerprint-v2"
    assert plan.steps[-1].db_read_ref == database_read.id
    assert result.compiler_version == "flowtest-integration-plan-compiler-s53-v1"
    assert result.importable is True


@pytest.mark.asyncio
async def test_asset_service_reads_canonical_contract_scenario_oracle_and_existing_workflow(
    s50_session: tuple[AsyncSession, User, Project],
) -> None:
    session, actor, project = s50_session
    service = Service(
        project_id=project.id,
        service_key="orders",
        name="Orders",
        description="",
        owner_team=None,
        service_type="http",
        enabled=True,
        created_by_id=actor.id,
    )
    session.add(service)
    await session.flush()
    contract = OperationContract(
        operation="orders.protected",
        method="GET",
        path="/protected",
        service="orders",
        auth=ContractAuth(
            required=True,
            kind="bearer",
            location="header",
            name="Authorization",
            source_ref="contract://orders/protected/auth",
        ),
        responses={
            "200": ContractResponse(
                description="OK",
                schema={"type": "object", "properties": {"id": {"type": "string"}}},
            )
        },
        source_ref="contract://orders/protected",
        revision="1",
    )
    definition = APIDefinition(
        project_id=project.id,
        folder_id=None,
        service_id=service.id,
        name="orders.protected",
        description="",
        current_version=1,
        is_active=True,
        import_key="orders.protected",
        import_fingerprint=fingerprint_contract(contract),
        import_source="s50-test",
        import_source_key="orders.protected",
        created_by_id=actor.id,
    )
    session.add(definition)
    await session.flush()
    session.add(
        APIVersion(
            api_definition_id=definition.id,
            version=1,
            method="GET",
            path="/protected",
            query_parameters=[],
            headers={},
            variables={},
            body_kind="none",
            body=None,
            auth_kind="bearer",
            auth_config={"in": "header", "name": "Authorization"},
            extraction_rules=[],
            assertions=[],
            canonical_contract=contract.model_dump(mode="json", by_alias=True),
            contract_fingerprint=fingerprint_contract(contract),
            contract_completeness="complete",
            created_by_id=actor.id,
        )
    )
    auth_workflow = Workflow(
        project_id=project.id,
        folder_id=None,
        name="Existing Auth",
        description="",
        draft_definition=_auth_workflow_definition(definition.id),
        draft_revision=1,
        current_version=1,
        created_by_id=actor.id,
    )
    session.add(auth_workflow)
    await session.flush()
    session.add(
        WorkflowVersion(
            workflow_id=auth_workflow.id,
            version=1,
            definition=_auth_workflow_definition(definition.id),
            fingerprint="a" * 64,
            created_by_id=actor.id,
            published_at=datetime.now(UTC),
        )
    )
    await session.commit()

    plan = await IntegrationPlanAssetService(session).build(
        actor=actor,
        project_id=project.id,
        command=IntegrationPlanAssetCommand(
            context_revision_id=UUID("00000000-0000-0000-0000-000000000051"),
            context_fingerprint="6" * 64,
            objective="Reuse Existing Auth for protected operation",
            actors=(
                PlanActor(
                    id="operator",
                    role="integration tester",
                    evidence_refs=["context://s50/operator"],
                ),
            ),
            preconditions=(),
            target_environment=PlanTargetEnvironment(
                key="test",
                source_ref="environment://test",
                evidence_refs=["environment://test/revision/1"],
            ),
            operations=(OperationPlanSelection(definition_id=definition.id),),
            existing_auth=ExistingAuthWorkflowSelection(
                workflow_id=auth_workflow.id,
                workflow_version=1,
                token_path="nodes[?node_id=='login']|[0].output.body.token",
            ),
        ),
    )

    assert validate_integration_plan(plan).valid is True
    assert plan.steps[0].kind == "subflow"
    assert plan.operations[0].contract_fingerprint == fingerprint_contract(contract)
    assert plan.oracles and all(not oracle.requires_review for oracle in plan.oracles)
    assert plan.bindings[0].candidates[0].source_step_id == "existing-auth"
    assert any(
        ref.startswith(f"workflow://{auth_workflow.id}/version/1") for ref in plan.evidence_refs
    )
    assert compile_integration_plan(plan).importable is True


@pytest.mark.asyncio
async def test_asset_service_rejects_cross_project_operation(
    s50_session: tuple[AsyncSession, User, Project],
) -> None:
    session, actor, project = s50_session
    foreign_project = Project(
        organization_id=project.organization_id,
        name="Foreign S50 project",
        created_by_id=actor.id,
    )
    session.add(foreign_project)
    await session.flush()
    foreign_definition = APIDefinition(
        project_id=foreign_project.id,
        folder_id=None,
        service_id=None,
        name="foreign.operation",
        description="",
        current_version=1,
        is_active=True,
        import_key="foreign.operation",
        import_fingerprint="f" * 64,
        import_source="s50-test",
        import_source_key="foreign.operation",
        created_by_id=actor.id,
    )
    session.add(foreign_definition)
    await session.commit()

    with pytest.raises(AppError) as error_info:
        await IntegrationPlanAssetService(session).build(
            actor=actor,
            project_id=project.id,
            command=IntegrationPlanAssetCommand(
                context_revision_id=UUID("00000000-0000-0000-0000-000000000052"),
                context_fingerprint="7" * 64,
                objective="Reject foreign operation",
                actors=(
                    PlanActor(
                        id="operator",
                        role="integration tester",
                        evidence_refs=["context://s50/operator"],
                    ),
                ),
                preconditions=(),
                target_environment=PlanTargetEnvironment(
                    key="test",
                    source_ref="environment://test",
                    evidence_refs=["environment://test/revision/1"],
                ),
                operations=(OperationPlanSelection(definition_id=foreign_definition.id),),
            ),
        )

    assert error_info.value.code == "API_DEFINITION_NOT_FOUND"


@pytest.mark.asyncio
async def test_asset_service_validates_s53_dataset_and_database_ownership(
    s50_session: tuple[AsyncSession, User, Project],
) -> None:
    session, actor, project = s50_session
    foreign_project = Project(
        organization_id=project.organization_id,
        name="Foreign S53 data project",
        created_by_id=actor.id,
    )
    session.add(foreign_project)
    await session.flush()
    foreign_artifact = Artifact(
        project_id=foreign_project.id,
        object_key=f"s53/{uuid4()}",
        filename="approved.csv",
        content_type="text/csv",
        size_bytes=10,
        sha256="5" * 64,
        purpose="upload",
        created_by_id=actor.id,
    )
    foreign_credential = Credential(
        project_id=foreign_project.id,
        name="foreign-readonly-postgres",
        kind="postgresql",
        host="database.example.test",
        port=5432,
        database_name="orders",
        username="flowtest_reader",
        secret_provider="local",
        provider_reference=None,
        ciphertext=b"encrypted",
        nonce=b"0123456789ab",
        tls_enabled=True,
        created_by_id=actor.id,
    )
    wrong_dialect_credential = Credential(
        project_id=project.id,
        name="local-readonly-mysql",
        kind="mysql",
        host="database.example.test",
        port=3306,
        database_name="orders",
        username="flowtest_reader",
        secret_provider="local",
        provider_reference=None,
        ciphertext=b"encrypted",
        nonce=b"0123456789ab",
        tls_enabled=True,
        created_by_id=actor.id,
    )
    session.add_all([foreign_artifact, foreign_credential, wrong_dialect_credential])
    await session.commit()
    recipe = PlanDataRecipe(
        id="approved-orders",
        kind="approved_dataset",
        name="Approved orders",
        artifact_id=foreign_artifact.id,
        source_ref="artifact://approved-orders/revision/1",
        evidence_refs=["artifact://approved-orders/revision/1"],
    )
    database_read = PlanDatabaseRead(
        id="orders-db-read",
        name="Read order",
        credential_id=foreign_credential.id,
        dialect="postgresql",
        table="orders",
        columns=["id"],
        predicates=[
            PlanDatabasePredicate(
                column="id",
                parameter="order_id",
                variable_name="orders-create-id",
            )
        ],
        source_ref="database://orders/schema/revision/53",
        evidence_refs=["database://orders/schema/revision/53"],
    )
    service = IntegrationPlanAssetService(session)

    with pytest.raises(AppError) as artifact_error:
        await service._validate_data_assets(
            project_id=project.id,
            data_recipes=(recipe,),
            database_reads=(),
        )
    with pytest.raises(AppError) as credential_error:
        await service._validate_data_assets(
            project_id=project.id,
            data_recipes=(),
            database_reads=(database_read,),
        )
    with pytest.raises(AppError) as dialect_error:
        await service._validate_data_assets(
            project_id=project.id,
            data_recipes=(),
            database_reads=(
                database_read.model_copy(update={"credential_id": wrong_dialect_credential.id}),
            ),
        )

    assert artifact_error.value.code == "DATA_RECIPE_ARTIFACT_NOT_FOUND"
    assert credential_error.value.code == "DATABASE_READ_CREDENTIAL_NOT_FOUND"
    assert dialect_error.value.code == "DATABASE_READ_CREDENTIAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_compiled_plan_creates_reviewed_workflow_draft_and_frozen_snapshot(
    s50_session: tuple[AsyncSession, User, Project],
) -> None:
    session, actor, project = s50_session
    plan = _golden_plan()
    compilation = compile_integration_plan(plan)
    assert compilation.flow_spec is not None and compilation.importable
    service = Service(
        project_id=project.id,
        service_key="orders",
        name="Orders",
        description="",
        owner_team=None,
        service_type="http",
        enabled=True,
        created_by_id=actor.id,
    )
    session.add(service)
    await session.flush()
    operation_ids: dict[str, UUID] = {}
    for operation in plan.operations:
        definition = APIDefinition(
            project_id=project.id,
            folder_id=None,
            service_id=service.id,
            name=operation.name,
            description="",
            current_version=1,
            is_active=True,
            import_key=operation.ref,
            import_fingerprint=operation.contract_fingerprint,
            import_source="s50-golden",
            import_source_key=operation.ref,
            created_by_id=actor.id,
        )
        session.add(definition)
        await session.flush()
        session.add(
            APIVersion(
                api_definition_id=definition.id,
                service_id=service.id,
                version=1,
                method=operation.method,
                path=operation.path,
                query_parameters=[],
                headers={},
                variables={},
                body_kind="none",
                body=None,
                auth_kind="none",
                auth_config={},
                extraction_rules=[],
                assertions=[],
                canonical_contract={},
                contract_fingerprint=operation.contract_fingerprint,
                contract_completeness="complete",
                created_by_id=actor.id,
            )
        )
        operation_ids[operation.ref] = definition.id
    await session.commit()

    service_layer = FlowSpecService(session)
    context_revision_id = plan.context_revision_id
    provenance = FlowSpecImportProvenance(
        context_revision_id=context_revision_id,
        context_fingerprint=plan.context_fingerprint,
        source_ref=f"context://{context_revision_id}/integration-plan",
        service_account_id=uuid4(),
        integration_plan=plan,
        compilation=compilation,
    )
    with pytest.raises(AppError) as error_info:
        await service_layer.create_import(
            actor=actor,
            project_id=project.id,
            payload=FlowSpecImportRequest(
                spec=compilation.flow_spec,
                service_mappings={"orders": service.id},
                operation_mappings=operation_ids,
                operation_version_mappings={ref: 1 for ref in operation_ids},
            ),
            provenance=replace(
                provenance,
                compilation=compilation.model_copy(update={"passes": []}),
            ),
        )
    assert error_info.value.code == "INTEGRATION_PLAN_PROVENANCE_INVALID"

    view = await service_layer.create_import(
        actor=actor,
        project_id=project.id,
        payload=FlowSpecImportRequest(
            spec=compilation.flow_spec,
            service_mappings={"orders": service.id},
            operation_mappings=operation_ids,
            operation_version_mappings={ref: 1 for ref in operation_ids},
        ),
        provenance=provenance,
    )
    snapshot = view.change_set.source_snapshot
    assert view.change_set.status == "draft"
    assert snapshot["integration_plan_fingerprint"] == plan.plan_fingerprint
    assert snapshot["integration_plan"]["schema_version"] == ("flowtest-integration-plan-v1")
    assert snapshot["integration_plan_compiler"]["version"] == (
        "flowtest-integration-plan-compiler-v1"
    )
    assert snapshot["integration_plan_compiler"]["flow_spec_fingerprint"] == (
        compilation.flow_spec_fingerprint
    )
    assert snapshot["integration_plan_compiler"]["node_evidence"]
    assert snapshot["integration_plan_compiler"]["edge_evidence"]

    await service_layer.review(
        actor=actor,
        project_id=project.id,
        change_set_id=view.change_set.id,
        accept=True,
        note="S50 golden plan reviewed",
    )
    applied, workflow = await service_layer.apply(
        actor=actor,
        project_id=project.id,
        change_set_id=view.change_set.id,
    )
    assert applied.change_set.applied_at is not None
    assert workflow.draft_revision == 1
    workflow_definition = WorkflowDefinition.model_validate(workflow.draft_definition)
    assert {node.type.value for node in workflow_definition.nodes} >= {
        "api",
        "extract",
        "assert",
    }

    create_step = next(step for step in plan.steps if step.operation_ref == "orders.create")
    cleanup_plan = seal_integration_plan(
        plan.model_copy(
            update={
                "objective": "Login Create Query Cleanup",
                "cleanup_requirements": [
                    PlanCleanupRequirement(
                        id="cleanup-order",
                        operation_ref="orders.create",
                        cleanup_for_step_ids=[create_step.id],
                        evidence_refs=["contract://orders/cleanup"],
                    )
                ],
                "plan_fingerprint": "0" * 64,
            }
        )
    )
    cleanup_compilation = compile_integration_plan(cleanup_plan)
    assert isinstance(cleanup_compilation.flow_spec, FlowSpecV2)
    cleanup_view = await service_layer.create_import(
        actor=actor,
        project_id=project.id,
        payload=FlowSpecImportRequest(
            spec=cleanup_compilation.flow_spec,
            service_mappings={"orders": service.id},
            operation_mappings=operation_ids,
            operation_version_mappings={ref: 1 for ref in operation_ids},
        ),
        provenance=FlowSpecImportProvenance(
            context_revision_id=cleanup_plan.context_revision_id,
            context_fingerprint=cleanup_plan.context_fingerprint,
            source_ref=f"context://{context_revision_id}/cleanup-plan",
            service_account_id=uuid4(),
            integration_plan=cleanup_plan,
            compilation=cleanup_compilation,
        ),
    )
    assert cleanup_view.pipeline.spec.schema_version == "flowtest-flow-spec-v2"
    await service_layer.review(
        actor=actor,
        project_id=project.id,
        change_set_id=cleanup_view.change_set.id,
        accept=True,
        note="S54 cleanup runtime reviewed",
    )
    _cleanup_applied, cleanup_workflow = await service_layer.apply(
        actor=actor,
        project_id=project.id,
        change_set_id=cleanup_view.change_set.id,
    )
    cleanup_definition = WorkflowDefinition.model_validate(cleanup_workflow.draft_definition)
    cleanup_node = next(node for node in cleanup_definition.nodes if node.phase == "cleanup")
    assert cleanup_node.id == "cleanup-order"
    assert cleanup_node.cleanup_for == [create_step.id]
    exported = await service_layer.export(
        actor=actor,
        project_id=project.id,
        workflow_id=cleanup_workflow.id,
        version=None,
    )
    assert isinstance(exported.pipeline.spec, FlowSpecV2)
    assert exported.pipeline.spec.cleanup[0].id == "cleanup-order"


def _golden_plan() -> IntegrationPlan:
    login = _selected_operation(
        ref="auth.login",
        contract=OperationContract(
            operation="auth.login",
            method="POST",
            path="/api/login",
            service="orders",
            responses={
                "200": ContractResponse(
                    description="Authenticated",
                    schema={
                        "type": "object",
                        "required": ["token"],
                        "properties": {"token": {"type": "string"}},
                    },
                )
            },
            source_ref="contract://auth/login",
        ),
        status=200,
    )
    create = _selected_operation(
        ref="orders.create",
        contract=OperationContract(
            operation="orders.create",
            method="POST",
            path="/api/orders",
            service="orders",
            auth=ContractAuth(
                required=True,
                kind="bearer",
                location="header",
                name="Authorization",
                source_ref="contract://orders/create/auth",
            ),
            request_body=ContractRequestBody(
                required=True,
                schema={
                    "type": "object",
                    "required": ["product_id", "quantity"],
                    "properties": {
                        "product_id": {"type": "string"},
                        "quantity": {"type": "integer"},
                    },
                },
            ),
            responses={
                "201": ContractResponse(
                    description="Created",
                    schema={
                        "type": "object",
                        "required": ["id", "status"],
                        "properties": {
                            "id": {"type": "string"},
                            "status": {"type": "string"},
                        },
                    },
                )
            },
            source_ref="contract://orders/create",
        ),
        status=201,
        scenario=ScenarioCandidate(
            id="orders.create.happy",
            kind="happy_path",
            title="Create an order",
            request=ScenarioRequest(body={"product_id": "sku-golden", "quantity": 1}),
            request_body={"product_id": "sku-golden", "quantity": 1},
            expected_category="success",
            evidence_refs=["scenario://orders/create/happy"],
        ),
    )
    query = _selected_operation(
        ref="orders.query",
        contract=OperationContract(
            operation="orders.query",
            method="GET",
            path="/api/orders",
            service="orders",
            parameters=[
                ContractParameter(
                    name="id",
                    location="query",
                    required=True,
                    schema={"type": "string"},
                    source_ref="contract://orders/query/id",
                )
            ],
            responses={
                "200": ContractResponse(
                    description="Found",
                    schema={
                        "type": "object",
                        "required": ["id", "status"],
                        "properties": {
                            "id": {"type": "string"},
                            "status": {"type": "string"},
                        },
                    },
                )
            },
            source_ref="contract://orders/query",
        ),
        status=200,
        extra_oracles=[
            OracleSpec(
                id="query.schema",
                kind="schema",
                expression="body",
                operator="equals",
                expected={
                    "type": "object",
                    "required": ["id", "status"],
                    "properties": {
                        "id": {"type": "string"},
                        "status": {"type": "string"},
                    },
                },
                confidence=1,
                evidence_refs=["contract://orders/query/response-schema"],
            ),
            OracleSpec(
                id="query.id.exists",
                kind="json_path",
                expression="body.id",
                operator="exists",
                expected=None,
                confidence=1,
                evidence_refs=["contract://orders/query/response-id"],
            ),
        ],
    )
    return build_integration_plan(_planner_request([login, create, query]))


def _planner_request(
    selected: list[SelectedOperationEvidence],
) -> IntegrationPlannerRequest:
    return IntegrationPlannerRequest(
        context_revision_id=UUID("00000000-0000-0000-0000-000000000050"),
        context_fingerprint="5" * 64,
        objective="Login Create Query",
        actors=[
            PlanActor(
                id="operator",
                role="integration tester",
                evidence_refs=["context://golden/actor/operator"],
            )
        ],
        preconditions=[
            PlanPrecondition(
                id="target-ready",
                description="Golden target is available",
                evidence_refs=["environment://golden/ready"],
            )
        ],
        target_environment=PlanTargetEnvironment(
            key="golden",
            source_ref="environment://golden",
            evidence_refs=["environment://golden/revision/1"],
        ),
        selected_operations=selected,
    )


def _selected_operation(
    *,
    ref: str,
    contract: OperationContract,
    status: int,
    scenario: ScenarioCandidate | None = None,
    extra_oracles: list[OracleSpec] | None = None,
) -> SelectedOperationEvidence:
    evidence_ref = contract.source_ref or f"contract://{ref}"
    return SelectedOperationEvidence(
        operation_ref=ref,
        service_name="Orders",
        source_version=1,
        contract=contract,
        scenario=scenario,
        oracles=[
            OracleSpec(
                id=f"{ref}.status",
                kind="status",
                expression="status_code",
                operator="equals",
                expected=status,
                confidence=1,
                evidence_refs=[evidence_ref],
            ),
            *(extra_oracles or []),
        ],
        selected_by_user=True,
        evidence_refs=[evidence_ref],
    )


def _response_contract(operation: str, path: str, suffix: str) -> OperationContract:
    return OperationContract(
        operation=operation,
        method="POST",
        path=path,
        service="orders",
        responses={
            "200": ContractResponse(
                description="OK",
                schema={
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "string"}},
                },
            )
        },
        source_ref=f"contract://orders/{suffix}",
    )


def _auth_workflow_definition(api_definition_id: UUID) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "variables": {},
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "name": "Start",
                "position": {"x": 0, "y": 0},
                "config": {},
            },
            {
                "id": "login",
                "type": "api",
                "name": "Login",
                "position": {"x": 180, "y": 0},
                "config": {"api_definition_id": str(api_definition_id), "api_version": 1},
            },
            {
                "id": "end",
                "type": "end",
                "name": "End",
                "position": {"x": 360, "y": 0},
                "config": {},
            },
        ],
        "edges": [
            {"id": "start-login", "source": "start", "target": "login"},
            {"id": "login-end", "source": "login", "target": "end"},
        ],
        "settings": {"fail_fast": True, "concurrency": 5, "default_timeout_seconds": 30},
    }


def _trace(values: Sequence[CompilerEvidenceTrace], resource_id: str) -> list[str]:
    for value in values:
        if value.resource_id == resource_id:
            return value.evidence_refs
    return []
