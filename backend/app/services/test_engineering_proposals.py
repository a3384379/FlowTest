from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.change_regression import OperationIdentity
from app.domain.evidence import EvidenceBundle
from app.domain.test_design import (
    OracleSpec,
    ScenarioCandidate,
    TestDesignDocument,
    fingerprint_design,
    normalized_design,
)
from app.domain.test_engineering import (
    GenerationPolicy,
    OperationContract,
    TestEngineeringEngine,
    fingerprint_contract,
)
from app.engine.contracts import WorkflowDefinition
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.api_assets import APIDefinition, Environment
from app.models.service_targets import ServiceEndpoint
from app.models.test_design import TestDesign
from app.repositories.api_assets import APIAssetRepository
from app.schemas.test_assets import TestCaseDefinitionInput
from app.schemas.test_engineering import TestEngineeringProposalCreate
from app.services.audit import AuditService
from app.services.projects import ProjectService
from app.services.test_assets import TestCaseService
from app.services.test_engineering import TestEngineeringService
from app.services.workflows import WorkflowService


@dataclass(frozen=True, slots=True)
class TestEngineeringProposalView:
    change_set: AIChangeSet
    item: AIChangeItem
    design: TestDesignDocument
    scenario_ids: list[str]


@dataclass(frozen=True, slots=True)
class TestEngineeringMaterialization:
    change_set_id: UUID
    test_design_id: UUID
    workflow_ids: list[UUID]
    test_case_ids: list[UUID]


class TestEngineeringProposalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._assets = APIAssetRepository(session)
        self._audit = AuditService(session)

    async def propose(
        self,
        *,
        actor: User,
        project_id: UUID,
        payload: TestEngineeringProposalCreate,
    ) -> TestEngineeringProposalView:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        definition, api_version = await self._target_api(project_id, payload.api_definition_id)
        await self._target_environment(project_id, payload.environment_id)
        endpoint_variant = await self._endpoint_variant(
            project_id=project_id,
            environment_id=payload.environment_id,
            service_id=definition.service_id,
            requested=payload.endpoint_variant,
        )
        api_contract = await TestEngineeringService(self._session).contract_for_api(
            project_id=project_id, definition_id=definition.id
        )
        contract = payload.contract or api_contract
        if (contract.method, contract.path) != (api_contract.method, api_contract.path):
            raise AppError(
                code="TEST_ENGINEERING_TARGET_MISMATCH",
                message="Contract method/path 与目标 API 不一致",
                status_code=422,
            )
        design = TestEngineeringEngine().generate(
            contract=contract,
            policy=payload.generation_policy,
            additional_evidence=payload.additional_evidence,
        )
        scenario_ids = _selected_scenarios(design, payload.scenario_ids)
        fingerprint = fingerprint_design(design)
        change_set = AIChangeSet(
            project_id=project_id,
            impact_run_id=None,
            release_risk_id=None,
            ai_job_id=None,
            title=payload.title.strip(),
            status="draft",
            source_snapshot={
                "schema_version": "s47-test-engineering-proposal-v2",
                "api_definition_id": str(definition.id),
                "api_version": api_version,
                "environment_id": str(payload.environment_id),
                "endpoint_variant": endpoint_variant,
                "scenario_ids": scenario_ids,
                "design_fingerprint": fingerprint,
                "contract_fingerprint": fingerprint_contract(contract),
                "api_contract_fingerprint": fingerprint_contract(api_contract),
                "evidence_fingerprints": sorted(
                    _evidence_fingerprint(bundle) for bundle in payload.additional_evidence
                ),
                "additional_evidence": [
                    bundle.model_dump(mode="json") for bundle in payload.additional_evidence
                ],
                "generation_policy": payload.generation_policy.model_dump(mode="json"),
                "contract": contract.model_dump(mode="json", by_alias=True),
            },
            source_fingerprint=fingerprint,
            source_type="rest",
            source_ref=contract.source_ref or f"contract://{contract.operation}",
            actor_type="user",
            actor_id=actor.id,
            created_by_id=actor.id,
        )
        self._session.add(change_set)
        await self._session.flush()
        item = AIChangeItem(
            change_set_id=change_set.id,
            suggestion_id=None,
            position=0,
            item_type="test_design",
            action="create",
            title=payload.title.strip(),
            target_resource_id=None,
            target_snapshot_sha256=None,
            proposed_content={
                "design": normalized_design(design),
                "scenario_ids": scenario_ids,
            },
            review_status="pending",
        )
        self._session.add(item)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="test_engineering.proposed",
            resource_type="ai_change_set",
            resource_id=change_set.id,
            details={"scenario_count": len(scenario_ids), "fingerprint": fingerprint},
        )
        await self._session.commit()
        await self._session.refresh(change_set)
        await self._session.refresh(item)
        return TestEngineeringProposalView(change_set, item, design, scenario_ids)

    async def review(
        self,
        *,
        actor: User,
        project_id: UUID,
        change_set_id: UUID,
        accept: bool,
        note: str,
    ) -> TestEngineeringProposalView:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        change_set, item = await self._proposal(change_set_id, project_id, for_update=True)
        if item.review_status != "pending":
            raise AppError(
                code="TEST_ENGINEERING_ALREADY_REVIEWED",
                message="测试工程 Proposal 已完成审核",
                status_code=409,
            )
        item.review_status = "accepted" if accept else "rejected"
        item.review_note = note.strip()
        item.reviewed_by_id = actor.id
        item.reviewed_at = datetime.now(UTC)
        change_set.status = "accepted" if accept else "rejected"
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="test_engineering.reviewed",
            resource_type="ai_change_set",
            resource_id=change_set.id,
            details={"accepted": accept},
        )
        await self._session.commit()
        return _view(change_set, item)

    async def apply(
        self, *, actor: User, project_id: UUID, change_set_id: UUID
    ) -> TestEngineeringMaterialization:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        change_set, item = await self._proposal(change_set_id, project_id, for_update=True)
        _require_applicable(change_set, item)
        design, scenario_ids = _proposal_content(item)
        _validate_frozen_generation(change_set, design)
        api_id, environment_id, expected_version, endpoint_variant = _proposal_targets(
            change_set.source_snapshot
        )
        definition, current_version = await self._target_api(project_id, api_id)
        await self._target_environment(project_id, environment_id)
        if current_version != expected_version:
            raise AppError(
                code="TEST_ENGINEERING_TARGET_STALE",
                message="目标 API 版本已变化,请重新生成 Proposal",
                status_code=409,
            )
        current_contract = await TestEngineeringService(self._session).contract_for_api(
            project_id=project_id, definition_id=definition.id
        )
        expected_api_contract = change_set.source_snapshot.get("api_contract_fingerprint")
        if (
            not isinstance(expected_api_contract, str)
            or fingerprint_contract(current_contract) != expected_api_contract
        ):
            raise AppError(
                code="TEST_ENGINEERING_TARGET_STALE",
                message="目标 API canonical contract 已变化,请重新生成 Proposal",
                status_code=409,
            )
        endpoint_variant = await self._endpoint_variant(
            project_id=project_id,
            environment_id=environment_id,
            service_id=definition.service_id,
            requested=endpoint_variant,
        )
        materialized = await self._materialize(
            actor=actor,
            project_id=project_id,
            change_set=change_set,
            title=item.title,
            design=design,
            scenarios=_scenario_models(design, scenario_ids),
            definition=definition,
            environment_id=environment_id,
            endpoint_variant=endpoint_variant,
            api_version=expected_version,
        )
        item.materialized_resource_type = "test_design"
        item.materialized_resource_id = materialized.test_design_id
        change_set.applied_at = datetime.now(UTC)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="test_engineering.applied",
            resource_type="test_design",
            resource_id=materialized.test_design_id,
            details={
                "workflow_count": len(materialized.workflow_ids),
                "test_case_count": len(materialized.test_case_ids),
            },
        )
        await self._session.commit()
        return materialized

    async def materialize_reviewed_design(
        self,
        *,
        actor: User,
        project_id: UUID,
        change_set: AIChangeSet,
        title: str,
        design: TestDesignDocument,
        api_definition_id: UUID,
        environment_id: UUID,
        endpoint_variant: str | None,
        scenario_ids: list[str],
        frozen_operation: OperationIdentity | None = None,
    ) -> TestEngineeringMaterialization:
        """Reuse the reviewed Test Engineering materializer for another ChangeSet flow."""

        if frozen_operation is not None and frozen_operation.api_definition_id != str(
            api_definition_id
        ):
            raise _change_regression_target_mismatch()
        definition, api_version = await self._target_api(project_id, api_definition_id)
        current_contract = await TestEngineeringService(self._session).contract_for_api(
            project_id=project_id, definition_id=definition.id
        )
        if frozen_operation is not None:
            _validate_change_regression_target(
                frozen=frozen_operation,
                definition=definition,
                api_version=api_version,
                contract=current_contract,
            )
        await self._target_environment(project_id, environment_id)
        resolved_variant = await self._endpoint_variant(
            project_id=project_id,
            environment_id=environment_id,
            service_id=definition.service_id,
            requested=endpoint_variant,
        )
        selected_ids = scenario_ids or [scenario.id for scenario in design.scenarios]
        return await self._materialize(
            actor=actor,
            project_id=project_id,
            change_set=change_set,
            title=title,
            design=design,
            scenarios=_scenario_models(design, selected_ids),
            definition=definition,
            environment_id=environment_id,
            endpoint_variant=resolved_variant,
            api_version=api_version,
        )

    async def _materialize(
        self,
        *,
        actor: User,
        project_id: UUID,
        change_set: AIChangeSet,
        title: str,
        design: TestDesignDocument,
        scenarios: list[ScenarioCandidate],
        definition: APIDefinition,
        environment_id: UUID,
        endpoint_variant: str | None,
        api_version: int,
    ) -> TestEngineeringMaterialization:
        if "constraint_unsatisfiable" in design.review_requirements:
            raise AppError(
                code="TEST_ENGINEERING_CONSTRAINT_UNSATISFIABLE",
                message="测试设计包含不可满足的约束,禁止物化 Workflow/TestCase",
                status_code=409,
            )
        await self._ensure_unique_design(project_id, title)
        workflow_ids: list[UUID] = []
        test_case_ids: list[UUID] = []
        for scenario in scenarios:
            expected_status = _expected_status(design, scenario)
            scenario_oracles = _scenario_oracles(design, scenario)
            workflow = await WorkflowService(self._session).create(
                actor=actor,
                project_id=project_id,
                name=_asset_name(title, scenario, "Workflow"),
                description=f"由 Test Engineering Proposal {change_set.id} 生成",
                folder_id=None,
                definition=_scenario_workflow(
                    definition.id,
                    api_version,
                    scenario,
                    expected_status,
                    scenario_oracles,
                    endpoint_variant,
                ),
                commit=False,
            )
            test_case = await TestCaseService(self._session).create(
                actor=actor,
                project_id=project_id,
                name=_asset_name(title, scenario, "TestCase"),
                description=f"Evidence-driven scenario: {scenario.title}",
                folder_id=None,
                tags=["generated", "test-engineering", scenario.kind],
                is_template=False,
                definition=TestCaseDefinitionInput(
                    workflow_id=workflow.id, environment_id=environment_id
                ),
                commit=False,
            )
            workflow_ids.append(workflow.id)
            test_case_ids.append(test_case.id)
        model = _test_design_model(
            actor=actor,
            project_id=project_id,
            change_set=change_set,
            title=title,
            design=design,
            scenarios=scenarios,
            test_case_ids=test_case_ids,
        )
        self._session.add(model)
        await self._session.flush()
        return TestEngineeringMaterialization(
            change_set_id=change_set.id,
            test_design_id=model.id,
            workflow_ids=workflow_ids,
            test_case_ids=test_case_ids,
        )

    async def _proposal(
        self, change_set_id: UUID, project_id: UUID, *, for_update: bool
    ) -> tuple[AIChangeSet, AIChangeItem]:
        query = select(AIChangeSet).where(
            AIChangeSet.id == change_set_id,
            AIChangeSet.project_id == project_id,
            AIChangeSet.source_type == "rest",
        )
        if for_update:
            query = query.with_for_update()
        change_set = (await self._session.execute(query)).scalar_one_or_none()
        if change_set is None or change_set.source_snapshot.get("schema_version") not in {
            "s47-test-engineering-proposal-v1",
            "s47-test-engineering-proposal-v2",
        }:
            raise AppError(
                code="TEST_ENGINEERING_PROPOSAL_NOT_FOUND",
                message="测试工程 Proposal 不存在",
                status_code=404,
            )
        item_query = select(AIChangeItem).where(AIChangeItem.change_set_id == change_set.id)
        if for_update:
            item_query = item_query.with_for_update()
        item = (await self._session.execute(item_query)).scalar_one_or_none()
        if item is None:
            raise AppError(
                code="TEST_ENGINEERING_PROPOSAL_INVALID",
                message="测试工程 Proposal 缺少变更项",
                status_code=409,
            )
        return change_set, item

    async def _target_api(self, project_id: UUID, definition_id: UUID) -> tuple[APIDefinition, int]:
        definition = await self._assets.get_definition(definition_id)
        if definition is None or definition.project_id != project_id:
            raise AppError(
                code="API_DEFINITION_NOT_FOUND", message="API 定义不存在", status_code=404
            )
        return definition, definition.current_version

    async def _target_environment(self, project_id: UUID, environment_id: UUID) -> Environment:
        environment = await self._session.get(Environment, environment_id)
        if environment is None or environment.project_id != project_id:
            raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)
        return environment

    async def _ensure_unique_design(self, project_id: UUID, title: str) -> None:
        duplicate = await self._session.scalar(
            select(TestDesign.id).where(
                TestDesign.project_id == project_id, TestDesign.name == title
            )
        )
        if duplicate is not None:
            raise AppError(
                code="TEST_DESIGN_NAME_EXISTS", message="Test Design 名称已存在", status_code=409
            )

    async def _endpoint_variant(
        self,
        *,
        project_id: UUID,
        environment_id: UUID,
        service_id: UUID | None,
        requested: str | None,
    ) -> str | None:
        if service_id is None:
            if requested is not None:
                raise AppError(
                    code="TEST_ENGINEERING_ENDPOINT_VARIANT_INVALID",
                    message="未绑定 Service 的 API 不能指定 Endpoint Variant",
                    status_code=422,
                )
            return None
        endpoints = list(
            (
                await self._session.scalars(
                    select(ServiceEndpoint).where(
                        ServiceEndpoint.project_id == project_id,
                        ServiceEndpoint.environment_id == environment_id,
                        ServiceEndpoint.service_id == service_id,
                        ServiceEndpoint.enabled.is_(True),
                    )
                )
            ).all()
        )
        if requested is not None:
            if any(endpoint.variant == requested for endpoint in endpoints):
                return requested
            raise AppError(
                code="SERVICE_ENDPOINT_NOT_FOUND",
                message="当前环境没有配置该 Service 的 Endpoint Variant",
                status_code=422,
                details={"service_id": str(service_id), "variant": requested},
            )
        if len(endpoints) == 1:
            return endpoints[0].variant
        default = next((endpoint for endpoint in endpoints if endpoint.variant == "default"), None)
        if default is not None:
            return default.variant
        if not endpoints:
            raise AppError(
                code="SERVICE_ENDPOINT_NOT_FOUND",
                message="当前环境没有配置该 Service 的 Endpoint Variant",
                status_code=422,
                details={"service_id": str(service_id)},
            )
        raise AppError(
            code="TEST_ENGINEERING_ENDPOINT_VARIANT_REQUIRED",
            message="该 Service 有多个 Endpoint Variant, 请明确选择物化目标",
            status_code=422,
            details={"variants": sorted(endpoint.variant for endpoint in endpoints)},
        )


