import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from secrets import token_hex, token_urlsafe
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import EncryptedValue, SecretBox, secret_box
from app.core.errors import AppError
from app.domain.api_assets import JsonValue
from app.domain.quality import ScheduleValidationError, next_scheduled_at
from app.domain.tasking import (
    ServiceTokenScope,
    TestPlanTrigger,
    digest_token,
    valid_webhook_signature,
)
from app.domain.test_assets import TestTargetType
from app.models.access import Project, User
from app.models.api_assets import Environment
from app.models.tasking import ServiceToken, TestPlan, TestPlanItem, TestPlanRun, TestPlanRunItem
from app.models.workflows import Workflow
from app.repositories.access import UserRepository
from app.repositories.tasking import TaskingRepository
from app.repositories.test_assets import TestAssetRepository
from app.repositories.workflows import WorkflowRepository
from app.schemas.tasking import TestPlanItemInput
from app.schemas.test_assets import PublishedTestCaseDefinition
from app.services.audit import AuditService
from app.services.projects import ProjectService


@dataclass(frozen=True, slots=True)
class TestPlanDetail:
    plan: TestPlan
    items: list[TestPlanItem]


@dataclass(frozen=True, slots=True)
class CreatedTestPlan:
    detail: TestPlanDetail
    webhook_secret: str


@dataclass(frozen=True, slots=True)
class TestPlanRunDetail:
    run: TestPlanRun
    items: list[TestPlanRunItem]


@dataclass(frozen=True, slots=True)
class CreatedServiceToken:
    model: ServiceToken
    token: str


@dataclass(frozen=True, slots=True)
class ServiceTokenIdentity:
    model: ServiceToken
    actor: User


@dataclass(frozen=True, slots=True)
class ExpandedPlanItem:
    workflow_id: UUID
    environment_id: UUID
    workflow_version: int
    target_type: TestTargetType
    target_id: UUID
    target_version: int
    max_retries: int
    runtime_variables: dict[str, str]
    runtime_headers: dict[str, str]
    target_snapshot: dict[str, JsonValue]


