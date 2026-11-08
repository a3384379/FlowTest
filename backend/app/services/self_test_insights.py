"""Product diagnostics, frozen denominators and independent observation projections."""

import hashlib
import json
from dataclasses import dataclass

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.self_tests import SelfTestSettings
from app.domain.integration_plans import PlanDiagnostic
from app.domain.self_tests import document_digest
from app.domain.test_design import fingerprint_design
from app.models.ai import AIChangeSet
from app.models.self_tests import SelfTestBatch, SelfTestScenarioResult
from app.repositories.self_tests import SelfTestRepository
from app.schemas.self_test_insights import (
    SelfTestCaseSlot,
    SelfTestComparison,
    SelfTestDiagnostic,
    SelfTestInsights,
    SelfTestMetric,
    SelfTestScenarioComparison,
)
from app.schemas.self_tests import (
    FrozenBatchManifest,
    GenerationState,
    ResourceSnapshot,
    ScenarioAssets,
    SourceReference,
    TemplateScenario,
)
from app.services.self_test_access import self_test_error
from app.services.self_test_insight_documents import (
    InsightArtifactScenario,
    InsightCall,
    InsightDocument,
    InsightExecution,
    InsightGeneration,
    SelfTestInsightDocuments,
)
from app.services.self_test_views import SelfTestViews