def _selected_scenarios(design: TestDesignDocument, requested: list[str]) -> list[str]:
    known = {scenario.id for scenario in design.scenarios}
    if requested:
        unknown = sorted(set(requested) - known)
        if unknown:
            raise AppError(
                code="TEST_ENGINEERING_SCENARIO_INVALID",
                message=f"Scenario 不存在: {', '.join(unknown)}",
                status_code=422,
            )
        return list(dict.fromkeys(requested))
    happy = next((item.id for item in design.scenarios if item.kind == "happy_path"), None)
    if happy is None:
        raise AppError(
            code="TEST_ENGINEERING_SCENARIO_INVALID",
            message="生成结果缺少可物化的 Happy Path",
            status_code=422,
        )
    return [happy]


def _require_applicable(change_set: AIChangeSet, item: AIChangeItem) -> None:
    if change_set.status != "accepted" or item.review_status != "accepted":
        raise AppError(
            code="TEST_ENGINEERING_REVIEW_REQUIRED",
            message="测试工程 Proposal 必须审核通过后才能应用",
            status_code=409,
        )
    if change_set.applied_at is not None or item.materialized_resource_id is not None:
        raise AppError(
            code="TEST_ENGINEERING_ALREADY_APPLIED",
            message="测试工程 Proposal 已应用",
            status_code=409,
        )


