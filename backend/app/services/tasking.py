import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from secrets import token_hex, token_urlsafe
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import EncryptedValue, SecretBox, secret_box
from app.core.errors import AppError
from app.domain.tasking import (
    ServiceTokenScope,
    TestPlanTrigger,
    digest_token,
    next_scheduled_at,
    valid_webhook_signature,
)
from app.models.access import User
from app.models.api_assets import Environment
from app.models.tasking import ServiceToken, TestPlan, TestPlanItem, TestPlanRun, TestPlanRunItem
from app.models.workflows import Workflow
from app.repositories.access import UserRepository
from app.repositories.tasking import TaskingRepository
from app.repositories.workflows import WorkflowRepository
from app.schemas.tasking import TestPlanItemInput
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


class TestPlanService:
    def __init__(self, session: AsyncSession, *, secrets: SecretBox = secret_box) -> None:
        self._session = session
        self._tasks = TaskingRepository(session)
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
        plan = TestPlan(
            id=plan_id,
            project_id=project_id,
            name=normalized_name,
            description=description.strip(),
            enabled=enabled,
            schedule_interval_seconds=schedule_interval_seconds,
            next_run_at=next_scheduled_at(now, schedule_interval_seconds, enabled),
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
        plan.next_run_at = next_scheduled_at(
            datetime.now(UTC), plan.schedule_interval_seconds, plan.enabled
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
            plan.next_run_at = next_scheduled_at(now, plan.schedule_interval_seconds, plan.enabled)
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
        items = await self._tasks.list_plan_items(plan.id)
        if not items:
            raise AppError(
                code="TEST_PLAN_EMPTY",
                message="测试计划没有可执行项",
                status_code=409,
            )
        run = TestPlanRun(
            project_id=plan.project_id,
            test_plan_id=plan.id,
            requested_by_id=requested_by_id,
            status="queued",
            trigger_type=trigger.value,
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
                position=item.position,
                max_retries=item.max_retries,
                attempts=0,
                status="queued",
                runtime_variables=item.runtime_variables,
                runtime_headers=item.runtime_headers,
                workflow_execution_id=None,
                error_message=None,
            )
            for item in items
        ]
        self._tasks.add_all(snapshots)
        self._audit.record(
            actor_user_id=requested_by_id,
            project_id=plan.project_id,
            action="test_plan_run.queued",
            resource_type="test_plan_run",
            resource_id=run.id,
            details={"trigger": trigger.value, "item_count": len(items)},
        )
        if commit:
            await self._session.commit()
            await self._session.refresh(run)
        return run

    async def _build_items(
        self, project_id: UUID, plan_id: UUID, inputs: list[TestPlanItemInput]
    ) -> tuple[TestPlanItem, ...]:
        models: list[TestPlanItem] = []
        for position, item in enumerate(inputs):
            workflow = await self._session.get(Workflow, item.workflow_id)
            environment = await self._session.get(Environment, item.environment_id)
            if workflow is None or workflow.project_id != project_id:
                raise AppError(code="WORKFLOW_NOT_FOUND", message="工作流不存在", status_code=404)
            if environment is None or environment.project_id != project_id:
                raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)
            version = item.workflow_version or workflow.current_version
            if version is None or await self._workflows.find_version(workflow.id, version) is None:
                raise AppError(
                    code="WORKFLOW_VERSION_NOT_FOUND",
                    message="工作流版本不存在",
                    status_code=404,
                )
            models.append(
                TestPlanItem(
                    test_plan_id=plan_id,
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


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
