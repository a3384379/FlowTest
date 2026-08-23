from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.test_design import (
    ScenarioCandidate,
    TestDesignDocument,
    fingerprint_design,
    normalized_design,
)
from app.domain.test_engineering import TestEngineeringEngine
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
            contract=contract, policy=payload.generation_policy
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
                "schema_version": "s47-test-engineering-proposal-v1",
                "api_definition_id": str(definition.id),
                "api_version": api_version,
                "environment_id": str(payload.environment_id),
                "endpoint_variant": endpoint_variant,
                "scenario_ids": scenario_ids,
                "design_fingerprint": fingerprint,
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
    ) -> TestEngineeringMaterialization:
        await self._ensure_unique_design(project_id, title)
        workflow_ids: list[UUID] = []
        test_case_ids: list[UUID] = []
        for scenario in scenarios:
            expected_status = _expected_status(design, scenario)
            workflow = await WorkflowService(self._session).create(
                actor=actor,
                project_id=project_id,
                name=_asset_name(title, scenario, "Workflow"),
                description=f"由 Test Engineering Proposal {change_set.id} 生成",
                folder_id=None,
                definition=_scenario_workflow(
                    definition.id, scenario, expected_status, endpoint_variant
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
        if change_set is None or change_set.source_snapshot.get("schema_version") != (
            "s47-test-engineering-proposal-v1"
        ):
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
        unsupported = sorted(
            scenario.id
            for scenario in design.scenarios
            if scenario.id in requested and scenario.kind == "auth_missing"
        )
        if unsupported:
            raise AppError(
                code="TEST_ENGINEERING_SCENARIO_NOT_MATERIALIZABLE",
                message=(
                    "auth_missing Scenario 尚无法安全物化: 现有 Workflow API 节点"
                    "不支持显式禁用定义级认证"
                ),
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
    ]
    if len(matches) != 1:
        raise AppError(
            code="TEST_ENGINEERING_ORACLE_NOT_EXECUTABLE",
            message=f"Scenario {scenario.id} 缺少唯一的确定性状态码 Oracle",
            status_code=422,
        )
    return cast(int, matches[0].expected)


def _scenario_workflow(
    api_definition_id: UUID,
    scenario: ScenarioCandidate,
    expected_status: int,
    endpoint_variant: str | None,
) -> WorkflowDefinition:
    request_config: dict[str, Any] = {
        "api_definition_id": str(api_definition_id),
        "expected_statuses": [expected_status],
        "request_overrides": {"body": {"kind": "json", "value": scenario.request_body}},
    }
    if endpoint_variant is not None:
        request_config["endpoint_variant"] = endpoint_variant
    return WorkflowDefinition.model_validate(
        {
            "schema_version": "1.0",
            "variables": {},
            "nodes": [
                _workflow_node("start", "start", "Start", 0, {}),
                _workflow_node(
                    "request",
                    "api",
                    scenario.title,
                    200,
                    request_config,
                ),
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
                _workflow_node("end", "end", "End", 600, {}),
            ],
            "edges": [
                {"id": "start-request", "source": "start", "target": "request"},
                {"id": "request-assert", "source": "request", "target": "assert_status"},
                {"id": "assert-end", "source": "assert_status", "target": "end"},
            ],
            "settings": {},
        }
    )


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
    test_case_ids: list[UUID],
) -> TestDesign:
    payload = design.model_dump(mode="json")
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
        warnings=list(design.warnings),
        confidence=design.confidence,
        review_requirements=list(design.review_requirements),
        test_case_refs=[f"testcase://{value}" for value in test_case_ids],
        fingerprint=fingerprint_design(design),
        source_change_set_id=change_set.id,
        created_by_id=actor.id,
        reviewed_by_id=actor.id,
        reviewed_at=datetime.now(UTC),
    )


def _asset_name(title: str, scenario: ScenarioCandidate, suffix: str) -> str:
    prefix = f"{title} - {scenario.kind} - {suffix}"
    return f"{prefix[:190]}-{scenario.id[-8:]}"[:200]


def _view(change_set: AIChangeSet, item: AIChangeItem) -> TestEngineeringProposalView:
    design, scenario_ids = _proposal_content(item)
    return TestEngineeringProposalView(change_set, item, design, scenario_ids)
