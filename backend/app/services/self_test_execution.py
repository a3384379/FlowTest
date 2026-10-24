"""Freeze native Suite/Plan dependencies before execution; use the existing queue."""

from uuid import UUID

from kombu.exceptions import OperationalError  # type: ignore[import-untyped]
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.self_tests import document_digest
from app.domain.tasking import TestPlanTrigger
from app.domain.test_assets import TestTargetType
from app.models.access import User
from app.models.self_tests import SelfTestBatch, SelfTestScenarioResult
from app.models.tasking import TestPlanRun
from app.repositories.test_assets import TestAssetRepository
from app.schemas.self_tests import (
    ExecutionReference,
    FrozenCaseReference,
    PublishedAsset,
    ResourceSnapshot,
    ScenarioAssets,
)
from app.schemas.tasking import TestPlanItemInput
from app.schemas.test_assets import TestSuiteDefinitionInput, TestSuiteItemInput
from app.services.self_test_access import self_test_error
from app.services.tasking import TestPlanDetail, TestPlanService
from app.services.test_assets import TestSuiteService
from app.tasking.dispatch import TestPlanDispatcher


class SelfTestNativeExecution:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def variables(self, batch: SelfTestBatch) -> dict[str, str]:
        return (
            {"selftest_batch_key": batch.batch_key} if batch.batch_kind == "fixed_baseline" else {}
        )

    async def freeze(
        self, actor: User, batch: SelfTestBatch, rows: list[SelfTestScenarioResult]
    ) -> ResourceSnapshot:
        assets = [ScenarioAssets.model_validate(row.published_assets) for row in rows]
        if len({asset.case.id for asset in assets}) != len(assets):
            raise self_test_error("SELFTEST_CASE_SET_DUPLICATE", "冻结场景不能共用同一 Case")
        suites = TestSuiteService(self.session)
        suite = await suites.create(
            actor=actor,
            project_id=batch.project_id,
            name=f"selftest:{batch.id}",
            description="固定本批现场发布 Case",
            folder_id=None,
            tags=["selftest"],
            definition=TestSuiteDefinitionInput(
                items=[
                    TestSuiteItemInput(
                        test_case_id=asset.case.id, test_case_version=asset.case.version
                    )
                    for asset in assets
                ]
            ),
            commit=False,
        )
        version = await suites.publish(
            actor=actor,
            project_id=batch.project_id,
            suite_id=suite.id,
            change_note="正式执行前冻结本批 Suite",
            commit=False,
        )
        plan = await TestPlanService(self.session).create(
            actor=actor,
            project_id=batch.project_id,
            name=f"selftest:{batch.id}",
            description="本批固定套件; 无定时; 重试零次",
            enabled=True,
            schedule_interval_seconds=None,
            schedule_cron=None,
            schedule_timezone="UTC",
            queue_priority=5,
            items=[
                TestPlanItemInput(
                    target_type=TestTargetType.SUITE,
                    target_id=suite.id,
                    target_version=version.version,
                    max_retries=0,
                    runtime_variables=self.variables(batch),
                )
            ],
            commit=False,
        )
        suite_ref = PublishedAsset(
            id=suite.id, version=version.version, fingerprint=version.fingerprint
        )
        cases = tuple([await self._case_snapshot(asset, suite_ref) for asset in assets])
        snapshot = ResourceSnapshot(suite=suite_ref, plan_id=plan.detail.plan.id, cases=cases)
        batch.execution_plan_id = plan.detail.plan.id
        batch.suite_ref, batch.resource_snapshot = (
            suite_ref.model_dump(mode="json"),
            snapshot.model_dump(mode="json"),
        )
        return snapshot

    async def _case_snapshot(
        self, asset: ScenarioAssets, suite: PublishedAsset
    ) -> FrozenCaseReference:
        version = await TestAssetRepository(self.session).find_case_version(
            asset.case.id, asset.case.version
        )
        if version is None:
            raise self_test_error("SELFTEST_CASE_VERSION_MISSING", "Case 发布版本不存在")
        digest = document_digest(
            {
                "target_type": "case",
                "target_id": str(asset.case.id),
                "target_version": asset.case.version,
                "definition": version.definition,
                "source_suite": {"id": str(suite.id), "version": suite.version},
            }
        )
        return FrozenCaseReference(
            **asset.model_dump(),
            environment_id=UUID(str(version.definition["environment_id"])),
            target_snapshot_digest=digest,
        )

    async def validate_plan(
        self, actor: User, batch: SelfTestBatch, snapshot: ResourceSnapshot
    ) -> None:
        detail = await TestPlanService(self.session).get(
            actor=actor, project_id=batch.project_id, plan_id=snapshot.plan_id
        )
        self._plan_configuration(batch, snapshot, detail)
        suite = await TestAssetRepository(self.session).get_suite(snapshot.suite.id)
        version = await TestAssetRepository(self.session).find_suite_version(
            snapshot.suite.id, snapshot.suite.version
        )
        if (
            suite is None
            or version is None
            or suite.project_id != batch.project_id
            or suite.archived_at is not None
            or suite.current_version != snapshot.suite.version
            or version.fingerprint != snapshot.suite.fingerprint
        ):
            raise self_test_error("SELFTEST_SUITE_VERSION_CHANGED", "执行前固定 Suite 已漂移")

    def _plan_configuration(
        self, batch: SelfTestBatch, snapshot: ResourceSnapshot, detail: TestPlanDetail
    ) -> None:
        plan = detail.plan
        if (
            not plan.enabled
            or plan.schedule_cron is not None
            or plan.schedule_interval_seconds is not None
            or len(detail.items) != 1
        ):
            raise self_test_error(
                "SELFTEST_PLAN_CONFIGURATION_CHANGED", "计划状态、定时或成员配置改变"
            )
        item = detail.items[0]
        actual = (
            item.target_type,
            item.target_id,
            item.target_version,
            item.max_retries,
            item.runtime_variables,
            item.runtime_headers,
        )
        expected: tuple[str, UUID, int, int, dict[str, str], dict[str, str]] = (
            "suite",
            snapshot.suite.id,
            snapshot.suite.version,
            0,
            self.variables(batch),
            {},
        )
        if actual != expected or plan.id != batch.execution_plan_id:
            raise self_test_error(
                "SELFTEST_PLAN_CONFIGURATION_CHANGED", "计划不再引用冻结套件或预算"
            )

    async def queue(
        self,
        actor: User,
        batch: SelfTestBatch,
        rows: list[SelfTestScenarioResult],
        snapshot: ResourceSnapshot,
        dispatcher: TestPlanDispatcher,
    ) -> None:
        service = TestPlanService(self.session)
        run = await service.queue_run(
            actor=actor,
            project_id=batch.project_id,
            plan_id=snapshot.plan_id,
            trigger=TestPlanTrigger.MANUAL,
            commit=False,
        )
        detail = await service.get_run(actor=actor, project_id=batch.project_id, run_id=run.id)
        by_case = {
            case.case.id: (case, row) for case, row in zip(snapshot.cases, rows, strict=True)
        }
        if {item.target_id for item in detail.items} != set(by_case):
            raise self_test_error("SELFTEST_PLAN_EXPANSION_CHANGED", "原生展开集合与冻结 Case 不符")
        for item in detail.items:
            case, row = by_case[item.target_id]
            digest = document_digest(item.target_snapshot)
            if digest != case.target_snapshot_digest:
                raise self_test_error(
                    "SELFTEST_PLAN_SNAPSHOT_CHANGED", "原生展开快照与执行前冻结内容不符"
                )
            row.test_plan_run_id, row.run_item_id = run.id, item.id
            row.execution_refs = [
                ExecutionReference(
                    test_plan_run_id=run.id,
                    run_item_id=item.id,
                    execution_id=None,
                    target_version=item.target_version,
                    target_snapshot_digest=digest,
                ).model_dump(mode="json")
            ]
        batch.plan_run_ids = [str(run.id)]
        await self.session.commit()
        await self.dispatch(batch, run, dispatcher)

    async def dispatch(
        self, batch: SelfTestBatch, run: TestPlanRun, dispatcher: TestPlanDispatcher
    ) -> None:
        try:
            dispatcher.start_test_plan(
                run.id, queue_name=run.queue_name, priority=run.queue_priority
            )
            batch.reason_codes = []
            batch.readiness = "ready"
        except (AppError, OSError, RuntimeError, OperationalError):
            # The native Run identity is durable. Repeating delivery must reuse it.
            batch.reason_codes = ["SELFTEST_DISPATCH_UNCONFIRMED"]
            batch.readiness = "needs_review"
        await self.session.commit()

    async def resume_dispatch(
        self,
        actor: User,
        batch: SelfTestBatch,
        snapshot: ResourceSnapshot,
        dispatcher: TestPlanDispatcher,
    ) -> None:
        await self.validate_plan(actor, batch, snapshot)
        if len(batch.plan_run_ids) != 1:
            raise self_test_error("SELFTEST_DISPATCH_RUN_MISSING", "未知队列结果缺少唯一原生 Run")
        run = await self.session.get(TestPlanRun, UUID(batch.plan_run_ids[0]))
        if (
            run is None
            or run.project_id != batch.project_id
            or run.test_plan_id != snapshot.plan_id
        ):
            raise self_test_error("SELFTEST_DISPATCH_RUN_MISSING", "原生 Run 不属于本批冻结计划")
        from app.repositories.self_tests import SelfTestRepository

        if await SelfTestRepository(self.session).lock_batch(batch) is None:
            raise self_test_error("SELFTEST_BATCH_BUSY", "批次正在被其他任务修改")
        batch.reason_codes, batch.readiness = [], "ready"
        await self.session.commit()
        if run.status == "queued":
            await self.dispatch(batch, run, dispatcher)
