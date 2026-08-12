import hashlib
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.contracts import ContractSchemaError
from app.domain.impact import (
    AssetMapping,
    ChangeItem,
    ImpactInputError,
    SourceKind,
    TargetType,
    build_impact_evidence,
    changes_fingerprint,
    diff_graphql,
    diff_grpc,
    diff_openapi,
    parse_git_diff,
    validate_selector,
)
from app.models.access import User
from app.models.contracts import ContractRun, PactContractVersion
from app.models.impact import CoverageSnapshot, ImpactAssetMapping, ImpactRun, TestSelection
from app.models.performance import PerformanceScenario
from app.models.protocols import SchemaArtifact
from app.models.test_assets import TestCase
from app.models.workflows import Workflow
from app.repositories.impact import ImpactRepository, ImpactRunBundle
from app.schemas.impact import ImpactRunCreate, OpenApiDiffReference, SchemaDiffReference
from app.services.audit import AuditService
from app.services.projects import ProjectService


@dataclass(frozen=True, slots=True)
class ImpactTargetView:
    id: UUID
    target_type: TargetType
    name: str
    version: str | int | None


@dataclass(frozen=True, slots=True)
class ImpactMappingView:
    model: ImpactAssetMapping
    target: ImpactTargetView


@dataclass(frozen=True, slots=True)
class ImpactCatalogView:
    targets: tuple[ImpactTargetView, ...]
    schemas: tuple[SchemaArtifact, ...]