class TestPlanService:
    def __init__(self, session: AsyncSession, *, secrets: SecretBox = secret_box) -> None:
        self._session = session
        self._tasks = TaskingRepository(session)
        self._assets = TestAssetRepository(session)
        self._workflows = WorkflowRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)
        self._secrets = secrets

    async def create(
        self,
        *,
        actor: User,
        project_id: UUID,
        name: str,
        description: str,
        enabled: bool,
        schedule_interval_seconds: int | None,
        schedule_cron: str | None,
        schedule_timezone: str,
        queue_priority: int,
        items: list[TestPlanItemInput],
    ) -> CreatedTestPlan:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        normalized_name = name.strip()
        await self._ensure_unique_name(project_id, normalized_name)
        now = datetime.now(UTC)
        plan_id = uuid4()
        webhook_secret = "fthook_" + token_urlsafe(32)
        encrypted = self._secrets.encrypt(
            webhook_secret,
            associated_data=_webhook_associated_data(plan_id),
        )
        next_run_at = _next_run_at(
            now,
            enabled=enabled,
            interval_seconds=schedule_interval_seconds,
            cron_expression=schedule_cron,
            timezone_name=schedule_timezone,
        )
        plan = TestPlan(
            id=plan_id,
            project_id=project_id,
            name=normalized_name,
            description=description.strip(),
            enabled=enabled,
            schedule_interval_seconds=schedule_interval_seconds,
            schedule_cron=schedule_cron,
            schedule_timezone=schedule_timezone,
            queue_priority=queue_priority,
            next_run_at=next_run_at,
            webhook_secret_ciphertext=encrypted.ciphertext,
            webhook_secret_nonce=encrypted.nonce,
            created_by_id=actor.id,
        )
        models = await self._build_items(project_id, plan.id, items)
        self._tasks.add(plan)
        self._tasks.add_all(list(models))
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="test_plan.created",
            resource_type="test_plan",
            resource_id=plan.id,
            details={"item_count": len(models)},
        )
        await self._session.commit()
        await self._session.refresh(plan)
        return CreatedTestPlan(TestPlanDetail(plan, list(models)), webhook_secret)

    async def list_plans(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[TestPlanDetail], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        plans, total = await self._tasks.list_plans(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        details = [
            TestPlanDetail(plan, await self._tasks.list_plan_items(plan.id)) for plan in plans
        ]
        return details, total

    async def get(self, *, actor: User, project_id: UUID, plan_id: UUID) -> TestPlanDetail:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        plan = await self._get_project_plan(project_id, plan_id)
        return TestPlanDetail(plan, await self._tasks.list_plan_items(plan.id))

    async def update(
        self,
        *,
        actor: User,
        project_id: UUID,
        plan_id: UUID,
        name: str | None,
        description: str | None,
        enabled: bool | None,
        schedule_interval_seconds: int | None,
        schedule_cron: str | None,
        schedule_timezone: str | None,
        queue_priority: int | None,
        change_schedule: bool,
    ) -> TestPlanDetail:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        plan = await self._get_project_plan(project_id, plan_id)
        if name is not None:
            normalized = name.strip()
            await self._ensure_unique_name(project_id, normalized, excluding_id=plan.id)
            plan.name = normalized
        if description is not None:
            plan.description = description.strip()
        if enabled is not None:
            plan.enabled = enabled
        if change_schedule:
            plan.schedule_interval_seconds = schedule_interval_seconds
            plan.schedule_cron = schedule_cron
        if schedule_timezone is not None:
            plan.schedule_timezone = schedule_timezone
        if queue_priority is not None:
            plan.queue_priority = queue_priority
        plan.next_run_at = _next_run_at(
            datetime.now(UTC),
            enabled=plan.enabled,
            interval_seconds=plan.schedule_interval_seconds,
            cron_expression=plan.schedule_cron,
            timezone_name=plan.schedule_timezone,
        )
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="test_plan.updated",
            resource_type="test_plan",
            resource_id=plan.id,
        )
        await self._session.commit()
        await self._session.refresh(plan)
        return TestPlanDetail(plan, await self._tasks.list_plan_items(plan.id))

    async def queue_run(
        self,
        *,
        actor: User,
        project_id: UUID,
        plan_id: UUID,
        trigger: TestPlanTrigger,
    ) -> TestPlanRun:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        plan = await self._get_project_plan(project_id, plan_id)
        return await self._create_run(plan=plan, requested_by_id=actor.id, trigger=trigger)

    async def queue_external_run(
        self,
        *,
        plan: TestPlan,
        requested_by_id: UUID,
        trigger: TestPlanTrigger,
    ) -> TestPlanRun:
        return await self._create_run(
            plan=plan,
            requested_by_id=requested_by_id,
            trigger=trigger,
        )

    async def list_runs(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[TestPlanRun], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._tasks.list_runs(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def get_run(self, *, actor: User, project_id: UUID, run_id: UUID) -> TestPlanRunDetail:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        run = await self._get_project_run(project_id, run_id)
        return TestPlanRunDetail(run, await self._tasks.list_run_items(run.id))

    async def cancel_run(self, *, actor: User, project_id: UUID, run_id: UUID) -> TestPlanRun:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        run = await self._get_project_run(project_id, run_id)
        if run.status in {"passed", "failed", "cancelled"}:
            raise AppError(
                code="TEST_PLAN_RUN_FINISHED",
                message="测试计划运行已结束, 不能取消",
                status_code=409,
            )
        now = datetime.now(UTC)
        run.cancel_requested_at = run.cancel_requested_at or now
        items = await self._tasks.list_run_items(run.id)
        for item in items:
            if item.status == "queued":
                item.status = "cancelled"
            if item.workflow_execution_id is not None and item.status == "running":
                execution = await self._workflows.get_execution(item.workflow_execution_id)
                if execution is not None and execution.cancel_requested_at is None:
                    execution.cancel_requested_at = now
                    await self._workflows.request_child_cancellation(execution.id, now)
        if run.status == "queued":
            run.status = "cancelled"
            run.completed_at = now
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="test_plan_run.cancel_requested",
            resource_type="test_plan_run",
            resource_id=run.id,
        )
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def authenticate_webhook(
        self,
        *,
        plan_id: UUID,
        timestamp: str,
        signature: str,
        body: bytes,
    ) -> TestPlan:
        plan = await self._tasks.get_plan(plan_id)
        if plan is None:
            raise _invalid_webhook()
        secret = self._secrets.decrypt(
            EncryptedValue(
                ciphertext=plan.webhook_secret_ciphertext,
                nonce=plan.webhook_secret_nonce,
            ),
            associated_data=_webhook_associated_data(plan.id),
        )
        if not valid_webhook_signature(
            secret=secret,
            timestamp=timestamp,
            body=body,
            signature=signature,
            now=datetime.now(UTC),
            tolerance_seconds=settings.webhook_signature_tolerance_seconds,
        ):
            raise _invalid_webhook()
        if not plan.enabled:
            raise AppError(
                code="TEST_PLAN_DISABLED",
                message="测试计划已停用",
                status_code=409,
            )
        return plan

    async def queue_due_runs(self, now: datetime) -> list[TestPlanRun]:
        plans = await self._tasks.due_plans(now)
        runs: list[TestPlanRun] = []
        for plan in plans:
            plan.next_run_at = _next_run_at(
                now,
                enabled=plan.enabled,
                interval_seconds=plan.schedule_interval_seconds,
                cron_expression=plan.schedule_cron,
                timezone_name=plan.schedule_timezone,
            )
            runs.append(
                await self._create_run(
                    plan=plan,
                    requested_by_id=plan.created_by_id,
                    trigger=TestPlanTrigger.SCHEDULE,
                    commit=False,
                )
            )
        await self._session.commit()
        return runs

    async def _create_run(
        self,
        *,
        plan: TestPlan,
        requested_by_id: UUID,
        trigger: TestPlanTrigger,
        commit: bool = True,
    ) -> TestPlanRun:
        project_result = await self._session.execute(
            select(Project).where(Project.id == plan.project_id).with_for_update()
        )
        project = project_result.scalar_one_or_none()
        if project is None:
            raise AppError(code="PROJECT_NOT_FOUND", message="项目不存在", status_code=404)
        queued = await self._session.scalar(
            select(func.count())
            .select_from(TestPlanRun)
            .where(
                TestPlanRun.project_id == plan.project_id,
                TestPlanRun.status.in_(("queued", "running")),
            )
        )
        if int(queued or 0) >= project.queued_run_limit:
            raise AppError(
                code="PROJECT_QUEUE_LIMIT_EXCEEDED",
                message="项目排队任务数已达上限",
                status_code=429,
                details={"limit": project.queued_run_limit},
            )
        items = await self._tasks.list_plan_items(plan.id)
        if not items:
            raise AppError(
                code="TEST_PLAN_EMPTY",
                message="测试计划没有可执行项",
                status_code=409,
            )
        expanded = [
            expanded_item
            for item in items
            for expanded_item in await self._expand_plan_item(plan.project_id, item)
        ]
        queue_name = await self._queue_name_for_items(expanded)
        run = TestPlanRun(
            project_id=plan.project_id,
            test_plan_id=plan.id,
            requested_by_id=requested_by_id,
            status="queued",
            trigger_type=trigger.value,
            queue_priority=plan.queue_priority,
            queue_name=queue_name,
            baseline_run_id=None,
            quality_summary={},
            cancel_requested_at=None,
            started_at=None,
            completed_at=None,
            error_message=None,
        )
        self._tasks.add(run)
        await self._session.flush()
        snapshots = [
            TestPlanRunItem(
                test_plan_run_id=run.id,
                workflow_id=item.workflow_id,
                environment_id=item.environment_id,
                workflow_version=item.workflow_version,
                target_type=item.target_type.value,
                target_id=item.target_id,
                target_version=item.target_version,
                target_snapshot=item.target_snapshot,
                position=position,
                max_retries=item.max_retries,
                attempts=0,
                status=(
                    "quarantined" if await self._is_quarantined(plan.project_id, item) else "queued"
                ),
                runtime_variables=item.runtime_variables,
                runtime_headers=item.runtime_headers,
                workflow_execution_id=None,
                error_message=None,
            )
            for position, item in enumerate(expanded)
        ]
        self._tasks.add_all(snapshots)
        self._audit.record(
            actor_user_id=requested_by_id,
            project_id=plan.project_id,
            action="test_plan_run.queued",
            resource_type="test_plan_run",
            resource_id=run.id,
            details={"trigger": trigger.value, "item_count": len(expanded)},
        )
        if commit:
            await self._session.commit()
            await self._session.refresh(run)
        return run

    async def _is_quarantined(self, project_id: UUID, item: ExpandedPlanItem) -> bool:
        from app.services.quality import QualityService

        return await QualityService(self._session).is_quarantined(
            project_id=project_id,
            target_type=item.target_type.value,
            target_id=item.target_id,
            target_version=item.target_version,
        )

    async def _queue_name_for_items(self, items: list[ExpandedPlanItem]) -> str:
        for item in items:
            version = await self._workflows.find_version(item.workflow_id, item.workflow_version)
            if version is None:
                continue
            nodes = version.definition.get("nodes", [])
            if isinstance(nodes, list) and any(
                isinstance(node, dict) and node.get("type") in {"sql", "redis"} for node in nodes
            ):
                return "data"
        return "general"

    async def _build_items(
        self, project_id: UUID, plan_id: UUID, inputs: list[TestPlanItemInput]
    ) -> tuple[TestPlanItem, ...]:
        models: list[TestPlanItem] = []
        for position, item in enumerate(inputs):
            if item.target_type is not TestTargetType.WORKFLOW:
                models.append(await self._build_asset_item(plan_id, position, project_id, item))
                continue
            workflow_id = item.target_id or item.workflow_id
            if workflow_id is None or item.environment_id is None:
                raise AppError(
                    code="INVALID_TEST_PLAN_ITEM",
                    message="工作流计划项缺少目标或环境",
                    status_code=422,
                )
            workflow = await self._session.get(Workflow, workflow_id)
            environment = await self._session.get(Environment, item.environment_id)
            if workflow is None or workflow.project_id != project_id:
                raise AppError(code="WORKFLOW_NOT_FOUND", message="工作流不存在", status_code=404)
            if environment is None or environment.project_id != project_id:
                raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)
            version = item.target_version or item.workflow_version or workflow.current_version
            if version is None or await self._workflows.find_version(workflow.id, version) is None:
                raise AppError(
                    code="WORKFLOW_VERSION_NOT_FOUND",
                    message="工作流版本不存在",
                    status_code=404,
                )
            models.append(
                TestPlanItem(
                    test_plan_id=plan_id,
                    target_type=TestTargetType.WORKFLOW.value,
                    target_id=workflow.id,
                    target_version=version,
                    workflow_id=workflow.id,
                    environment_id=environment.id,
                    workflow_version=version,
                    position=position,
                    max_retries=item.max_retries,
                    runtime_variables=dict(item.runtime_variables),
                    runtime_headers=dict(item.runtime_headers),
                )
            )
        return tuple(models)

    async def _build_asset_item(
        self,
        plan_id: UUID,
        position: int,
        project_id: UUID,
        item: TestPlanItemInput,
    ) -> TestPlanItem:
        if item.target_id is None:
            raise AppError(
                code="INVALID_TEST_PLAN_ITEM",
                message="测试资产计划项缺少目标",
                status_code=422,
            )
        if item.target_type is TestTargetType.CASE:
            case = await self._assets.get_case(item.target_id)
            if case is None or case.project_id != project_id:
                raise AppError(
                    code="TEST_CASE_NOT_FOUND", message="测试资产不存在", status_code=404
                )
            target_id = case.id
            current_version = case.current_version
        else:
            suite = await self._assets.get_suite(item.target_id)
            if suite is None or suite.project_id != project_id:
                raise AppError(
                    code="TEST_SUITE_NOT_FOUND", message="测试资产不存在", status_code=404
                )
            target_id = suite.id
            current_version = suite.current_version
        version = item.target_version or current_version
        if version is None or not await self._target_version_exists(
            item.target_type, target_id, version
        ):
            raise AppError(
                code="TEST_ASSET_VERSION_NOT_FOUND",
                message="测试资产尚未发布或版本不存在",
                status_code=404,
            )
        return TestPlanItem(
            test_plan_id=plan_id,
            target_type=item.target_type.value,
            target_id=target_id,
            target_version=version,
            workflow_id=None,
            environment_id=None,
            workflow_version=None,
            position=position,
            max_retries=item.max_retries,
            runtime_variables=dict(item.runtime_variables),
            runtime_headers=dict(item.runtime_headers),
        )

    async def _target_version_exists(
        self, target_type: TestTargetType, target_id: UUID, version: int
    ) -> bool:
        if target_type is TestTargetType.CASE:
            return await self._assets.find_case_version(target_id, version) is not None
        return await self._assets.find_suite_version(target_id, version) is not None

    async def _expand_plan_item(
        self, project_id: UUID, item: TestPlanItem
    ) -> tuple[ExpandedPlanItem, ...]:
        target_type = TestTargetType(item.target_type)
        if target_type is TestTargetType.WORKFLOW:
            if (
                item.workflow_id is None
                or item.environment_id is None
                or item.workflow_version is None
            ):
                raise AppError(
                    code="INVALID_TEST_PLAN_ITEM",
                    message="工作流计划项配置不完整",
                    status_code=409,
                )
            return (
                ExpandedPlanItem(
                    workflow_id=item.workflow_id,
                    environment_id=item.environment_id,
                    workflow_version=item.workflow_version,
                    target_type=target_type,
                    target_id=item.target_id,
                    target_version=item.target_version,
                    max_retries=item.max_retries,
                    runtime_variables=dict(item.runtime_variables),
                    runtime_headers=dict(item.runtime_headers),
                    target_snapshot={
                        "target_type": target_type.value,
                        "target_id": str(item.target_id),
                        "target_version": item.target_version,
                    },
                ),
            )
        if target_type is TestTargetType.CASE:
            return (
                await self._expand_case(
                    project_id,
                    item.target_id,
                    item.target_version,
                    item.max_retries,
                    item.runtime_variables,
                    item.runtime_headers,
                ),
            )
        suite = await self._assets.find_suite_version(item.target_id, item.target_version)
        if suite is None:
            raise AppError(
                code="TEST_SUITE_VERSION_NOT_FOUND",
                message="测试套件版本不存在",
                status_code=409,
            )
        suite_items = await self._assets.list_suite_items(suite.id)
        expanded: list[ExpandedPlanItem] = []
        for suite_item in suite_items:
            expanded.append(
                await self._expand_case(
                    project_id,
                    suite_item.test_case_id,
                    suite_item.test_case_version,
                    item.max_retries,
                    item.runtime_variables,
                    item.runtime_headers,
                    suite_id=item.target_id,
                    suite_version=item.target_version,
                )
            )
        return tuple(expanded)

    async def _expand_case(
        self,
        project_id: UUID,
        case_id: UUID,
        case_version: int,
        max_retries: int,
        runtime_variables: dict[str, str],
        runtime_headers: dict[str, str],
        *,
        suite_id: UUID | None = None,
        suite_version: int | None = None,
    ) -> ExpandedPlanItem:
        case = await self._assets.get_case(case_id)
        version = await self._assets.find_case_version(case_id, case_version)
        if case is None or case.project_id != project_id or version is None:
            raise AppError(
                code="TEST_CASE_VERSION_NOT_FOUND",
                message="测试用例版本不存在",
                status_code=409,
            )
        definition = PublishedTestCaseDefinition.model_validate(version.definition)
        merged_variables = {**definition.runtime_variables, **runtime_variables}
        merged_headers = {**definition.runtime_headers, **runtime_headers}
        snapshot: dict[str, JsonValue] = {
            "target_type": TestTargetType.CASE.value,
            "target_id": str(case.id),
            "target_version": version.version,
            "definition": definition.model_dump(mode="json"),
        }
        if suite_id is not None:
            snapshot["source_suite"] = {
                "id": str(suite_id),
                "version": suite_version,
            }
        return ExpandedPlanItem(
            workflow_id=definition.workflow_id,
            environment_id=definition.environment_id,
            workflow_version=definition.workflow_version,
            target_type=TestTargetType.CASE,
            target_id=case.id,
            target_version=version.version,
            max_retries=max_retries,
            runtime_variables=merged_variables,
            runtime_headers=merged_headers,
            target_snapshot=snapshot,
        )

    async def _get_project_plan(self, project_id: UUID, plan_id: UUID) -> TestPlan:
        plan = await self._tasks.get_plan(plan_id)
        if plan is None or plan.project_id != project_id:
            raise AppError(code="TEST_PLAN_NOT_FOUND", message="测试计划不存在", status_code=404)
        return plan

    async def _get_project_run(self, project_id: UUID, run_id: UUID) -> TestPlanRun:
        run = await self._tasks.get_run(run_id)
        if run is None or run.project_id != project_id:
            raise AppError(
                code="TEST_PLAN_RUN_NOT_FOUND", message="测试计划运行不存在", status_code=404
            )
        return run

    async def _ensure_unique_name(
        self, project_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> None:
        if await self._tasks.plan_name_exists(
            project_id=project_id, name=name, excluding_id=excluding_id
        ):
            raise AppError(
                code="TEST_PLAN_NAME_EXISTS",
                message="测试计划名称已存在",
                status_code=409,
            )


class ServiceTokenService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tasks = TaskingRepository(session)
        self._projects = ProjectService(session)
        self._users = UserRepository(session)
        self._audit = AuditService(session)

    async def create(
        self,
        *,
        actor: User,
        project_id: UUID,
        name: str,
        scopes: set[ServiceTokenScope],
        expires_at: datetime | None,
    ) -> CreatedServiceToken:
        await self._projects.authorize_owner(actor=actor, project_id=project_id)
        now = datetime.now(UTC)
        normalized_expiry = _aware(expires_at) if expires_at is not None else None
        if normalized_expiry is not None and normalized_expiry <= now:
            raise AppError(
                code="INVALID_TOKEN_EXPIRY",
                message="Token 过期时间必须晚于当前时间",
                status_code=422,
            )
        prefix = token_hex(6)
        raw = f"ftci_{prefix}_{token_urlsafe(32)}"
        model = ServiceToken(
            project_id=project_id,
            name=name.strip(),
            token_prefix=prefix,
            token_hash=digest_token(raw),
            scopes=sorted(scope.value for scope in scopes),
            created_by_id=actor.id,
            expires_at=normalized_expiry,
            last_used_at=None,
            revoked_at=None,
            metadata_json={},
        )
        self._tasks.add(model)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="service_token.created",
            resource_type="service_token",
            resource_id=model.id,
            details={"scopes": model.scopes},
        )
        await self._session.commit()
        await self._session.refresh(model)
        return CreatedServiceToken(model, raw)

    async def list_tokens(self, *, actor: User, project_id: UUID) -> list[ServiceToken]:
        await self._projects.authorize_owner(actor=actor, project_id=project_id)
        return await self._tasks.list_tokens(project_id)

    async def revoke(self, *, actor: User, project_id: UUID, token_id: UUID) -> ServiceToken:
        await self._projects.authorize_owner(actor=actor, project_id=project_id)
        token = await self._session.get(ServiceToken, token_id)
        if token is None or token.project_id != project_id:
            raise AppError(
                code="SERVICE_TOKEN_NOT_FOUND", message="CI Token 不存在", status_code=404
            )
        token.revoked_at = token.revoked_at or datetime.now(UTC)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="service_token.revoked",
            resource_type="service_token",
            resource_id=token.id,
        )
        await self._session.commit()
        await self._session.refresh(token)
        return token

    async def authenticate(
        self,
        *,
        raw_token: str,
        project_id: UUID,
        required_scope: ServiceTokenScope,
    ) -> ServiceTokenIdentity:
        prefix = _token_prefix(raw_token)
        model = await self._tasks.find_token(prefix)
        now = datetime.now(UTC)
        if (
            model is None
            or model.project_id != project_id
            or model.revoked_at is not None
            or (model.expires_at is not None and _aware(model.expires_at) <= now)
            or required_scope.value not in model.scopes
            or not hmac.compare_digest(model.token_hash, digest_token(raw_token))
        ):
            raise AppError(
                code="INVALID_SERVICE_TOKEN",
                message="CI Token 无效或权限不足",
                status_code=401,
            )
        actor = await self._users.get(model.created_by_id)
        if actor is None or not actor.is_active:
            raise AppError(
                code="INVALID_SERVICE_TOKEN",
                message="CI Token 无效或权限不足",
                status_code=401,
            )
        model.last_used_at = now
        await self._session.commit()
        return ServiceTokenIdentity(model, actor)


def _token_prefix(raw_token: str) -> str:
    parts = raw_token.split("_", 2)
    if len(parts) != 3 or parts[0] != "ftci" or not parts[1]:
        raise AppError(
            code="INVALID_SERVICE_TOKEN", message="CI Token 无效或权限不足", status_code=401
        )
    return parts[1]


def _webhook_associated_data(plan_id: UUID) -> bytes:
    return f"test-plan:{plan_id}:webhook-secret".encode()


def _invalid_webhook() -> AppError:
    return AppError(code="INVALID_WEBHOOK_SIGNATURE", message="Webhook 签名无效", status_code=401)


def _next_run_at(
    now: datetime,
    *,
    enabled: bool,
    interval_seconds: int | None,
    cron_expression: str | None,
    timezone_name: str,
) -> datetime | None:
    try:
        return next_scheduled_at(
            now,
            enabled=enabled,
            interval_seconds=interval_seconds,
            cron_expression=cron_expression,
            timezone_name=timezone_name,
        )
    except ScheduleValidationError as error:
        raise AppError(
            code="INVALID_TEST_PLAN_SCHEDULE",
            message="测试计划调度配置无效",
            status_code=422,
            details={"reason": str(error)},
        ) from error


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