def _proposal_content(item: AIChangeItem) -> tuple[TestDesignDocument, list[str]]:
    try:
        design = TestDesignDocument.model_validate(item.proposed_content.get("design"))
    except (TypeError, ValueError, ValidationError) as error:
        raise AppError(
            code="TEST_ENGINEERING_PROPOSAL_INVALID",
            message="测试工程 Proposal 内容无效",
            status_code=409,
        ) from error
    raw = item.proposed_content.get("scenario_ids")
    if not isinstance(raw, list) or not all(isinstance(value, str) for value in raw):
        raise AppError(
            code="TEST_ENGINEERING_PROPOSAL_INVALID",
            message="测试工程 Proposal 场景选择无效",
            status_code=409,
        )
    return design, cast(list[str], raw)


def _proposal_targets(snapshot: dict[str, Any]) -> tuple[UUID, UUID, int, str | None]:
    try:
        raw_variant = snapshot.get("endpoint_variant")
        if raw_variant is not None and not isinstance(raw_variant, str):
            raise TypeError("endpoint_variant must be a string")
        return (
            UUID(str(snapshot["api_definition_id"])),
            UUID(str(snapshot["environment_id"])),
            int(snapshot["api_version"]),
            raw_variant,
        )
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise AppError(
            code="TEST_ENGINEERING_PROPOSAL_INVALID",
            message="测试工程 Proposal 目标快照无效",
            status_code=409,
        ) from error


