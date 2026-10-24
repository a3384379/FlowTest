"""Resolve product self-test references against existing authorized native assets."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.self_tests import SelfTestBinding
from app.domain.self_tests import document_digest, request_upper_bound
from app.domain.test_engineering import fingerprint_contract
from app.engine.contracts import WorkflowDefinition
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.api_assets import Environment
from app.models.artifacts import Artifact
from app.models.self_tests import SelfTestBatch, SelfTestScenarioResult
from app.models.service_targets import Service
from app.models.tasking import TestPlanRunItem
from app.models.workflows import WorkflowExecution
from app.repositories.service_targets import ServiceTargetRepository
from app.repositories.test_assets import TestAssetRepository
from app.repositories.workflows import WorkflowRepository
from app.schemas.self_tests import (
    ArtifactReference,
    ExecutionReference,
    InstallationMapping,
    ResourceSnapshot,
    ScenarioAssets,
    SourceReference,
    TemplateResponse,
)
from app.schemas.test_assets import TestCaseDefinitionInput
from app.services.flow_spec import FlowSpecService
from app.services.self_test_access import self_test_error
from app.services.test_engineering import TestEngineeringService


class SelfTestAssets:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.cases = TestAssetRepository(session)
        self.workflows = WorkflowRepository(session)
        self.targets = ServiceTargetRepository(session)

    async def mapping(
        self,
        project_id: UUID,
        binding: SelfTestBinding,
        template: TemplateResponse,
        mapping: InstallationMapping,
    ) -> None:
        remote = (
            mapping.target_project_id,
            mapping.target_organization_id,
            mapping.target_user_id,
            mapping.target_instance_id,
            mapping.target_build_digest,
        )
        expected = (
            binding.target_project_id,
            binding.target_organization_id,
            binding.target_user_id,
            binding.target_instance_id,
            binding.builds.target,
        )
        if remote != expected:
            raise self_test_error(
                "SELFTEST_REMOTE_MAPPING_MISMATCH", "B 资源命名空间与部署绑定不符"
            )
        for identifier, service_id, url in (
            (mapping.environment_id, mapping.fixture_service_id, binding.fixture_base_url),
            (mapping.target_environment_id, mapping.target_service_id, binding.target_base_url),
        ):
            await self._environment(project_id, identifier, service_id, url)
        for identifier in (mapping.fixture_service_id, mapping.target_service_id):
            service = await self.session.get(Service, identifier)
            if service is None or service.project_id != project_id or not service.enabled:
                raise self_test_error("SELFTEST_SERVICE_MAPPING_INVALID", "服务不属于当前项目")
        if template.batch_kind == "fixed_baseline":
            actual = [(item.scenario_id, item.variant_key) for item in mapping.assets]
            required = [(item.scenario_id, item.variant_key) for item in template.scenarios]
            if sorted(actual) != sorted(required):
                raise self_test_error(
                    "SELFTEST_INSTALLATION_ASSET_SET_MISMATCH", "安装资源必须覆盖完整固定模板"
                )
        await self.assets(project_id, mapping, mapping.assets)

    async def _environment(
        self, project_id: UUID, identifier: UUID, service_id: UUID, url: str
    ) -> None:
        environment = await self.session.scalar(
            select(Environment).where(Environment.id == identifier).with_for_update()
        )
        if (
            environment is None
            or environment.project_id != project_id
            or environment.archived_at is not None
            or environment.classification not in {"test", "sandbox"}
            or environment.base_url.rstrip("/") != url.rstrip("/")
        ):
            raise self_test_error(
                "SELFTEST_ENVIRONMENT_MAPPING_INVALID", "环境归属、目标或分类不符合部署绑定"
            )
        endpoints = await self.targets.list_endpoints(
            project_id=project_id, environment_id=identifier, for_update=True
        )
        route_services = {service_id, environment.default_service_id}
        enabled = [item for item in endpoints if item.enabled and item.service_id in route_services]
        missing = environment.default_service_id is not None and not any(
            item.variant == "default" and item.service_id == environment.default_service_id
            for item in enabled
        )
        if missing or any(item.base_url.rstrip("/") != url.rstrip("/") for item in enabled):
            raise self_test_error(
                "SELFTEST_ENVIRONMENT_MAPPING_INVALID", "Service Endpoint 与本轮部署目标不符"
            )

    async def assets(
        self, project_id: UUID, mapping: InstallationMapping, assets: Sequence[ScenarioAssets]
    ) -> None:
        for asset in assets:
            environment_id = (
                mapping.target_environment_id
                if asset.scenario_id == "ST-MCP-023"
                else mapping.environment_id
            )
            await self._asset(project_id, environment_id, asset)

    async def request_budget(self, assets: Sequence[ScenarioAssets], maximum: int) -> None:
        total = 0
        for asset in assets:
            version = await self.workflows.find_version(asset.workflow.id, asset.workflow.version)
            if version is None:
                raise self_test_error(
                    "SELFTEST_PUBLISHED_VERSION_MISSING", "预算校验缺少流程发布版本"
                )
            bound = request_upper_bound(WorkflowDefinition.model_validate(version.definition))
            if bound is None:
                raise self_test_error(
                    "SELFTEST_REQUEST_BUDGET_UNSUPPORTED", "自测流程必须声明有界请求预算"
                )
            total += bound
        if total > maximum:
            raise self_test_error(
                "SELFTEST_REQUEST_BUDGET_UNSUPPORTED", "发布流程的请求上界超过冻结批次预算"
            )

    async def _asset(self, project_id: UUID, environment_id: UUID, asset: ScenarioAssets) -> None:
        case = await self.cases.get_case(asset.case.id)
        workflow = await self.workflows.get(asset.workflow.id)
        case_version = await self.cases.find_case_version(asset.case.id, asset.case.version)
        workflow_version = await self.workflows.find_version(
            asset.workflow.id, asset.workflow.version
        )
        if (
            case is None
            or workflow is None
            or case.project_id != project_id
            or workflow.project_id != project_id
            or case.archived_at is not None
        ):
            raise self_test_error("SELFTEST_ASSET_NOT_FOUND", "发布资产不存在或不属于当前项目", 404)
        if (
            case_version is None
            or workflow_version is None
            or case_version.fingerprint != asset.case.fingerprint
            or workflow_version.fingerprint != asset.workflow.fingerprint
        ):
            raise self_test_error("SELFTEST_ASSET_VERSION_CHANGED", "发布版本或指纹不匹配")
        expected = (str(asset.workflow.id), asset.workflow.version, str(environment_id))
        actual = tuple(
            case_version.definition.get(key)
            for key in ("workflow_id", "workflow_version", "environment_id")
        )
        if (
            actual != expected
            or case.current_version != asset.case.version
            or workflow.current_version != asset.workflow.version
        ):
            raise self_test_error(
                "SELFTEST_CASE_TARGET_CHANGED", "Case 目标、环境或当前发布版本发生变化"
            )

    async def artifact(self, project_id: UUID, reference: ArtifactReference) -> None:
        artifact = await self.session.get(Artifact, reference.id)
        if (
            artifact is None
            or artifact.project_id != project_id
            or artifact.sha256 != reference.sha256
        ):
            raise self_test_error("SELFTEST_ARTIFACT_INVALID", "证据文件归属或摘要不符")

    async def proposal(
        self, project_id: UUID, reference: object, *, accepted: bool
    ) -> AIChangeItem:
        from app.schemas.self_tests import ProposalReference

        proposal = ProposalReference.model_validate(reference)
        change_set = await self.session.get(AIChangeSet, proposal.change_set_id)
        if (
            change_set is None
            or change_set.project_id != project_id
            or change_set.source_fingerprint != proposal.content_fingerprint
        ):
            raise self_test_error("SELFTEST_PROPOSAL_SOURCE_INVALID", "提案来源或指纹不匹配")
        query = select(AIChangeItem).where(AIChangeItem.change_set_id == change_set.id)
        if proposal.item_id is not None:
            query = query.where(AIChangeItem.id == proposal.item_id)
        else:
            query = query.where(AIChangeItem.item_type == "workflow")
        items = list((await self.session.scalars(query.limit(2))).all())
        if len(items) != 1:
            raise self_test_error("SELFTEST_PROPOSAL_ITEM_INVALID", "提案必须关联唯一真实变更项")
        item = items[0]
        if item.review_status != proposal.review_status or (
            accepted
            and (
                item.review_status != "accepted"
                or item.materialized_resource_id != proposal.materialized_resource_id
            )
        ):
            raise self_test_error("SELFTEST_PROPOSAL_REVIEW_MISMATCH", "审核或物化状态不匹配")
        return item

    async def source(
        self, actor: User, project_id: UUID, mapping: InstallationMapping, source: SourceReference
    ) -> None:
        await self.assets(project_id, mapping, (source,))
        workflow_item = await self.proposal(project_id, source.workflow_proposal, accepted=True)
        case_item = await self.proposal(project_id, source.case_proposal, accepted=True)
        if (
            workflow_item.materialized_resource_id != source.workflow.id
            or case_item.materialized_resource_id != source.case.id
            or workflow_item.item_type != "workflow"
            or case_item.item_type != "test_case"
        ):
            raise self_test_error(
                "SELFTEST_MATERIALIZED_ASSET_MISMATCH", "发布资产不是本提案物化的对象"
            )
        await self._published_definition(actor, project_id, source, case_item)
        await self._oracles(project_id, source)
        await self.artifact(project_id, source.generation_manifest)

    async def _published_definition(
        self, actor: User, project_id: UUID, source: SourceReference, case_item: AIChangeItem
    ) -> None:
        if (
            source.workflow_proposal.route != "flow_spec_visual"
            or source.case_proposal.route != "controlled_write"
        ):
            raise self_test_error("SELFTEST_REVIEW_ROUTE_INVALID", "生成资产必须遵循原有两条审核链")
        visual = await FlowSpecService(self.session).get_visual_proposal(
            actor=actor, project_id=project_id, change_set_id=source.workflow_proposal.change_set_id
        )
        workflow = await self.workflows.find_version(source.workflow.id, source.workflow.version)
        case = await self.cases.find_case_version(source.case.id, source.case.version)
        if workflow is None or case is None:
            raise self_test_error("SELFTEST_PUBLISHED_VERSION_MISSING", "缺少真实发布版本")
        expected_definition = visual.proposed_definition.model_dump(mode="json", exclude_none=True)
        published_definition = WorkflowDefinition.model_validate(workflow.definition).model_dump(
            mode="json", exclude_none=True
        )
        if document_digest(expected_definition) != document_digest(published_definition):
            raise self_test_error(
                "SELFTEST_PUBLISHED_DEFINITION_CHANGED", "已发布流程与审核提案内容不一致"
            )
        definition = TestCaseDefinitionInput.model_validate(
            case_item.proposed_content.get("definition")
        ).model_dump(mode="json", exclude_none=True)
        published_case = TestCaseDefinitionInput.model_validate(case.definition).model_dump(
            mode="json", exclude_none=True
        )
        if document_digest(definition) != document_digest(published_case):
            raise self_test_error(
                "SELFTEST_PUBLISHED_CASE_CHANGED", "已发布 Case 与审核变更项不一致"
            )

    async def _oracles(self, project_id: UUID, source: SourceReference) -> None:
        workflow = await self.workflows.find_version(source.workflow.id, source.workflow.version)
        if workflow is None:
            raise self_test_error("SELFTEST_PUBLISHED_VERSION_MISSING", "流程版本不存在")
        nodes = {node["id"]: node for node in workflow.definition.get("nodes", [])}
        if (
            len({item.oracle_id for item in source.oracle_bindings}) != len(source.oracle_bindings)
            or document_digest([item.model_dump(mode="json") for item in source.oracle_bindings])
            != source.oracle_mapping_digest
        ):
            raise self_test_error("SELFTEST_ORACLE_MAPPING_INVALID", "Oracle 映射重复或摘要不符")
        for oracle in source.oracle_bindings:
            node = nodes.get(oracle.node_id, {})
            config = node.get("config", {})
            if (
                node.get("type") != "assert"
                or config.get("expression") != oracle.expression
                or document_digest(config.get("expected")) != oracle.expected_value_digest
            ):
                raise self_test_error(
                    "SELFTEST_REQUIRED_ORACLE_MISSING", "必要 Oracle 未落实到实际断言"
                )
        if (
            document_digest([item.model_dump(mode="json") for item in source.api_sources])
            != source.api_sources_digest
        ):
            raise self_test_error("SELFTEST_API_SOURCE_DIGEST_INVALID", "API 来源摘要不符")
        actual = {
            (node["config"].get("api_definition_id"), node["config"].get("api_version"))
            for node in nodes.values()
            if node.get("type") == "api"
        }
        expected = {(str(item.api_definition_id), item.api_version) for item in source.api_sources}
        if actual != expected:
            raise self_test_error("SELFTEST_API_SOURCE_SET_CHANGED", "流程使用的 API 版本集合不符")
        for origin in source.api_sources:
            contract = await TestEngineeringService(self.session).contract_for_api(
                project_id=project_id,
                definition_id=origin.api_definition_id,
                version_number=origin.api_version,
            )
            if (
                origin.project_id != project_id
                or fingerprint_contract(contract) != origin.contract_fingerprint
            ):
                raise self_test_error("SELFTEST_API_CONTRACT_CHANGED", "API 契约或项目来源不符")

    async def sync_execution(
        self, batch: SelfTestBatch, row: SelfTestScenarioResult
    ) -> WorkflowExecution | None:
        if row.run_item_id is None:
            return None
        item = await self.session.get(TestPlanRunItem, row.run_item_id)
        if item is None or str(item.test_plan_run_id) not in batch.plan_run_ids:
            raise self_test_error("SELFTEST_RUN_ITEM_MISSING", "原生运行关联已缺失")
        snapshot = ResourceSnapshot.model_validate(batch.resource_snapshot)
        frozen = next(
            (
                case
                for case in snapshot.cases
                if (case.scenario_id, case.variant_key) == (row.scenario_id, row.variant_key)
            ),
            None,
        )
        if frozen is None or (
            item.target_id,
            item.target_version,
            document_digest(item.target_snapshot),
        ) != (
            frozen.case.id,
            frozen.case.version,
            frozen.target_snapshot_digest,
        ):
            raise self_test_error(
                "SELFTEST_EXECUTION_SNAPSHOT_MISMATCH", "原生 Case 或目标快照不符合执行前冻结内容"
            )
        row.observed_status = item.status
        row.execution_id = item.workflow_execution_id
        row.execution_refs = [
            ExecutionReference(
                test_plan_run_id=item.test_plan_run_id,
                run_item_id=item.id,
                execution_id=item.workflow_execution_id,
                target_version=item.target_version,
                target_snapshot_digest=document_digest(item.target_snapshot),
            ).model_dump(mode="json")
        ]
        execution = (
            None
            if item.workflow_execution_id is None
            else await self.session.get(WorkflowExecution, item.workflow_execution_id)
        )
        if execution is not None and (
            execution.project_id != batch.project_id
            or execution.source_plan_run_item_id != item.id
            or execution.run_purpose != "standard"
        ):
            raise self_test_error("SELFTEST_EXECUTION_SOURCE_MISMATCH", "执行不是本批正式原生运行")
        return execution
