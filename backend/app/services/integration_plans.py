"""Read-only orchestration for evidence-backed Integration Plan generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.data_nodes import CredentialKind
from app.domain.integration_plans import (
    IntegrationPlan,
    IntegrationPlannerRequest,
    PlanActor,
    PlanCleanupRequirement,
    PlanDatabaseRead,
    PlanDataRecipe,
    PlanOracle,
    PlanPrecondition,
    PlanTargetEnvironment,
    ReusableAuthSubflowEvidence,
    SelectedOperationEvidence,
    build_integration_plan,
)
from app.domain.test_design import ScenarioCandidate, TestDesignDocument
from app.domain.test_engineering import (
    GenerationPolicy,
    TestEngineeringEngine,
    fingerprint_contract,
)
from app.engine.contracts import NodeType, WorkflowDefinition
from app.models.access import User
from app.models.api_assets import APIDefinition
from app.repositories.api_assets import APIAssetRepository
from app.repositories.artifacts import ArtifactRepository
from app.repositories.data_sources import DataSourceRepository
from app.repositories.service_targets import ServiceTargetRepository
from app.repositories.workflows import WorkflowRepository
from app.services.projects import ProjectService
from app.services.test_engineering import TestEngineeringService

_SECRET_TEMPLATE = re.compile(r"\{\{secret\.([A-Za-z0-9_.-]{1,160})\}\}")


@dataclass(frozen=True, slots=True)
class OperationPlanSelection:
    definition_id: UUID
    scenario_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExistingAuthWorkflowSelection:
    workflow_id: UUID
    workflow_version: int
    token_path: str
    step_id: str = "existing-auth"


@dataclass(frozen=True, slots=True)
class IntegrationPlanAssetCommand:
    context_revision_id: UUID
    context_fingerprint: str
    objective: str
    actors: tuple[PlanActor, ...]
    preconditions: tuple[PlanPrecondition, ...]
    target_environment: PlanTargetEnvironment
    operations: tuple[OperationPlanSelection, ...]
    existing_auth: ExistingAuthWorkflowSelection | None = None
    data_recipes: tuple[PlanDataRecipe, ...] = ()
    database_reads: tuple[PlanDatabaseRead, ...] = ()
    additional_oracles: tuple[PlanOracle, ...] = ()
    cleanup_requirements: tuple[PlanCleanupRequirement, ...] = ()


class IntegrationPlanAssetService:
    """Resolve current project assets, then delegate all judgment to the pure planner."""

    def __init__(self, session: AsyncSession) -> None:
        self._projects = ProjectService(session)
        self._assets = APIAssetRepository(session)
        self._artifacts = ArtifactRepository(session)
        self._data_sources = DataSourceRepository(session)
        self._targets = ServiceTargetRepository(session)
        self._workflows = WorkflowRepository(session)
        self._test_engineering = TestEngineeringService(session)

    async def build(
        self,
        *,
        actor: User,
        project_id: UUID,
        command: IntegrationPlanAssetCommand,
    ) -> IntegrationPlan:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        if not command.operations:
            raise AppError(
                code="INTEGRATION_PLAN_OPERATION_REQUIRED",
                message="至少需要一个用户明确选择的 API Operation",
                status_code=422,
            )
        selected: list[SelectedOperationEvidence] = []
        for operation in command.operations:
            selected.append(
                await self._selected_operation(
                    project_id=project_id,
                    selection=operation,
                )
            )
        reusable_auth = await self._reusable_auth(
            project_id=project_id,
            selection=command.existing_auth,
        )
        await self._validate_data_assets(
            project_id=project_id,
            data_recipes=command.data_recipes,
            database_reads=command.database_reads,
        )
        return build_integration_plan(
            IntegrationPlannerRequest(
                context_revision_id=command.context_revision_id,
                context_fingerprint=command.context_fingerprint,
                objective=command.objective,
                actors=list(command.actors),
                preconditions=list(command.preconditions),
                target_environment=command.target_environment,
                selected_operations=selected,
                reusable_auth_subflow=reusable_auth,
                data_recipes=list(command.data_recipes),
                database_reads=list(command.database_reads),
                additional_oracles=list(command.additional_oracles),
                cleanup_requirements=list(command.cleanup_requirements),
            )
        )

    async def _validate_data_assets(
        self,
        *,
        project_id: UUID,
        data_recipes: tuple[PlanDataRecipe, ...],
        database_reads: tuple[PlanDatabaseRead, ...],
    ) -> None:
        for recipe in data_recipes:
            if recipe.artifact_id is None:
                continue
            artifact = await self._artifacts.get(recipe.artifact_id)
            if artifact is None or artifact.project_id != project_id:
                raise AppError(
                    code="DATA_RECIPE_ARTIFACT_NOT_FOUND",
                    message="Data Recipe 引用的数据集不存在",
                    status_code=422,
                )
        for database_read in database_reads:
            credential = await self._data_sources.get_credential(database_read.credential_id)
            expected_kind = CredentialKind(database_read.dialect)
            if (
                credential is None
                or credential.project_id != project_id
                or credential.kind != expected_kind.value
            ):
                raise AppError(
                    code="DATABASE_READ_CREDENTIAL_NOT_FOUND",
                    message="DB Read 引用的只读数据库 Credential 不存在或类型不匹配",
                    status_code=422,
                )

    async def _selected_operation(
        self,
        *,
        project_id: UUID,
        selection: OperationPlanSelection,
    ) -> SelectedOperationEvidence:
        definition = await self._definition(project_id, selection.definition_id)
        version = await self._assets.get_version(
            definition_id=definition.id,
            version=definition.current_version,
        )
        if version is None:
            raise AppError(
                code="API_VERSION_NOT_FOUND",
                message="用户选择的 API Version 不存在",
                status_code=404,
            )
        contract = await self._test_engineering.contract_for_api(
            project_id=project_id,
            definition_id=definition.id,
            version_number=version.version,
        )
        if (
            version.contract_fingerprint is None
            or fingerprint_contract(contract) != version.contract_fingerprint
        ):
            raise AppError(
                code="API_CONTRACT_FINGERPRINT_MISMATCH",
                message="API Version 的 Canonical Contract Fingerprint 不一致",
                status_code=409,
            )
        design = TestEngineeringEngine().generate(
            contract=contract,
            policy=GenerationPolicy(
                max_scenarios=50,
                include_negative=False,
                include_auth=True,
                include_state=False,
            ),
        )
        scenario = _select_local_scenario(design, selection.scenario_id)
        service_ref, service_name = await self._service_identity(
            project_id,
            version.service_id,
            contract.service,
        )
        source_ref = f"api-definition://{definition.id}/version/{version.version}"
        evidence_refs = sorted(
            set(
                [
                    source_ref,
                    *(reference.source_ref for reference in design.evidence_refs),
                    *scenario.evidence_refs,
                ]
            )
        )
        oracles = [
            oracle
            for oracle in design.oracles
            if oracle.deterministic
            and not oracle.requires_review
            and (not oracle.applies_to or scenario.id in oracle.applies_to)
        ]
        return SelectedOperationEvidence(
            operation_ref=contract.operation,
            service_ref=service_ref,
            service_name=service_name,
            source_version=version.version,
            contract=contract,
            scenario=scenario,
            oracles=oracles,
            credential_refs=_credential_refs(version.auth_config),
            selected_by_user=True,
            evidence_refs=evidence_refs,
        )

    async def _definition(self, project_id: UUID, definition_id: UUID) -> APIDefinition:
        definition = await self._assets.get_definition(definition_id)
        if definition is None or definition.project_id != project_id or not definition.is_active:
            raise AppError(
                code="API_DEFINITION_NOT_FOUND",
                message="用户选择的 API 定义不存在",
                status_code=404,
            )
        return definition

    async def _service_identity(
        self,
        project_id: UUID,
        service_id: UUID | None,
        contract_service: str | None,
    ) -> tuple[str | None, str]:
        if service_id is not None:
            service = await self._targets.get_service(service_id)
        elif contract_service is not None:
            service = await self._targets.find_service_by_key(
                project_id=project_id,
                service_key=contract_service,
            )
        else:
            return None, "Default HTTP Service"
        if service is None or service.project_id != project_id or not service.enabled:
            raise AppError(
                code="SERVICE_NOT_FOUND",
                message="用户选择的 API 关联 Service 不存在或已停用",
                status_code=404,
            )
        return service.service_key, service.name

    async def _reusable_auth(
        self,
        *,
        project_id: UUID,
        selection: ExistingAuthWorkflowSelection | None,
    ) -> ReusableAuthSubflowEvidence | None:
        if selection is None:
            return None
        workflow = await self._workflows.get(selection.workflow_id)
        if workflow is None or workflow.project_id != project_id:
            raise AppError(
                code="WORKFLOW_NOT_FOUND",
                message="Existing Auth Workflow 不存在",
                status_code=404,
            )
        version = await self._workflows.find_version(
            selection.workflow_id,
            selection.workflow_version,
        )
        if version is None:
            raise AppError(
                code="WORKFLOW_VERSION_NOT_FOUND",
                message="Existing Auth Workflow Version 不存在",
                status_code=404,
            )
        try:
            definition = WorkflowDefinition.model_validate(version.definition)
        except (TypeError, ValueError, ValidationError) as error:
            raise AppError(
                code="INVALID_WORKFLOW_DEFINITION",
                message="Existing Auth Workflow Definition 无法解析",
                status_code=409,
            ) from error
        if not any(
            node.effective_type in {NodeType.API, NodeType.SUBFLOW} for node in definition.nodes
        ):
            raise AppError(
                code="AUTH_SUBFLOW_EVIDENCE_MISSING",
                message="Existing Workflow 没有可复用的 Auth/API/SubFlow Evidence",
                status_code=422,
            )
        evidence_ref = (
            f"workflow://{workflow.id}/version/{version.version}?fingerprint={version.fingerprint}"
        )
        return ReusableAuthSubflowEvidence(
            step_id=selection.step_id,
            name=workflow.name,
            workflow_id=workflow.id,
            workflow_version=version.version,
            token_path=selection.token_path,
            evidence_refs=[evidence_ref],
            confidence=1,
        )


def _select_local_scenario(
    design: TestDesignDocument,
    requested_id: str | None,
) -> ScenarioCandidate:
    candidates = [
        scenario
        for scenario in design.scenarios
        if scenario.expected_category == "success"
        and scenario.deterministic
        and not scenario.requires_review
    ]
    if requested_id is not None:
        candidates = [scenario for scenario in candidates if scenario.id == requested_id]
    if not candidates:
        raise AppError(
            code="INTEGRATION_PLAN_SCENARIO_EVIDENCE_MISSING",
            message="所选 Operation 没有可复用的确定性成功 Scenario",
            status_code=422,
        )
    return sorted(candidates, key=lambda item: item.id)[0]


def _credential_refs(auth_config: dict[str, str]) -> list[str]:
    return sorted(
        {
            f"secret://{name}"
            for value in auth_config.values()
            for name in _SECRET_TEMPLATE.findall(value)
        }
    )