def _scenario_models(
    design: TestDesignDocument, scenario_ids: list[str]
) -> list[ScenarioCandidate]:
    by_id = {scenario.id: scenario for scenario in design.scenarios}
    try:
        return [by_id[scenario_id] for scenario_id in scenario_ids]
    except KeyError as error:
        raise AppError(
            code="TEST_ENGINEERING_PROPOSAL_INVALID",
            message="测试工程 Proposal 引用了未知场景",
            status_code=409,
        ) from error


def _expected_status(design: TestDesignDocument, scenario: ScenarioCandidate) -> int:
    matches = [
        oracle
        for oracle in design.oracles
        if oracle.kind == "status"
        and scenario.id in oracle.applies_to
        and isinstance(oracle.expected, int)
        and oracle.deterministic
        and not oracle.requires_review
        and oracle.operator == "equals"
    ]
    if len(matches) != 1:
        raise AppError(
            code="TEST_ENGINEERING_ORACLE_NOT_EXECUTABLE",
            message=f"Scenario {scenario.id} 缺少唯一的确定性状态码 Oracle",
            status_code=422,
        )
    return cast(int, matches[0].expected)


def _scenario_oracles(design: TestDesignDocument, scenario: ScenarioCandidate) -> list[OracleSpec]:
    result = [oracle for oracle in design.oracles if scenario.id in oracle.applies_to]
    comparison_operators = {
        "equals",
        "not_equals",
        "contains",
        "exists",
        "matches",
    }
    unsupported = [
        oracle.id
        for oracle in result
        if oracle.kind not in {"status", "schema", "json_path", "expression"}
        or (
            oracle.kind in {"json_path", "expression"}
            and oracle.operator not in comparison_operators
        )
        or oracle.requires_review
        or not oracle.deterministic
    ]
    if unsupported:
        raise AppError(
            code="TEST_ENGINEERING_ORACLE_NOT_EXECUTABLE",
            message=f"Scenario {scenario.id} 包含不可执行 Oracle",
            status_code=422,
            details={"oracle_ids": sorted(unsupported)},
        )
    return result