class ImpactService:
    def __init__(self, session: AsyncSession, *, enabled: bool) -> None:
        self._session = session
        self._enabled = enabled
        self._repository = ImpactRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def create_mapping(
        self,
        *,
        actor: User,
        project_id: UUID,
        source_kind: str,
        source_selector: str,
        target_type: str,
        target_id: UUID,
    ) -> ImpactMappingView:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        try:
            kind = SourceKind(source_kind)
            target_kind = TargetType(target_type)
            selector = validate_selector(source_selector)
        except (ValueError, ImpactInputError) as error:
            raise AppError(
                code="IMPACT_MAPPING_INVALID", message=str(error), status_code=422
            ) from error
        target = await self._resolve_target(
            project_id=project_id, target_type=target_kind, target_id=target_id
        )
        mapping_key = _mapping_key(kind, selector, target_kind, target_id)
        if await self._repository.find_mapping_by_key(
            project_id=project_id, mapping_key=mapping_key
        ):
            raise AppError(
                code="IMPACT_MAPPING_EXISTS", message="影响资产映射已存在", status_code=409
            )
        model = ImpactAssetMapping(
            project_id=project_id,
            source_kind=kind.value,
            source_selector=selector,
            target_type=target_kind.value,
            mapping_key=mapping_key,
            created_by_id=actor.id,
            **_target_columns(target_kind, target_id),
        )
        self._repository.add_mapping(model)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="impact.mapping_created",
            resource_type="impact_asset_mapping",
            resource_id=model.id,
            details={
                "source_kind": kind.value,
                "target_type": target_kind.value,
                "target_id": str(target_id),
            },
        )
        await self._session.commit()
        await self._session.refresh(model)
        return ImpactMappingView(model, target)

    async def list_mappings(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[ImpactMappingView], int]:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        models, total = await self._repository.list_mappings(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return [await self._mapping_view(project_id, model) for model in models], total

    async def delete_mapping(self, *, actor: User, project_id: UUID, mapping_id: UUID) -> None:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        model = await self._repository.get_mapping(mapping_id)
        if model is None or model.project_id != project_id:
            raise AppError(
                code="IMPACT_MAPPING_NOT_FOUND", message="影响资产映射不存在", status_code=404
            )
        await self._repository.delete_mapping(model)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="impact.mapping_deleted",
            resource_type="impact_asset_mapping",
            resource_id=mapping_id,
        )
        await self._session.commit()

    async def catalog(self, *, actor: User, project_id: UUID) -> ImpactCatalogView:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        targets: list[ImpactTargetView] = []
        targets.extend(
            _test_case_target(item)
            for item in await self._repository.catalog_test_cases(project_id=project_id)
        )
        targets.extend(
            _workflow_target(item)
            for item in await self._repository.catalog_workflows(project_id=project_id)
        )
        targets.extend(
            _openapi_target(item)
            for item in await self._repository.catalog_openapi_contracts(project_id=project_id)
        )
        targets.extend(
            _pact_target(item)
            for item in await self._repository.catalog_pact_contracts(project_id=project_id)
        )
        targets.extend(
            _performance_target(item)
            for item in await self._repository.catalog_performance(project_id=project_id)
        )
        schemas = await self._repository.catalog_schemas(project_id=project_id)
        return ImpactCatalogView(tuple(targets), tuple(schemas))

    async def create_run(
        self, *, actor: User, project_id: UUID, payload: ImpactRunCreate
    ) -> ImpactRunBundle:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        changes, source_summary = await self._collect_changes(project_id, payload)
        if not changes:
            raise AppError(
                code="IMPACT_NO_CHANGES",
                message="所选基线与当前版本没有可分析的变更",
                status_code=422,
            )
        mapping_models, _ = await self._repository.list_mappings(project_id=project_id)
        mappings: list[AssetMapping] = []
        for model in mapping_models:
            mappings.append(await self._domain_mapping(project_id=project_id, model=model))
        try:
            evidence = build_impact_evidence(changes, tuple(mappings))
        except ImpactInputError as error:
            raise AppError(
                code="IMPACT_INPUT_INVALID", message=str(error), status_code=422
            ) from error
        run = ImpactRun(
            project_id=project_id,
            title=payload.title.strip(),
            source_ref=payload.source_ref.strip(),
            status="completed",
            source_fingerprint=changes_fingerprint(changes),
            source_summary=source_summary,
            change_count=len(changes),
            changes=[item.as_json() for item in changes],
            graph=evidence.graph,
            summary=evidence.summary,
            created_by_id=actor.id,
        )
        self._repository.add_run(run)
        await self._session.flush()
        selection = TestSelection(
            project_id=project_id,
            impact_run_id=run.id,
            strategy="explicit_mapping_v1",
            selected_assets=list(evidence.selected_assets),
            explanations=list(evidence.matrix),
            created_by_id=actor.id,
        )
        covered = int(cast(int, evidence.summary["covered_change_count"]))
        coverage = CoverageSnapshot(
            project_id=project_id,
            impact_run_id=run.id,
            total_changes=len(changes),
            covered_changes=covered,
            coverage_percent=float(cast(float, evidence.summary["coverage_percent"])),
            matrix=list(evidence.matrix),
            gaps=list(evidence.gaps),
            created_by_id=actor.id,
        )
        self._repository.add_run_evidence(selection=selection, coverage=coverage)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="impact.run_created",
            resource_type="impact_run",
            resource_id=run.id,
            details={
                "change_count": len(changes),
                "selected_asset_count": evidence.summary["selected_asset_count"],
                "coverage_percent": evidence.summary["coverage_percent"],
                "source_kinds": sorted({item.source_kind.value for item in changes}),
            },
        )
        await self._session.commit()
        bundle = await self._repository.get_run_bundle(run.id)
        if bundle is None:
            raise AppError(
                code="IMPACT_RUN_PERSISTENCE_FAILED",
                message="影响分析结果保存失败",
                status_code=500,
            )
        return bundle

    async def list_runs(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[ImpactRun], int]:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_runs(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def get_run(self, *, actor: User, project_id: UUID, run_id: UUID) -> ImpactRunBundle:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        bundle = await self._repository.get_run_bundle(run_id)
        if bundle is None or bundle.run.project_id != project_id:
            raise AppError(code="IMPACT_RUN_NOT_FOUND", message="影响分析不存在", status_code=404)
        return bundle

    async def _collect_changes(
        self, project_id: UUID, payload: ImpactRunCreate
    ) -> tuple[tuple[ChangeItem, ...], dict[str, JsonValue]]:
        changes: dict[str, ChangeItem] = {}
        summary: dict[str, JsonValue] = {
            "git": None,
            "openapi": [],
            "schemas": [],
        }
        try:
            if payload.git_diff:
                git_changes = parse_git_diff(payload.git_diff)
                changes.update((item.key, item) for item in git_changes)
                summary["git"] = {
                    "source_ref": payload.source_ref.strip(),
                    "file_count": len(git_changes),
                    "content_sha256": hashlib.sha256(payload.git_diff.encode()).hexdigest(),
                }
            openapi_summaries = []
            for reference in payload.openapi_diffs:
                current_changes, item_summary = await self._openapi_changes(project_id, reference)
                changes.update((item.key, item) for item in current_changes)
                openapi_summaries.append(item_summary)
            summary["openapi"] = cast(JsonValue, openapi_summaries)
            schema_summaries = []
            for schema_reference in payload.schema_diffs:
                current_changes, item_summary = await self._schema_changes(
                    project_id, schema_reference
                )
                changes.update((item.key, item) for item in current_changes)
                schema_summaries.append(item_summary)
            summary["schemas"] = cast(JsonValue, schema_summaries)
        except (ImpactInputError, ContractSchemaError) as error:
            raise AppError(
                code="IMPACT_INPUT_INVALID", message=str(error), status_code=422
            ) from error
        if len(changes) > 5_000:
            raise AppError(
                code="IMPACT_INPUT_INVALID", message="变更项超过 5000 上限", status_code=422
            )
        return tuple(changes.values()), summary

    async def _openapi_changes(
        self, project_id: UUID, reference: OpenApiDiffReference
    ) -> tuple[tuple[ChangeItem, ...], dict[str, JsonValue]]:
        baseline = await self._repository.get_contract_run(reference.baseline_run_id)
        current = await self._repository.get_contract_run(reference.current_run_id)
        if (
            baseline is None
            or current is None
            or baseline.project_id != project_id
            or current.project_id != project_id
        ):
            raise AppError(
                code="IMPACT_OPENAPI_REFERENCE_INVALID",
                message="OpenAPI 基线或当前版本不存在于该项目",
                status_code=422,
            )
        changes = diff_openapi(
            cast(dict[str, JsonValue], baseline.schema_document),
            cast(dict[str, JsonValue], current.schema_document),
        )
        return changes, {
            "baseline_run_id": str(baseline.id),
            "current_run_id": str(current.id),
            "source_name": current.source_name,
            "change_count": len(changes),
        }

    async def _schema_changes(
        self, project_id: UUID, reference: SchemaDiffReference
    ) -> tuple[tuple[ChangeItem, ...], dict[str, JsonValue]]:
        baseline = await self._repository.get_schema_artifact(reference.baseline_artifact_id)
        current = await self._repository.get_schema_artifact(reference.current_artifact_id)
        if (
            baseline is None
            or current is None
            or baseline.project_id != project_id
            or current.project_id != project_id
            or baseline.protocol != current.protocol
            or baseline.protocol not in {"graphql", "grpc"}
        ):
            raise AppError(
                code="IMPACT_SCHEMA_REFERENCE_INVALID",
                message="Schema 基线与当前版本必须属于同一项目和协议",
                status_code=422,
            )
        changes = (
            diff_graphql(baseline.canonical_content, current.canonical_content)
            if current.protocol == "graphql"
            else diff_grpc(baseline.canonical_content, current.canonical_content)
        )
        return changes, {
            "protocol": current.protocol,
            "baseline_artifact_id": str(baseline.id),
            "current_artifact_id": str(current.id),
            "name": current.name,
            "change_count": len(changes),
        }

    async def _mapping_view(self, project_id: UUID, model: ImpactAssetMapping) -> ImpactMappingView:
        target_type = TargetType(model.target_type)
        target_id = _mapping_target_id(model, target_type)
        target = await self._resolve_target(
            project_id=project_id, target_type=target_type, target_id=target_id
        )
        return ImpactMappingView(model, target)

    async def _domain_mapping(self, *, project_id: UUID, model: ImpactAssetMapping) -> AssetMapping:
        view = await self._mapping_view(project_id, model)
        return AssetMapping(
            mapping_id=str(model.id),
            source_kind=SourceKind(model.source_kind),
            selector=model.source_selector,
            target_type=view.target.target_type,
            target_id=str(view.target.id),
            target_name=view.target.name,
            target_version=view.target.version,
        )

    async def _resolve_target(
        self, *, project_id: UUID, target_type: TargetType, target_id: UUID
    ) -> ImpactTargetView:
        target_project_id: UUID | None
        if target_type == TargetType.TEST_CASE:
            test_case = await self._repository.get_test_case(target_id)
            target_project_id = test_case.project_id if test_case else None
            view = _test_case_target(test_case) if test_case else None
        elif target_type == TargetType.WORKFLOW:
            workflow = await self._repository.get_workflow(target_id)
            target_project_id = workflow.project_id if workflow else None
            view = _workflow_target(workflow) if workflow else None
        elif target_type == TargetType.OPENAPI_CONTRACT:
            contract = await self._repository.get_contract_run(target_id)
            target_project_id = contract.project_id if contract else None
            view = _openapi_target(contract) if contract else None
        elif target_type == TargetType.PACT_CONTRACT:
            pact = await self._repository.get_pact(target_id)
            target_project_id = pact.project_id if pact else None
            view = _pact_target(pact) if pact else None
        else:
            performance = await self._repository.get_performance_scenario(target_id)
            target_project_id = performance.project_id if performance else None
            view = _performance_target(performance) if performance else None
        if view is None or target_project_id != project_id:
            raise AppError(
                code="IMPACT_TARGET_NOT_FOUND",
                message="映射目标资产不存在于该项目",
                status_code=422,
            )
        return view

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise AppError(
                code="IMPACT_ENGINE_DISABLED", message="影响分析能力尚未启用", status_code=409
            )


def _mapping_key(
    source_kind: SourceKind,
    selector: str,
    target_type: TargetType,
    target_id: UUID,
) -> str:
    return hashlib.sha256(
        f"{source_kind.value}|{selector}|{target_type.value}|{target_id}".encode()
    ).hexdigest()


def _target_columns(target_type: TargetType, target_id: UUID) -> dict[str, UUID | None]:
    columns: dict[str, UUID | None] = {
        "test_case_id": None,
        "workflow_id": None,
        "contract_run_id": None,
        "pact_contract_version_id": None,
        "performance_scenario_id": None,
    }
    columns[
        {
            TargetType.TEST_CASE: "test_case_id",
            TargetType.WORKFLOW: "workflow_id",
            TargetType.OPENAPI_CONTRACT: "contract_run_id",
            TargetType.PACT_CONTRACT: "pact_contract_version_id",
            TargetType.PERFORMANCE: "performance_scenario_id",
        }[target_type]
    ] = target_id
    return columns


def _mapping_target_id(model: ImpactAssetMapping, target_type: TargetType) -> UUID:
    value = {
        TargetType.TEST_CASE: model.test_case_id,
        TargetType.WORKFLOW: model.workflow_id,
        TargetType.OPENAPI_CONTRACT: model.contract_run_id,
        TargetType.PACT_CONTRACT: model.pact_contract_version_id,
        TargetType.PERFORMANCE: model.performance_scenario_id,
    }[target_type]
    if value is None:
        raise AppError(
            code="IMPACT_MAPPING_CORRUPT", message="影响资产映射引用无效", status_code=500
        )
    return value


def _test_case_target(model: TestCase) -> ImpactTargetView:
    return ImpactTargetView(model.id, TargetType.TEST_CASE, model.name, model.current_version)


def _workflow_target(model: Workflow) -> ImpactTargetView:
    return ImpactTargetView(model.id, TargetType.WORKFLOW, model.name, model.current_version)


def _openapi_target(model: ContractRun) -> ImpactTargetView:
    version = model.provider_version or model.source_sha256[:12]
    return ImpactTargetView(model.id, TargetType.OPENAPI_CONTRACT, model.source_name, version)


def _pact_target(model: PactContractVersion) -> ImpactTargetView:
    return ImpactTargetView(
        model.id,
        TargetType.PACT_CONTRACT,
        model.source_name,
        model.consumer_version,
    )


def _performance_target(model: PerformanceScenario) -> ImpactTargetView:
    return ImpactTargetView(model.id, TargetType.PERFORMANCE, model.name, model.version)
