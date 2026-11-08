"""Read just two declared synthetic body.name fields; never build a full execution DTO."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.self_tests import SelfTestBinding
from app.domain.api_assets import BodyKind
from app.domain.self_tests import document_digest
from app.domain.test_engineering import fingerprint_contract
from app.engine.contracts import ApiNodeConfig, NodeType, WorkflowDefinition, WorkflowPhase
from app.models.api_assets import APIDefinition, APIVersion
from app.models.self_tests import SelfTestBatch, SelfTestScenarioResult
from app.models.workflows import WorkflowExecution, WorkflowNodeExecution, WorkflowVersion
from app.schemas.self_test_evidence import SyntheticNameEvidence, SyntheticNameField
from app.schemas.self_tests import APISourceReference, SourceReference
from app.services.self_test_access import self_test_error
from app.services.test_engineering import TestEngineeringService


class SelfTestSyntheticEvidence:
    def __init__(self, session: AsyncSession, binding: SelfTestBinding) -> None:
        self.session, self.binding = session, binding

    async def _source(self, batch: SelfTestBatch, execution: WorkflowExecution) -> SourceReference:
        row = await self.session.scalar(
            select(SelfTestScenarioResult).where(
                SelfTestScenarioResult.batch_id == batch.id,
                SelfTestScenarioResult.scenario_id == "ST-MCP-023",
                SelfTestScenarioResult.variant_key == "environment_lifecycle",
            )
        )
        if row is None or row.source is None:
            raise self_test_error(
                "SELFTEST_SYNTHETIC_CAPTURE_NOT_DECLARED", "本批未声明生命周期字段采集", 404
            )
        source = SourceReference.model_validate(row.source)
        if (
            execution.workflow_id != source.workflow.id
            or execution.source_case_id != source.case.id
            or execution.source_case_version != source.case.version
            or execution.parent_execution_id is not None
        ):
            raise self_test_error(
                "SELFTEST_SYNTHETIC_CAPTURE_SOURCE_MISMATCH", "执行与已发布生命周期来源不符", 404
            )
        return source

    async def read(self, batch: SelfTestBatch, execution_id: UUID) -> SyntheticNameEvidence:
        execution = await self.session.get(WorkflowExecution, execution_id)
        if execution is None or execution.project_id != batch.project_id:
            raise self_test_error("SELFTEST_EVIDENCE_NOT_IN_BATCH", "执行不属于此批次", 404)
        source = await self._source(batch, execution)
        version = await self.session.get(WorkflowVersion, execution.workflow_version_id)
        if (
            version is None
            or version.workflow_id != source.workflow.id
            or version.version != source.workflow.version
            or version.fingerprint != source.workflow.fingerprint
            or execution.workflow_id is None
            or execution.workflow_version_id is None
            or execution.status not in {"passed", "failed", "cancelled"}
        ):
            raise self_test_error(
                "SELFTEST_SYNTHETIC_CAPTURE_SOURCE_MISMATCH", "执行缺少匹配的固定发布版本", 409
            )
        definition = WorkflowDefinition.model_validate(version.definition)
        fields = tuple(
            [
                await self._field(batch, execution, definition, source, purpose)
                for purpose in ("create", "patch")
            ]
        )
        return SyntheticNameEvidence(
            batch_id=batch.id,
            batch_key=batch.batch_key,
            project_id=batch.project_id,
            execution_id=execution.id,
            workflow_id=execution.workflow_id,
            workflow_version_id=execution.workflow_version_id,
            environment_id=execution.environment_id,
            status=execution.status,
            snapshot_digest=document_digest(execution.snapshot),
            fields=fields,
            observed_at=datetime.now(UTC),
        )

    async def _api(
        self, batch: SelfTestBatch, source: SourceReference, purpose: Literal["create", "patch"]
    ) -> tuple[APISourceReference, APIVersion]:
        base = f"/api/v1/projects/{self.binding.target_project_id}/environments"
        paths = (
            (base,)
            if purpose == "create"
            else (base + "/{{environment_id}}", base + "/{environment_id}")
        )
        method = "POST" if purpose == "create" else "PATCH"
        candidates = []
        for origin in source.api_sources:
            api = await self.session.scalar(
                select(APIVersion)
                .join(APIDefinition)
                .where(
                    APIDefinition.project_id == batch.project_id,
                    APIVersion.api_definition_id == origin.api_definition_id,
                    APIVersion.version == origin.api_version,
                    APIVersion.method == method,
                    APIVersion.path.in_(paths),
                )
            )
            if api is not None:
                contract = await TestEngineeringService(self.session).contract_for_api(
                    project_id=batch.project_id,
                    definition_id=origin.api_definition_id,
                    version_number=origin.api_version,
                )
                if (
                    origin.project_id != batch.project_id
                    or fingerprint_contract(contract) != origin.contract_fingerprint
                ):
                    raise self_test_error(
                        "SELFTEST_SYNTHETIC_CAPTURE_SOURCE_MISMATCH", "字段 API 契约指纹不符"
                    )
                candidates.append((origin, api))
        if len(candidates) != 1:
            raise self_test_error(
                "SELFTEST_SYNTHETIC_CAPTURE_NOT_DECLARED", "仅支持本批精确环境创建和修改 API", 404
            )
        return candidates[0]

    async def _field(
        self,
        batch: SelfTestBatch,
        execution: WorkflowExecution,
        definition: WorkflowDefinition,
        source: SourceReference,
        purpose: Literal["create", "patch"],
    ) -> SyntheticNameField:
        origin, api = await self._api(batch, source, purpose)
        node_id, config = self._api_node(definition, origin)
        body = config.request_overrides.body
        expected = f"{batch.batch_key}-{'created' if purpose == 'create' else 'updated'}"
        if (
            body is None
            or body.kind is not BodyKind.JSON
            or not isinstance(body.value, dict)
            or body.value.get("name") != expected
        ):
            raise self_test_error(
                "SELFTEST_SYNTHETIC_CAPTURE_NOT_DECLARED", "字段不属于本批声明的合成资源名称", 404
            )
        self._snapshot_binding(execution, node_id, origin, api.id)
        node = await self.session.scalar(
            select(WorkflowNodeExecution).where(
                WorkflowNodeExecution.workflow_execution_id == execution.id,
                WorkflowNodeExecution.node_id == node_id,
            )
        )
        value = self._actual_name(node)
        return SyntheticNameField(purpose=purpose, node_id=node_id, api_source=origin, actual=value)

    @staticmethod
    def _api_node(
        definition: WorkflowDefinition, origin: APISourceReference
    ) -> tuple[str, ApiNodeConfig]:
        matches = []
        for node in definition.nodes:
            if node.effective_type is not NodeType.API or node.phase is not WorkflowPhase.MAIN:
                continue
            config = ApiNodeConfig.model_validate(node.config)
            if (config.api_definition_id, config.api_version) == (
                origin.api_definition_id,
                origin.api_version,
            ):
                matches.append((node.id, config))
        if len(matches) != 1:
            raise self_test_error(
                "SELFTEST_SYNTHETIC_CAPTURE_SOURCE_MISMATCH", "字段 API 节点不唯一"
            )
        return matches[0]

    @staticmethod
    def _snapshot_binding(
        execution: WorkflowExecution, node: str, source: APISourceReference, version_id: UUID
    ) -> None:
        apis = execution.snapshot.get("apis")
        api = apis.get(node) if isinstance(apis, dict) else None
        if not isinstance(api, dict) or (
            api.get("definition_id"),
            api.get("version_id"),
            api.get("version"),
        ) != (str(source.api_definition_id), str(version_id), source.api_version):
            raise self_test_error(
                "SELFTEST_SYNTHETIC_CAPTURE_SOURCE_MISMATCH", "执行 API 固定绑定与来源不符"
            )

    @staticmethod
    def _actual_name(node: WorkflowNodeExecution | None) -> str:
        if node is None or (node.node_type, node.phase, node.status, node.attempts) != (
            "api",
            "main",
            "passed",
            1,
        ):
            raise self_test_error(
                "SELFTEST_SYNTHETIC_FIELD_UNAVAILABLE", "合成字段节点未完整成功执行"
            )
        output = node.output
        body = output.get("body") if isinstance(output, dict) else None
        value = body.get("name") if isinstance(body, dict) else None
        if not isinstance(value, str) or not 1 <= len(value) <= 200:
            raise self_test_error(
                "SELFTEST_SYNTHETIC_FIELD_UNAVAILABLE", "合成名称字段缺失或超出上限"
            )
        return value