def _scenario_workflow(
    api_definition_id: UUID,
    api_version: int,
    scenario: ScenarioCandidate,
    expected_status: int,
    oracles: list[OracleSpec],
    endpoint_variant: str | None,
) -> WorkflowDefinition:
    if scenario.requires_review or not scenario.deterministic:
        raise AppError(
            code="TEST_ENGINEERING_SCENARIO_NOT_MATERIALIZABLE",
            message="Scenario 包含未解决证据冲突或前置条件,仅可保留为 Design",
            status_code=422,
            details={"scenario_id": scenario.id},
        )
    if any(
        mutation.location == "path" and mutation.operation == "omit"
        for mutation in scenario.mutations
    ):
        raise AppError(
            code="TEST_ENGINEERING_SCENARIO_NOT_MATERIALIZABLE",
            message="必填 path 参数 omission 无法表示为真实 HTTP 请求",
            status_code=422,
            details={"scenario_id": scenario.id, "location": "path"},
        )
    request_overrides = _request_overrides(scenario)
    request_config: dict[str, Any] = {
        "api_definition_id": str(api_definition_id),
        "api_version": api_version,
        "expected_statuses": [expected_status],
        "request_overrides": request_overrides,
    }
    if endpoint_variant is not None:
        request_config["endpoint_variant"] = endpoint_variant
    nodes = [
        _workflow_node("start", "start", "Start", 0, {}),
        _workflow_node("request", "api", scenario.title, 200, request_config),
        _workflow_node(
            "assert_status",
            "assert",
            "Status Oracle",
            400,
            {
                "source_node_id": "request",
                "expression": "status_code",
                "operator": "equals",
                "expected": expected_status,
            },
        ),
    ]
    edges: list[dict[str, str]] = [
        {"id": "start-request", "source": "start", "target": "request"},
        {"id": "request-assert", "source": "request", "target": "assert_status"},
    ]
    previous = "assert_status"
    schema_oracles = [oracle for oracle in oracles if oracle.kind == "schema"]
    for index, oracle in enumerate(schema_oracles, start=1):
        node_id = f"assert_schema_{index}"
        nodes.append(
            _workflow_node(
                node_id,
                "assert",
                "Response Schema Oracle",
                400 + index * 150,
                {
                    "source_node_id": "request",
                    "expression": "body",
                    "operator": "equals",
                    "expected": oracle.expected,
                    "assertion_type": "json_schema",
                },
            )
        )
        edges.append({"id": f"{previous}-{node_id}", "source": previous, "target": node_id})
        previous = node_id
    comparison_oracles = [
        oracle for oracle in oracles if oracle.kind in {"json_path", "expression"}
    ]
    for index, oracle in enumerate(comparison_oracles, start=1):
        node_id = f"assert_expression_{index}"
        nodes.append(
            _workflow_node(
                node_id,
                "assert",
                "Response Expression Oracle",
                550 + index * 150,
                {
                    "source_node_id": "request",
                    "expression": oracle.expression,
                    "operator": oracle.operator,
                    "expected": oracle.expected,
                },
            )
        )
        edges.append({"id": f"{previous}-{node_id}", "source": previous, "target": node_id})
        previous = node_id
    nodes.append(_workflow_node("end", "end", "End", 700, {}))
    edges.append({"id": f"{previous}-end", "source": previous, "target": "end"})
    return WorkflowDefinition.model_validate(
        {
            "schema_version": "1.0",
            "variables": {
                name: _request_value(value)
                for name, value in scenario.request.path_parameters.items()
            },
            "nodes": nodes,
            "edges": edges,
            "settings": {},
        }
    )


