"""Validate explicitly reviewed revisions without rewriting model-origin evidence."""

from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.self_tests import SelfTestSettings
from app.domain.assisted_revisions import RevisionDifferenceLimit, revision_differences
from app.domain.self_tests import aware, document_digest
from app.engine.contracts import WorkflowDefinition
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.self_tests import SelfTestBatch, SelfTestScenarioResult
from app.repositories.test_assets import TestAssetRepository
from app.repositories.workflows import WorkflowRepository
from app.schemas.self_tests import (
    ArtifactReference,
    AssistedBeforeSource,
    BuildIdentity,
    FrozenBatchManifest,
    RevisionDifference,
    SourceReference,
    TemplateScenario,
)
from app.schemas.test_assets import PublishedTestCaseDefinition
from app.services.self_test_access import self_test_error
from app.services.self_test_views import SelfTestViews


class SelfTestAssistedSources:
    def __init__(self, session: AsyncSession, config: SelfTestSettings) -> None:
        self.session, self.views = session, SelfTestViews(session, config)
        self.workflows, self.cases = WorkflowRepository(session), TestAssetRepository(session)
        self.available: dict[UUID, SelfTestBatch] = {}

    async def validate(self, batch: SelfTestBatch, source: SourceReference) -> None:
        manifest = FrozenBatchManifest.model_validate(batch.frozen_manifest)
        if (
            None if source.assisted is None else source.assisted.before_batch_id
        ) != manifest.assisted_before_batch_id:
            raise self_test_error(
                "SELFTEST_ASSISTED_TASK_MISMATCH", "辅助来源必须属于当前冻结修订任务"
            )
        if source.assisted is None:
            if source.fixture_batch_key not in {None, batch.batch_key}:
                raise self_test_error(
                    "SELFTEST_ASSISTED_FIXTURE_SCOPE_INVALID", "普通生成不能借用其他批次路径"
                )
            return
        if batch.generation_mode != "host_llm_mcp":
            raise self_test_error("SELFTEST_ASSISTED_MODE_INVALID", "辅助修订必须保留真实宿主来源")
        _before_batch, before, origin = await self._context(batch, source)
        self._preserved(source, before, origin)
        await self._actors(batch, source)
        await self._difference(source, before)
        self._fixture(source, origin)

    async def _before(self, project: UUID, identifier: UUID) -> SelfTestBatch:
        if identifier in self.available:
            return self.available[identifier]
        model = await self.session.get(SelfTestBatch, identifier)
        if model is None or model.project_id != project:
            raise self_test_error("SELFTEST_ASSISTED_BEFORE_NOT_FOUND", "原批次不存在或跨项目", 404)
        if (
            model.sealed_at is None
            or model.resource_digest is None
            or model.generation_mode != "host_llm_mcp"
            or model.verdict not in {"passed", "failed", "blocked"}
        ):
            raise self_test_error("SELFTEST_ASSISTED_BEFORE_NOT_SEALED", "原宿主批次尚未完整封存")
        view = await self.views.batch(model, editing=False)
        if view.evidence_integrity != "complete" or view.cleanup_status != "completed":
            raise self_test_error(
                "SELFTEST_ASSISTED_BEFORE_EVIDENCE_UNAVAILABLE", "原批次证据或清理不完整"
            )
        self.available[identifier] = model
        return model

    async def _source(self, batch: SelfTestBatch, source: SourceReference) -> SourceReference:
        row = await self.session.scalar(
            select(SelfTestScenarioResult).where(
                SelfTestScenarioResult.batch_id == batch.id,
                SelfTestScenarioResult.scenario_id == source.scenario_id,
                SelfTestScenarioResult.variant_key == source.variant_key,
            )
        )
        if row is None or row.source is None:
            raise self_test_error(
                "SELFTEST_ASSISTED_BEFORE_SOURCE_MISSING", "原批次缺少冻结可执行来源, 不能猜造修订"
            )
        return SourceReference.model_validate(row.source)

    async def _context(
        self,
        batch: SelfTestBatch,
        source: SourceReference,
    ) -> tuple[SelfTestBatch, SourceReference, AssistedBeforeSource]:
        lineage = source.assisted
        if lineage is None:
            raise self_test_error("SELFTEST_ASSISTED_LINEAGE_MISSING", "缺少辅助修订来源")
        if batch.id in {lineage.before_batch_id, lineage.origin_batch_id}:
            raise self_test_error("SELFTEST_ASSISTED_LINEAGE_CYCLE", "修订不能引用当前批次自身")
        before_batch = await self._before(batch.project_id, lineage.before_batch_id)
        if (
            before_batch.sealed_at is None
            or aware(before_batch.sealed_at)
            > FrozenBatchManifest.model_validate(batch.frozen_manifest).created_at
        ):
            raise self_test_error("SELFTEST_ASSISTED_LINEAGE_ORDER", "原批次必须在新批次建立前封存")
        before = await self._source(before_batch, source)
        origin_id = before_batch.id if before.assisted is None else before.assisted.origin_batch_id
        revision = 1 if before.assisted is None else before.assisted.revision_number + 1
        if lineage.origin_batch_id != origin_id or lineage.revision_number != revision:
            raise self_test_error("SELFTEST_ASSISTED_LINEAGE_ORDER", "原始批次或连续修订版本不符")
        origin_batch = await self._before(batch.project_id, origin_id)
        origin_source = await self._source(origin_batch, source)
        if origin_source.assisted is not None:
            raise self_test_error("SELFTEST_ASSISTED_ORIGIN_INVALID", "模型原始来源不能是辅助修订")
        return before_batch, before, self._projection(origin_batch, origin_source)

    @staticmethod
    def _preserved(
        source: SourceReference,
        before: SourceReference,
        origin: AssistedBeforeSource,
    ) -> None:
        lineage = source.assisted
        if lineage is None:
            raise self_test_error("SELFTEST_ASSISTED_LINEAGE_MISSING", "缺少修订来源")
        before_refs = (
            document_digest(before),
            before.workflow,
            before.case,
            before.workflow_proposal,
            before.case_proposal,
        )
        declared_refs = (
            lineage.before_source_digest,
            lineage.before_workflow,
            lineage.before_case,
            lineage.before_workflow_proposal,
            lineage.before_case_proposal,
        )
        if before_refs != declared_refs:
            raise self_test_error(
                "SELFTEST_ASSISTED_BEFORE_SOURCE_CHANGED", "原批次来源引用或摘要不符"
            )
        immutable = (
            "design_fingerprint",
            "compilation_fingerprint",
            "oracle_mapping_digest",
            "api_sources_digest",
            "api_sources",
            "oracle_bindings",
            "protocol_receipts_digest",
        )
        if any(getattr(source, name) != getattr(before, name) for name in immutable):
            raise self_test_error(
                "SELFTEST_ASSISTED_GOLDEN_CHANGED", "修订不能替换设计、API 或必要 Oracle"
            )
        if source.host_evidence is None or source.host_evidence != origin.source.host_evidence:
            raise self_test_error("SELFTEST_ASSISTED_ORIGIN_CHANGED", "原模型调用证据不能改写")
        if source.workflow == before.workflow or source.case == before.case:
            raise self_test_error(
                "SELFTEST_ASSISTED_NEW_VERSION_REQUIRED", "修订必须重新发布流程和用例"
            )
        if (
            source.workflow_proposal.change_set_id == before.workflow_proposal.change_set_id
            or source.case_proposal.change_set_id == before.case_proposal.change_set_id
        ):
            raise self_test_error(
                "SELFTEST_ASSISTED_NEW_REVIEW_REQUIRED", "修订必须有新的真实审核提案"
            )

    async def _actors(self, batch: SelfTestBatch, source: SourceReference) -> None:
        lineage = source.assisted
        if lineage is None:
            raise self_test_error("SELFTEST_ASSISTED_LINEAGE_MISSING", "缺少修订来源")
        for reference, reviewer in (
            (source.workflow_proposal, lineage.workflow_reviewer_id),
            (source.case_proposal, lineage.case_reviewer_id),
        ):
            proposal = await self.session.get(AIChangeSet, reference.change_set_id)
            if (
                proposal is None
                or proposal.project_id != batch.project_id
                or proposal.actor_type != "user"
                or proposal.created_by_id != lineage.editor_id
            ):
                raise self_test_error(
                    "SELFTEST_ASSISTED_EDITOR_MISMATCH", "修订必须由声明的用户真实提出"
                )
            if reference.route == "controlled_write" and proposal.source_snapshot.get(
                "selftest_assisted_batch_id"
            ) != str(batch.id):
                raise self_test_error(
                    "SELFTEST_ASSISTED_TASK_MISMATCH", "人工用例提案不属于当前修订任务"
                )
            query = select(AIChangeItem).where(AIChangeItem.change_set_id == proposal.id)
            query = (
                query.where(AIChangeItem.id == reference.item_id)
                if reference.item_id
                else query.where(AIChangeItem.item_type == "workflow")
            )
            items = (await self.session.scalars(query.limit(2))).all()
            if (
                len(items) != 1
                or items[0].reviewed_by_id != reviewer
                or items[0].review_status != "accepted"
            ):
                raise self_test_error(
                    "SELFTEST_ASSISTED_REVIEWER_MISMATCH", "修订审核者与真实接受回执不符"
                )

    async def _definitions(self, source: SourceReference) -> dict[str, JsonValue]:
        workflow = await self.workflows.find_version(source.workflow.id, source.workflow.version)
        case = await self.cases.find_case_version(source.case.id, source.case.version)
        if (
            workflow is None
            or case is None
            or workflow.fingerprint != source.workflow.fingerprint
            or case.fingerprint != source.case.fingerprint
        ):
            raise self_test_error("SELFTEST_ASSISTED_VERSION_MISSING", "修订链缺少真实固定发布版本")
        return {
            "workflow": WorkflowDefinition.model_validate(workflow.definition).model_dump(
                mode="json", exclude_none=True
            ),
            "case": PublishedTestCaseDefinition.model_validate(case.definition).model_dump(
                mode="json", exclude_none=True
            ),
        }

    async def _difference(self, source: SourceReference, before: SourceReference) -> None:
        lineage = source.assisted
        if lineage is None:
            raise self_test_error("SELFTEST_ASSISTED_LINEAGE_MISSING", "缺少修订来源")
        old, new = await self._definitions(before), await self._definitions(source)
        self._required_assertions(before, old["workflow"], new["workflow"])
        try:
            changes = tuple(
                RevisionDifference(
                    path=item.path,
                    before_digest=item.before_digest,
                    after_digest=item.after_digest,
                )
                for item in revision_differences(old, new)
            )
        except RevisionDifferenceLimit as error:
            raise self_test_error(
                "SELFTEST_ASSISTED_DIFF_LIMIT", "修订差异超过 200 项", 422
            ) from error
        digest = document_digest([item.model_dump(mode="json") for item in changes])
        if not changes or changes != lineage.changes or digest != lineage.diff_digest:
            raise self_test_error("SELFTEST_ASSISTED_DIFF_MISMATCH", "真实发布差异与修订回执不符")

    @staticmethod
    def _required_assertions(source: SourceReference, before: JsonValue, after: JsonValue) -> None:
        old = WorkflowDefinition.model_validate(before)
        new = WorkflowDefinition.model_validate(after)
        left, right = {node.id: node for node in old.nodes}, {node.id: node for node in new.nodes}
        for oracle in source.oracle_bindings:
            prior, current = left.get(oracle.node_id), right.get(oracle.node_id)
            if (
                prior is None
                or current is None
                or prior.model_dump(mode="json", exclude={"name", "position"})
                != current.model_dump(mode="json", exclude={"name", "position"})
            ):
                raise self_test_error(
                    "SELFTEST_ASSISTED_REQUIRED_ORACLE_CHANGED",
                    "必要断言的比较、位置或执行条件不能弱化",
                )

    @staticmethod
    def _fixture(source: SourceReference, origin: AssistedBeforeSource) -> None:
        expected = None if source.scenario_id == "ST-MCP-023" else origin.batch_key
        if source.fixture_batch_key != expected:
            raise self_test_error(
                "SELFTEST_ASSISTED_FIXTURE_SCOPE_INVALID", "修订夹具路径必须属于原始来源"
            )

    @staticmethod
    def _projection(batch: SelfTestBatch, source: SourceReference) -> AssistedBeforeSource:
        if batch.sealed_at is None:
            raise self_test_error("SELFTEST_ASSISTED_BEFORE_NOT_SEALED", "原批次尚未封存")
        return AssistedBeforeSource.model_validate(
            {
                "batch_id": batch.id,
                "batch_key": batch.batch_key,
                "scenario_id": source.scenario_id,
                "variant_key": source.variant_key,
                "source": source,
                "source_digest": document_digest(source),
                "artifacts": tuple(
                    ArtifactReference.model_validate(item) for item in batch.artifact_refs
                ),
                "sealed_at": aware(batch.sealed_at),
                "verdict": batch.verdict,
                "evidence_integrity": batch.evidence_integrity,
                "cleanup_status": batch.cleanup_status,
                "resource_digest": batch.resource_digest,
                "policy_digest": batch.policy_digest,
                "builds": BuildIdentity.model_validate(batch.builds),
            }
        )

    async def projections(
        self,
        batch: SelfTestBatch,
        sources: tuple[SourceReference, ...],
    ) -> tuple[AssistedBeforeSource, ...]:
        result: dict[tuple[UUID, str, str], AssistedBeforeSource] = {}
        for source in sources:
            if source.assisted is None:
                continue
            before_batch, before, origin = await self._context(batch, source)
            for projection in (self._projection(before_batch, before), origin):
                result[(projection.batch_id, projection.scenario_id, projection.variant_key)] = (
                    projection
                )
        if len(result) > 20:
            raise self_test_error("SELFTEST_ASSISTED_SOURCE_LIMIT", "辅助来源超过有界投影范围")
        return tuple(result.values())

    async def selection_sources(
        self,
        project: UUID,
        installation: UUID,
        binding: UUID,
        before_id: UUID,
        scenarios: tuple[TemplateScenario, ...],
    ) -> tuple[AssistedBeforeSource, ...]:
        before = await self._before(project, before_id)
        if before.installation_id != installation or before.binding_id != binding:
            raise self_test_error(
                "SELFTEST_ASSISTED_BINDING_MISMATCH", "辅助修订必须使用原安装和环境绑定"
            )
        frozen = FrozenBatchManifest.model_validate(before.frozen_manifest)
        keys = {(item.scenario_id, item.variant_key) for item in scenarios}
        if keys != {(item.scenario_id, item.variant_key) for item in frozen.scenarios}:
            raise self_test_error(
                "SELFTEST_ASSISTED_SELECTION_CHANGED", "辅助修订不能缩小或替换原场景集合"
            )
        results: dict[tuple[UUID, str, str], AssistedBeforeSource] = {}
        for item in scenarios:
            row = await self.session.scalar(
                select(SelfTestScenarioResult).where(
                    SelfTestScenarioResult.batch_id == before.id,
                    SelfTestScenarioResult.scenario_id == item.scenario_id,
                    SelfTestScenarioResult.variant_key == item.variant_key,
                )
            )
            if row is None or row.source is None:
                raise self_test_error(
                    "SELFTEST_ASSISTED_BEFORE_SOURCE_MISSING", "原批次缺少冻结可执行来源"
                )
            source = SourceReference.model_validate(row.source)
            projection = self._projection(before, source)
            results[(before.id, item.scenario_id, item.variant_key)] = projection
            if source.assisted is not None:
                origin = await self._before(project, source.assisted.origin_batch_id)
                origin_source = await self._source(origin, source)
                results[(origin.id, item.scenario_id, item.variant_key)] = self._projection(
                    origin, origin_source
                )
        if len(results) > 20:
            raise self_test_error("SELFTEST_ASSISTED_SOURCE_LIMIT", "辅助来源超过有界投影范围")
        return tuple(results.values())