def _display(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > 4000:
        return json.dumps(
            {
                "detail_status": "超过单项展示上限, 完整内容见已授权原始证据",
                "count": len(value) if isinstance(value, list) else None,
                "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            },
            ensure_ascii=False,
        )
    return encoded


def _one_or_many(values: list[str]) -> str | list[str] | None:
    if not values:
        return None
    return values[0] if len(values) == 1 else values


@dataclass(frozen=True)
class _ComparisonValue:
    field: str
    expected: object
    observed: object
    required: bool = True
    recorded: bool = True

    def project(self, row: SelfTestScenarioResult) -> SelfTestComparison:
        difference = (
            "not_required"
            if not self.required
            else "not_recorded"
            if not self.recorded
            else "equal"
            if self.expected == self.observed
            else "different"
        )
        return SelfTestComparison.model_validate(
            {
                "field": self.field,
                "expected": _display(self.expected),
                "observed": _display(self.observed),
                "difference": difference,
                "verification_status": row.verification_status,
                "reason_codes": row.reason_codes,
            }
        )


def _metric_exclusions(
    key: str, denominator: int, partial: bool, unrecorded: bool, unconfirmed: bool
) -> tuple[str, ...]:
    if not denominator:
        return ("SELFTEST_NO_EVALUABLE_DENOMINATOR",)
    reasons = []
    if key in {"protocol", "design"} and partial:
        reasons.append("SELFTEST_ONLY_UPLOADED_GENERATION_EVALUATED")
    if key == "protocol" and unrecorded:
        reasons.append("SELFTEST_UNRECORDED_CALLS_EXCLUDED")
    if key in {"first", "assisted", "faults"} and unconfirmed:
        reasons.append("SELFTEST_BATCH_OBSERVATION_NOT_CONFIRMED")
    return tuple(reasons)


class SelfTestInsightService:
    def __init__(self, session: AsyncSession, config: SelfTestSettings) -> None:
        self.session = session
        self.repository = SelfTestRepository(session)
        self.views = SelfTestViews(session, config)

    async def read(self, batch: SelfTestBatch) -> SelfTestInsights:
        frozen = FrozenBatchManifest.model_validate(batch.frozen_manifest)
        rows = await self.repository.scenarios(batch.id)
        keys = {(item.scenario_id, item.variant_key) for item in frozen.scenarios}
        if len(rows) != len(keys) or {(row.scenario_id, row.variant_key) for row in rows} != keys:
            raise self_test_error(
                "SELFTEST_INSIGHT_SCENARIO_SET_MISMATCH", "当前批次场景集合不完整"
            )
        view = await self.views.batch(batch, editing=False)
        documents = SelfTestInsightDocuments(self.session)
        manifest = await documents.read(batch, "manifest")
        evidence = await documents.read(batch, "evidence")
        sources = [SourceReference.model_validate(row.source) for row in rows if row.source]
        trails = []
        if frozen.assisted_before_batch_id is None:
            for source in sources:
                trail = await documents.generation(batch, source.generation_manifest)
                self._validate_generation(batch, source, trail)
                trails.append(trail)
        comparisons = self._comparisons(batch, rows, manifest, evidence)
        diagnostics = await self._diagnostics(batch)
        slots = self._slots(view.resource_snapshot, trails)
        return SelfTestInsights(
            batch_id=batch.id,
            manifest_digest=batch.manifest_digest,
            task_set_digest=frozen.template.task_set_digest,
            template_version=frozen.template.version,
            scope=frozen.verification_scope,
            assisted_before_batch_id=frozen.assisted_before_batch_id,
            metrics=self._metrics(
                batch,
                frozen,
                rows,
                sources,
                manifest,
                view.evidence_integrity == "complete",
                trails,
            ),
            diagnostics=diagnostics,
            case_slots=slots,
            comparisons=comparisons,
            reason_codes=() if manifest and evidence else ("SELFTEST_OBSERVATION_NOT_AVAILABLE",),
        )

    @staticmethod
    def _validate_generation(
        batch: SelfTestBatch, source: SourceReference, trail: InsightGeneration
    ) -> None:
        design = trail.design or trail.combined_design
        fingerprint = (
            trail.design_fingerprint
            if trail.design is not None
            else trail.combined_design_fingerprint
        )
        identity = (trail.scenario_id, trail.variant_key, trail.compilation_fingerprint)
        expected = (source.scenario_id, source.variant_key, source.compilation_fingerprint)
        call_ids = [call.call_id for call in trail.calls]
        if (
            identity != expected
            or design is None
            or fingerprint != source.design_fingerprint
            or fingerprint_design(design) != source.design_fingerprint
            or document_digest([call.model_dump(mode="json") for call in trail.calls])
            != source.protocol_receipts_digest
            or len(set(call_ids)) != len(call_ids)
            or any(
                (call.batch_key, call.scenario_id) != (batch.batch_key, source.scenario_id)
                for call in trail.calls
            )
        ):
            raise self_test_error(
                "SELFTEST_INSIGHT_SOURCE_MISMATCH", "生成回执身份、设计或调用摘要与当前固定来源不符"
            )

    @staticmethod
    def _calls(trails: list[InsightGeneration]) -> dict[str, InsightCall]:
        result: dict[str, InsightCall] = {}
        for trail in trails:
            for call in trail.calls:
                previous = result.get(call.call_id)
                # H repeats one batch-wide trail on each scenario, changing only its scenario ID.
                if previous is not None and previous.model_dump(
                    exclude={"scenario_id"}
                ) != call.model_dump(exclude={"scenario_id"}):
                    raise self_test_error(
                        "SELFTEST_INSIGHT_SOURCE_MISMATCH", "相同调用身份的生成回执内容不一致"
                    )
                result[call.call_id] = call
        return result

    @staticmethod
    def _slots(
        snapshot: ResourceSnapshot | None, trails: list[InsightGeneration]
    ) -> tuple[SelfTestCaseSlot, ...]:
        if snapshot is None:
            return ()
        slots: dict[tuple[str, str], str] = {}
        for trail in trails:
            candidates = (
                []
                if trail.design is None
                else [item for item in trail.design.scenarios if item.kind == "happy_path"]
            )
            if len(candidates) == 1:
                slots[(trail.scenario_id, trail.variant_key)] = f"scenario:{candidates[0].id}"
        return tuple(
            SelfTestCaseSlot(
                scenario_id=item.scenario_id,
                variant_key=item.variant_key,
                workflow_slot=slots.get((item.scenario_id, item.variant_key)),
                case_id=item.case.id,
                case_version=item.case.version,
                environment_id=item.environment_id,
            )
            for item in snapshot.cases
        )

    async def _diagnostics(self, batch: SelfTestBatch) -> tuple[SelfTestDiagnostic, ...]:
        state = GenerationState.model_validate(batch.generation_summary or {})
        result = [
            SelfTestDiagnostic.model_validate(item.model_dump()) for item in state.diagnostics
        ]
        result.extend(
            SelfTestDiagnostic(
                code=code,
                severity="input" if batch.readiness == "needs_input" else "blocker",
                repair_hint="请按当前阶段核对部署登记、必需输入和审核回执; 原始原因码保留。",
            )
            for code in batch.reason_codes
        )
        for reference in state.proposals:
            proposal = await self.session.get(AIChangeSet, reference.change_set_id)
            if proposal is None or proposal.project_id != batch.project_id:
                raise self_test_error("SELFTEST_PROPOSAL_NOT_FOUND", "诊断提案不存在或跨项目", 404)
            compiler = proposal.source_snapshot.get("integration_plan_compiler")
            if not isinstance(compiler, dict):
                continue
            values = TypeAdapter(list[PlanDiagnostic]).validate_python(
                compiler.get("diagnostics", [])
            )
            result.extend(
                SelfTestDiagnostic(
                    code=item.code,
                    severity="blocker" if item.severity == "blocker" else "review",
                    field_path=item.path[:500],
                    repair_hint=item.message,
                )
                for item in values
            )
        if len(result) > 500:
            raise self_test_error("SELFTEST_INSIGHT_DIAGNOSTIC_LIMIT", "编译诊断超过展示限制")
        return tuple(result)

    @staticmethod
    def _comparisons(
        batch: SelfTestBatch,
        rows: list[SelfTestScenarioResult],
        manifest: InsightDocument | None,
        evidence: InsightDocument | None,
    ) -> tuple[SelfTestScenarioComparison, ...]:
        if manifest is None or evidence is None:
            return ()
        expected = {(item.scenario_id, item.variant_key): item for item in manifest.scenarios}
        observed = {(item.scenario_id, item.variant_key): item for item in evidence.scenarios}
        if set(expected) != {(row.scenario_id, row.variant_key) for row in rows} or set(
            observed
        ) != set(expected):
            raise self_test_error(
                "SELFTEST_INSIGHT_SCOPE_MISMATCH", "Observer 清单与冻结场景集合不符"
            )
        return tuple(
            SelfTestInsightService._comparison(
                batch,
                row,
                expected[(row.scenario_id, row.variant_key)],
                observed[(row.scenario_id, row.variant_key)],
            )
            for row in rows
        )

    @staticmethod
    def _comparison(
        batch: SelfTestBatch,
        row: SelfTestScenarioResult,
        expected: InsightArtifactScenario,
        observed: InsightArtifactScenario,
    ) -> SelfTestScenarioComparison:
        actual = observed.execution
        frozen = expected.expected
        if frozen is None:
            raise self_test_error(
                "SELFTEST_INSIGHT_EXPECTATION_MISSING", "Observer 清单缺少固定期望"
            )
        SelfTestInsightService._observation_scope(batch, row, actual)
        recorded = actual is not None
        failed_nodes = (
            [] if actual is None else [node for node in actual.nodes if node.status == "failed"]
        )
        values = [
            _ComparisonValue(
                "原始状态",
                frozen.execution_status,
                None if actual is None else actual.status,
                recorded=recorded,
            ),
            _ComparisonValue(
                "错误码",
                frozen.error_code,
                None if actual is None else actual.error_code,
                recorded=recorded,
            ),
            _ComparisonValue(
                "失败节点",
                frozen.node_id,
                _one_or_many([item.node_id for item in failed_nodes]),
                required=frozen.node_id is not None,
                recorded=bool(failed_nodes),
            ),
            _ComparisonValue(
                "失败阶段",
                frozen.phase,
                _one_or_many([item.phase for item in failed_nodes]),
                required=frozen.phase is not None,
                recorded=bool(failed_nodes),
            ),
            _ComparisonValue(
                "主阶段状态",
                frozen.main_status,
                None if actual is None else actual.main_status,
                required=frozen.main_status is not None,
                recorded=actual is not None and actual.main_status is not None,
            ),
            _ComparisonValue(
                "清理阶段状态",
                frozen.cleanup_status,
                None if actual is None else actual.cleanup_status,
                required=frozen.cleanup_status is not None,
                recorded=actual is not None and actual.cleanup_status is not None,
            ),
            _ComparisonValue(
                "请求次数",
                frozen.request_count,
                None if observed.journal is None else observed.journal.request_count,
                required=frozen.request_count is not None,
                recorded=observed.journal is not None,
            ),
            _ComparisonValue(
                "节点与次数",
                [item.model_dump() for item in frozen.top_nodes],
                None if actual is None else [item.model_dump() for item in actual.nodes],
                required=bool(frozen.top_nodes),
                recorded=recorded,
            ),
            _ComparisonValue(
                "分支与迭代节点",
                [item.model_dump() for item in frozen.nested_nodes],
                None if actual is None else [item.model_dump() for item in actual.nested_nodes],
                required=bool(frozen.nested_nodes),
                recorded=recorded,
            ),
            _ComparisonValue(
                "批次清理",
                "completed",
                observed.cleanup_status,
                recorded=observed.cleanup_status is not None,
            ),
        ]
        return SelfTestScenarioComparison(
            scenario_id=row.scenario_id,
            variant_key=row.variant_key,
            execution_id=None if actual is None else actual.id,
            items=tuple(value.project(row) for value in values),
        )

    @staticmethod
    def _observation_scope(
        batch: SelfTestBatch, row: SelfTestScenarioResult, actual: InsightExecution | None
    ) -> None:
        if actual is None:
            return
        if actual.project_id != batch.project_id or str(actual.id) not in {
            str(item.get("execution_id")) for item in row.execution_refs
        }:
            raise self_test_error(
                "SELFTEST_INSIGHT_EXECUTION_MISMATCH", "观察执行不属于当前自测场景"
            )
        assets: ScenarioAssets
        if row.source is not None:
            assets = SourceReference.model_validate(row.source)
        elif row.published_assets is not None:
            assets = ScenarioAssets.model_validate(row.published_assets)
        else:
            raise self_test_error("SELFTEST_INSIGHT_SOURCE_MISSING", "当前观察执行缺少固定来源")
        if (actual.workflow_id, actual.workflow_fingerprint) != (
            assets.workflow.id,
            assets.workflow.fingerprint,
        ):
            raise self_test_error("SELFTEST_INSIGHT_EXECUTION_MISMATCH", "观察流程与冻结版本不符")

    @staticmethod
    def _observation_confirmed(
        batch: SelfTestBatch, rows: list[SelfTestScenarioResult], complete: bool
    ) -> bool:
        available = bool(
            batch.sealed_at
            and complete
            and not batch.reason_codes
            and batch.cleanup_status == "completed"
        )
        scenario_failure = any(row.verification_status == "mismatched" for row in rows)
        return available and (
            batch.verdict == "passed" or (batch.verdict == "failed" and scenario_failure)
        )

    @staticmethod
    def _metrics(
        batch: SelfTestBatch,
        frozen: FrozenBatchManifest,
        rows: list[SelfTestScenarioResult],
        sources: list[SourceReference],
        manifest: InsightDocument | None,
        complete: bool,
        trails: list[InsightGeneration],
    ) -> tuple[SelfTestMetric, ...]:
        confirmed = SelfTestInsightService._observation_confirmed(batch, rows, complete)
        unconfirmed = batch.sealed_at is not None and not confirmed

        def matched(row: SelfTestScenarioResult) -> bool:
            return confirmed and row.verification_status == "matched"

        count = len(rows)
        metrics = [
            SelfTestMetric(
                key=key,
                label=label,
                numerator=sum(matched(row) for row in selected),
                denominator=len(selected),
                basis="当前冻结场景集合; 分子为证据完整的独立核验 matched 场景",
                exclusions=("SELFTEST_NO_APPLICABLE_SCENARIOS",)
                if not selected
                else ("SELFTEST_BATCH_OBSERVATION_NOT_CONFIRMED",)
                if unconfirmed
                else (),
            )
            for key, label, selected in (
                (
                    "api",
                    "API 执行符合率",
                    [row for row in rows if row.frozen_scenario.get("category") == "api"],
                ),
                (
                    "engine",
                    "引擎符合率",
                    [row for row in rows if row.frozen_scenario.get("category") == "engine"],
                ),
                ("verification", "独立核验符合率", rows),
            )
        ]
        if batch.batch_kind != "mcp_generated":
            return tuple(metrics)
        assisted = frozen.assisted_before_batch_id is not None
        complete_sources = len(sources)
        required = (
            []
            if manifest is None
            else [
                (item.scenario_id, item.variant_key, oracle)
                for item in manifest.scenarios
                for oracle in item.required_oracle_ids
            ]
        )
        landed = {
            (source.scenario_id, source.variant_key, oracle.oracle_id)
            for source in sources
            for oracle in source.oracle_bindings
        }
        faults = [
            row
            for row in rows
            if TemplateScenario.model_validate(row.frozen_scenario).expected.status == "failed"
        ]
        calls = SelfTestInsightService._calls(trails)
        design_calls = [
            call for call in calls.values() if call.tool_name == "flowtest.generate_test_design"
        ]
        unrecorded = GenerationState.model_validate(
            batch.generation_summary or {}
        ).tool_call_count > len(calls)
        data = (
            (
                "protocol",
                "协议可用率",
                sum(call.success for call in calls.values()),
                len(calls),
                "当前已上传生成回执的成功调用 / 已记录调用; 未上传调用排除; 辅助批次不重复计数",
            ),
            (
                "design",
                "设计合法率",
                sum(call.success for call in design_calls),
                len(design_calls),
                "当前生成回执中设计工具成功 / 设计工具调用; 未记录或辅助批次为未评估",
            ),
            (
                "assets",
                "可执行资产生成率",
                len(sources),
                count,
                "已校验固定 Workflow 与 Case 来源 / 当前冻结生成场景",
            ),
            (
                "oracle",
                "必要 Oracle 落地率",
                sum(item in landed for item in required),
                len(required),
                "Observer 冻结 required_oracle_ids 中有已发布断言绑定的数量",
            ),
            (
                "first",
                "首次生成符合率",
                0 if assisted else sum(matched(row) for row in rows),
                0 if assisted else count,
                "仅首次生成批次; 辅助修订排除",
            ),
            (
                "assisted",
                "辅助修订后符合率",
                sum(matched(row) for row in rows) if assisted else 0,
                count if assisted else 0,
                "仅新辅助批次; 不覆盖首次结果",
            ),
            (
                "faults",
                "固定缺陷检出率",
                sum(matched(row) for row in faults),
                len(faults),
                "冻结原始期望为 failed 且 O 确认符合 / 冻结故障场景",
            ),
            (
                "provenance",
                "来源完整率",
                complete_sources,
                count,
                "通过来源、审核和固定发布校验的来源 / 当前冻结场景; 执行结论另列",
            ),
        )
        metrics.extend(
            SelfTestMetric(
                key=key,
                label=label,
                numerator=numerator,
                denominator=denominator,
                basis=basis,
                exclusions=_metric_exclusions(
                    key, denominator, len(trails) < count, unrecorded, unconfirmed
                ),
            )
            for key, label, numerator, denominator, basis in data
        )
        return tuple(metrics)