def _request_overrides(scenario: ScenarioCandidate) -> dict[str, Any]:
    headers = {name: _request_value(value) for name, value in scenario.request.headers.items()}
    if scenario.request.cookies:
        headers["Cookie"] = "; ".join(
            f"{name}={_request_value(value)}"
            for name, value in sorted(scenario.request.cookies.items())
        )
    overrides: dict[str, Any] = {
        "query_parameters": [
            {"name": name, "value": _request_value(value), "enabled": True}
            for name, value in scenario.request.query_parameters.items()
        ],
        "headers": headers,
        "replace_headers": True,
        "auth_mode": "disabled" if scenario.request.auth_disabled else "inherit",
        "suppressed_headers": sorted(
            {
                mutation.path.split(".", 1)[1]
                for mutation in scenario.mutations
                if mutation.location == "header"
                and mutation.operation == "omit"
                and "." in mutation.path
            }
        ),
        "suppressed_query_parameters": sorted(
            {
                mutation.path.split(".", 1)[1]
                for mutation in scenario.mutations
                if mutation.location == "query"
                and mutation.operation == "omit"
                and "." in mutation.path
            }
        ),
        "suppressed_cookies": sorted(
            {
                mutation.path.split(".", 1)[1]
                for mutation in scenario.mutations
                if mutation.location == "cookie"
                and mutation.operation == "omit"
                and "." in mutation.path
            }
        ),
    }
    if scenario.request.body is not None:
        overrides["body"] = {"kind": "json", "value": scenario.request.body}
    return overrides


def _request_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _workflow_node(
    node_id: str, node_type: str, name: str, x: int, config: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "name": name,
        "position": {"x": x, "y": 0},
        "config": config,
    }


def _test_design_model(
    *,
    actor: User,
    project_id: UUID,
    change_set: AIChangeSet,
    title: str,
    design: TestDesignDocument,
    scenarios: list[ScenarioCandidate],
    test_case_ids: list[UUID],
) -> TestDesign:
    selected_ids = {scenario.id for scenario in scenarios}
    approved_design = design.model_copy(
        update={
            "scenarios": scenarios,
            "oracles": [
                oracle
                for oracle in design.oracles
                if not oracle.applies_to or selected_ids.intersection(oracle.applies_to)
            ],
        }
    )
    payload = approved_design.model_dump(mode="json")
    return TestDesign(
        project_id=project_id,
        name=title,
        status="approved",
        intent=cast(dict[str, Any], payload["intent"]),
        knowledge_graph=cast(dict[str, Any], payload["knowledge_graph"]),
        state_model=cast(dict[str, Any], payload["state_model"] or {}),
        scenarios=cast(list[dict[str, Any]], payload["scenarios"]),
        oracles=cast(list[dict[str, Any]], payload["oracles"]),
        coverage=cast(dict[str, Any], payload["coverage"]),
        evidence_refs=cast(list[dict[str, Any]], payload["evidence_refs"]),
        warnings=list(approved_design.warnings),
        confidence=approved_design.confidence,
        review_requirements=list(approved_design.review_requirements),
        test_case_refs=[f"testcase://{value}" for value in test_case_ids],
        fingerprint=fingerprint_design(approved_design),
        source_change_set_id=change_set.id,
        created_by_id=actor.id,
        reviewed_by_id=actor.id,
        reviewed_at=datetime.now(UTC),
    )


def _asset_name(title: str, scenario: ScenarioCandidate, suffix: str) -> str:
    prefix = f"{title} - {scenario.kind} - {suffix}"
    return f"{prefix[:190]}-{scenario.id[-8:]}"[:200]


def _evidence_fingerprint(bundle: EvidenceBundle) -> str:
    payload = bundle.model_dump(mode="json")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode()).hexdigest()


def _validate_frozen_generation(change_set: AIChangeSet, design: TestDesignDocument) -> None:
    snapshot = change_set.source_snapshot
    design_fingerprint = fingerprint_design(design)
    if (
        snapshot.get("design_fingerprint") != design_fingerprint
        or change_set.source_fingerprint != design_fingerprint
    ):
        raise _invalid_frozen_proposal("生成设计 Fingerprint 不匹配")
    try:
        contract = OperationContract.model_validate(snapshot.get("contract"))
        policy = GenerationPolicy.model_validate(snapshot.get("generation_policy"))
    except (TypeError, ValueError, ValidationError) as error:
        raise _invalid_frozen_proposal("冻结的 Contract 或生成策略无效") from error
    if fingerprint_contract(contract) != snapshot.get("contract_fingerprint"):
        raise _invalid_frozen_proposal("冻结的 Contract Fingerprint 不匹配")
    if snapshot.get("schema_version") == "s47-test-engineering-proposal-v1":
        return
    try:
        raw_evidence = snapshot.get("additional_evidence")
        if not isinstance(raw_evidence, list):
            raise TypeError("additional_evidence must be a list")
        evidence = [EvidenceBundle.model_validate(item) for item in raw_evidence]
    except (TypeError, ValueError, ValidationError) as error:
        raise _invalid_frozen_proposal("冻结的 Evidence 无效") from error
    evidence_fingerprints = sorted(_evidence_fingerprint(bundle) for bundle in evidence)
    if evidence_fingerprints != snapshot.get("evidence_fingerprints"):
        raise _invalid_frozen_proposal("冻结的 Evidence Fingerprint 不匹配")
    regenerated = TestEngineeringEngine().generate(
        contract=contract,
        policy=policy,
        additional_evidence=evidence,
    )
    if fingerprint_design(regenerated) != design_fingerprint:
        raise _invalid_frozen_proposal("冻结输入无法重现生成设计")


def _invalid_frozen_proposal(message: str) -> AppError:
    return AppError(
        code="TEST_ENGINEERING_PROPOSAL_INVALID",
        message=message,
        status_code=409,
    )


def _validate_change_regression_target(
    *,
    frozen: OperationIdentity,
    definition: APIDefinition,
    api_version: int,
    contract: OperationContract,
) -> None:
    if frozen.api_definition_id != str(definition.id):
        raise _change_regression_target_mismatch()
    if frozen.api_version != api_version:
        raise AppError(
            code="CHANGE_REGRESSION_TARGET_STALE",
            message="目标 API 版本已变化,必须重新审计变更",
            status_code=409,
        )
    identity_service = None if frozen.service_key == "unassigned" else frozen.service_key
    identity_contract = contract.model_copy(update={"service": identity_service})
    compatible_fingerprints = {
        fingerprint_contract(contract),
        fingerprint_contract(identity_contract),
    }
    if frozen.contract_fingerprint not in compatible_fingerprints:
        raise AppError(
            code="CHANGE_REGRESSION_TARGET_STALE",
            message="目标 API Contract Fingerprint 已变化,必须重新审计变更",
            status_code=409,
        )
    actual = (
        contract.service or frozen.service_key,
        contract.method,
        _semantic_operation_path(contract.path),
        contract.operation,
    )
    expected = (
        frozen.service_key,
        frozen.method,
        frozen.normalized_path,
        frozen.portable_operation_ref,
    )
    if actual != expected:
        raise _change_regression_target_mismatch()


def _semantic_operation_path(value: str) -> str:
    parts = value.split("?")
    path = parts[0] or "/"
    while "//" in path:
        path = path.replace("//", "/")
    segments = [
        "{}" if segment.startswith("{") and segment.endswith("}") else segment
        for segment in path.split("/")
    ]
    return "/".join(segments)


def _change_regression_target_mismatch() -> AppError:
    return AppError(
        code="CHANGE_REGRESSION_TARGET_MISMATCH",
        message="所选 API 与冻结的变更 Operation Identity 不一致",
        status_code=409,
    )


def _view(change_set: AIChangeSet, item: AIChangeItem) -> TestEngineeringProposalView:
    design, scenario_ids = _proposal_content(item)
    return TestEngineeringProposalView(change_set, item, design, scenario_ids)
