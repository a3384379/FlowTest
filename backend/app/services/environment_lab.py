from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.errors import AppError
from app.domain.environment_lab import (
    EnvironmentRuntime,
    EnvironmentRuntimeError,
    EnvironmentSeedEvidence,
    EnvironmentTemplateManifest,
    ProvisionedEnvironment,
)
from app.models.access import User
from app.models.environment_lab import (
    EnvironmentInstance,
    EnvironmentTemplate,
    EnvironmentTemplateVersion,
)
from app.repositories.environment_lab import EnvironmentLabRepository
from app.schemas.environment_lab import (
    EnvironmentProvisionRequest,
    EnvironmentTemplateCreate,
    EnvironmentTemplateVersionCreate,
)
from app.services.audit import AuditService
from app.services.projects import ProjectService

logger = logging.getLogger(__name__)


class EnvironmentTaskDispatcher(Protocol):
    def start_environment_provision(self, instance_id: UUID) -> None: ...

    def start_environment_cleanup(self, instance_id: UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class EnvironmentTemplateView:
    template: EnvironmentTemplate
    version: EnvironmentTemplateVersion
    manifest: EnvironmentTemplateManifest


@dataclass(frozen=True, slots=True)
class EnvironmentProvisionPlan:
    instance_id: UUID
    project_id: UUID
    template_key: str
    template_version: int
    manifest: EnvironmentTemplateManifest
    manifest_sha256: str
    signature: str
    fencing_token: int


class EnvironmentTemplateSigner:
    algorithm = "hmac-sha256-v1"

    def __init__(self, key_material: str) -> None:
        self._key = hashlib.sha256(key_material.encode()).digest()

    def sign(self, *, template_key: str, version: int, manifest_sha256: str) -> str:
        return hmac.new(
            self._key,
            _signature_payload(template_key, version, manifest_sha256),
            hashlib.sha256,
        ).hexdigest()

    def verify(
        self, *, template_key: str, version: int, manifest_sha256: str, signature: str
    ) -> bool:
        expected = self.sign(
            template_key=template_key,
            version=version,
            manifest_sha256=manifest_sha256,
        )
        return hmac.compare_digest(expected, signature)


class EnvironmentTemplateService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = EnvironmentLabRepository(session)
        self._audit = AuditService(session)
        self._signer = _template_signer()

    async def register(
        self, *, actor: User, payload: EnvironmentTemplateCreate
    ) -> EnvironmentTemplateView:
        self._require_enabled()
        self._require_system_admin(actor)
        self._validate_images(payload.manifest)
        template_key = payload.template_key.strip()
        if await self._repository.get_template_by_key(template_key) is not None:
            raise AppError(
                code="ENVIRONMENT_TEMPLATE_EXISTS",
                message="环境模板标识已存在",
                status_code=409,
            )
        template = EnvironmentTemplate(
            template_key=template_key,
            display_name=payload.display_name.strip(),
            description=payload.description.strip(),
            status="active",
            created_by_id=actor.id,
        )
        self._repository.add_template(template)
        await self._session.flush()
        version = self._new_version(actor, template, 1, payload.manifest)
        self._repository.add_template_version(version)
        await self._session.flush()
        self._record_template(actor, template, version, "environment_template.registered")
        await self._session.commit()
        await self._session.refresh(template)
        await self._session.refresh(version)
        return EnvironmentTemplateView(
            template=template, version=version, manifest=payload.manifest
        )

    async def create_version(
        self,
        *,
        actor: User,
        template_id: UUID,
        payload: EnvironmentTemplateVersionCreate,
    ) -> EnvironmentTemplateView:
        self._require_enabled()
        self._require_system_admin(actor)
        self._validate_images(payload.manifest)
        template = await self._repository.get_template_for_update(template_id)
        if template is None:
            raise _template_not_found()
        if template.status != "active":
            raise AppError(
                code="ENVIRONMENT_TEMPLATE_DISABLED",
                message="已停用环境模板不能创建新版本",
                status_code=409,
            )
        number = await self._repository.latest_template_version(template.id) + 1
        version = self._new_version(actor, template, number, payload.manifest)
        self._repository.add_template_version(version)
        await self._session.flush()
        self._record_template(actor, template, version, "environment_template.version_created")
        await self._session.commit()
        await self._session.refresh(version)
        return EnvironmentTemplateView(
            template=template, version=version, manifest=payload.manifest
        )

    async def disable(self, *, actor: User, template_id: UUID) -> EnvironmentTemplate:
        self._require_enabled()
        self._require_system_admin(actor)
        template = await self._repository.get_template_for_update(template_id)
        if template is None:
            raise _template_not_found()
        if template.status == "disabled":
            return template
        template.status = "disabled"
        self._audit.record(
            actor_user_id=actor.id,
            project_id=None,
            action="environment_template.disabled",
            resource_type="environment_template",
            resource_id=template.id,
        )
        await self._session.commit()
        await self._session.refresh(template)
        return template

    async def list_versions(self, *, actor: User) -> tuple[EnvironmentTemplateView, ...]:
        self._require_enabled()
        include_disabled = actor.is_system_admin
        rows = await self._repository.list_template_versions(include_disabled=include_disabled)
        views: list[EnvironmentTemplateView] = []
        for version, template in rows:
            manifest = EnvironmentTemplateManifest.model_validate(version.manifest)
            self._verify_version(template, version, manifest)
            views.append(
                EnvironmentTemplateView(template=template, version=version, manifest=manifest)
            )
        return tuple(views)

    def _new_version(
        self,
        actor: User,
        template: EnvironmentTemplate,
        number: int,
        manifest: EnvironmentTemplateManifest,
    ) -> EnvironmentTemplateVersion:
        signature = self._signer.sign(
            template_key=template.template_key,
            version=number,
            manifest_sha256=manifest.sha256,
        )
        return EnvironmentTemplateVersion(
            template_id=template.id,
            version=number,
            manifest=manifest.model_dump(mode="json"),
            manifest_sha256=manifest.sha256,
            signature=signature,
            signature_algorithm=self._signer.algorithm,
            signed_by_id=actor.id,
        )

    def _verify_version(
        self,
        template: EnvironmentTemplate,
        version: EnvironmentTemplateVersion,
        manifest: EnvironmentTemplateManifest,
    ) -> None:
        valid = manifest.sha256 == version.manifest_sha256 and self._signer.verify(
            template_key=template.template_key,
            version=version.version,
            manifest_sha256=version.manifest_sha256,
            signature=version.signature,
        )
        if not valid or version.signature_algorithm != self._signer.algorithm:
            raise AppError(
                code="ENVIRONMENT_TEMPLATE_SIGNATURE_INVALID",
                message="环境模板签名验证失败",
                status_code=409,
            )

    def _record_template(
        self,
        actor: User,
        template: EnvironmentTemplate,
        version: EnvironmentTemplateVersion,
        action: str,
    ) -> None:
        self._audit.record(
            actor_user_id=actor.id,
            project_id=None,
            action=action,
            resource_type="environment_template",
            resource_id=template.id,
            details={
                "version": version.version,
                "manifest_sha256": version.manifest_sha256,
                "signature_algorithm": version.signature_algorithm,
            },
        )

    @staticmethod
    def _require_system_admin(actor: User) -> None:
        if not actor.is_system_admin:
            raise AppError(
                code="SYSTEM_ADMIN_REQUIRED",
                message="需要系统管理员权限",
                status_code=403,
            )

    @staticmethod
    def _validate_images(manifest: EnvironmentTemplateManifest) -> None:
        allowed = frozenset(settings.environment_image_allowlist)
        rejected = sorted(manifest.images - allowed)
        if rejected:
            raise AppError(
                code="ENVIRONMENT_IMAGE_NOT_ALLOWED",
                message="环境模板包含未进入白名单的镜像",
                status_code=422,
                details={"images": rejected},
            )

    @staticmethod
    def _require_enabled() -> None:
        if not settings.feature_environment_lab_enabled:
            raise AppError(
                code="ENVIRONMENT_LAB_DISABLED",
                message="环境实验室尚未启用",
                status_code=409,
            )


class EnvironmentInstanceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = EnvironmentLabRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)
        self._signer = _template_signer()

    async def queue(
        self,
        *,
        actor: User,
        project_id: UUID,
        payload: EnvironmentProvisionRequest,
        idempotency_key: str,
        dispatcher: EnvironmentTaskDispatcher,
    ) -> EnvironmentInstance:
        EnvironmentTemplateService._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        existing = await self._repository.get_instance_by_idempotency_key(
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return existing
        version = await self._repository.get_template_version(payload.template_version_id)
        if version is None:
            raise _template_not_found()
        template = await self._repository.get_template(version.template_id)
        if template is None:
            raise _template_not_found()
        if template.status != "active":
            raise AppError(
                code="ENVIRONMENT_TEMPLATE_DISABLED",
                message="环境模板已停用",
                status_code=409,
            )
        manifest = EnvironmentTemplateManifest.model_validate(version.manifest)
        self._verify_snapshot(template, version, manifest)
        ttl_seconds = payload.ttl_seconds or manifest.default_ttl_seconds
        maximum = min(manifest.maximum_ttl_seconds, settings.environment_max_ttl_seconds)
        if ttl_seconds > maximum:
            raise AppError(
                code="ENVIRONMENT_TTL_LIMIT_EXCEEDED",
                message=f"环境 TTL 不能超过 {maximum} 秒",
                status_code=422,
            )
        now = datetime.now(UTC)
        instance_id = uuid4()
        instance = EnvironmentInstance(
            id=instance_id,
            project_id=project_id,
            template_version_id=version.id,
            template_key=template.template_key,
            template_version=version.version,
            idempotency_key=idempotency_key,
            status="queued",
            cleanup_status="none",
            runtime_name=_runtime_name(instance_id),
            manifest_snapshot=manifest.model_dump(mode="json"),
            manifest_sha256=version.manifest_sha256,
            signature=version.signature,
            ttl_seconds=ttl_seconds,
            fencing_token=1,
            queued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            created_by_id=actor.id,
        )
        self._repository.add_instance(instance)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            concurrent = await self._repository.get_instance_by_idempotency_key(
                project_id=project_id,
                idempotency_key=idempotency_key,
            )
            if concurrent is not None:
                return concurrent
            raise
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="environment_instance.queued",
            resource_type="environment_instance",
            resource_id=instance.id,
            details={
                "template_key": template.template_key,
                "template_version": version.version,
                "ttl_seconds": ttl_seconds,
            },
        )
        await self._session.commit()
        await self._session.refresh(instance)
        try:
            dispatcher.start_environment_provision(instance.id)
        except Exception as error:
            logger.exception(
                "Environment provision dispatch failed",
                extra={"environment_instance_id": str(instance.id)},
            )
            instance.status = "failed"
            instance.error_code = "ENVIRONMENT_QUEUE_UNAVAILABLE"
            instance.error_message = "环境任务队列暂时不可用"
            await self._session.commit()
            raise AppError(
                code="ENVIRONMENT_QUEUE_UNAVAILABLE",
                message="环境任务队列暂时不可用",
                status_code=503,
            ) from error
        return instance

    async def list_instances(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[EnvironmentInstance], int]:
        EnvironmentTemplateService._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_instances(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def get(self, *, actor: User, project_id: UUID, instance_id: UUID) -> EnvironmentInstance:
        EnvironmentTemplateService._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        instance = await self._repository.get_instance(instance_id)
        if instance is None or instance.project_id != project_id:
            raise _instance_not_found()
        return instance

    async def cancel(
        self,
        *,
        actor: User,
        project_id: UUID,
        instance_id: UUID,
        dispatcher: EnvironmentTaskDispatcher,
    ) -> EnvironmentInstance:
        EnvironmentTemplateService._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        instance = await self._repository.get_instance_for_update(instance_id)
        if instance is None or instance.project_id != project_id:
            raise _instance_not_found()
        if instance.cleanup_status == "completed":
            return instance
        now = datetime.now(UTC)
        instance.status = "cancelled"
        instance.cancellation_requested_at = now
        instance.cleanup_status = "pending"
        instance.fencing_token += 1
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="environment_instance.cancelled",
            resource_type="environment_instance",
            resource_id=instance.id,
        )
        await self._session.commit()
        await self._session.refresh(instance)
        try:
            dispatcher.start_environment_cleanup(instance.id)
        except Exception:
            logger.exception(
                "Environment cleanup dispatch failed",
                extra={"environment_instance_id": str(instance.id)},
            )
        return instance

    def _verify_snapshot(
        self,
        template: EnvironmentTemplate,
        version: EnvironmentTemplateVersion,
        manifest: EnvironmentTemplateManifest,
    ) -> None:
        EnvironmentTemplateService._validate_images(manifest)
        valid = manifest.sha256 == version.manifest_sha256 and self._signer.verify(
            template_key=template.template_key,
            version=version.version,
            manifest_sha256=version.manifest_sha256,
            signature=version.signature,
        )
        if not valid or version.signature_algorithm != self._signer.algorithm:
            raise AppError(
                code="ENVIRONMENT_TEMPLATE_SIGNATURE_INVALID",
                message="环境模板签名验证失败",
                status_code=409,
            )


class EnvironmentRunCoordinator:
    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        runtime: EnvironmentRuntime,
    ) -> None:
        self._session_maker = session_maker
        self._runtime = runtime
        self._signer = _template_signer()

    async def provision(self, instance_id: UUID) -> None:
        plan = await self._claim_provision(instance_id)
        if plan is None:
            await self.cleanup(instance_id)
            return
        try:
            self._verify_plan(plan)
            await self._runtime.cleanup(instance_id)
            async with asyncio.timeout(settings.environment_provision_timeout_seconds):
                provisioned = await self._runtime.provision(instance_id, plan.manifest)
                if not await self._is_current(plan):
                    await self._runtime.cleanup(instance_id)
                    return
                seed_evidence = await self._runtime.apply_seeds(
                    provisioned,
                    plan.manifest.seeds,
                )
            if not await self._mark_ready(plan, provisioned, seed_evidence):
                await self._runtime.cleanup(instance_id)
        except TimeoutError:
            await self._fail_and_cleanup(
                plan,
                code="ENVIRONMENT_PROVISION_TIMEOUT",
                message="环境 Provision 超时",
            )
        except EnvironmentRuntimeError as error:
            await self._fail_and_cleanup(plan, code=error.code, message=error.message)
        except AppError as error:
            await self._fail_and_cleanup(plan, code=error.code, message=error.message)
        except Exception:
            logger.exception(
                "Environment runner failed",
                extra={"environment_instance_id": str(instance_id)},
            )
            await self._fail_and_cleanup(
                plan,
                code="ENVIRONMENT_RUNNER_FAILED",
                message="环境 Runner 执行失败",
            )

    async def cleanup(self, instance_id: UUID) -> None:
        claimed = await self._claim_cleanup(instance_id)
        if not claimed:
            return
        try:
            async with asyncio.timeout(settings.environment_cleanup_timeout_seconds):
                await self._runtime.cleanup(instance_id)
        except Exception as error:
            await self._mark_cleanup_failed(instance_id, error)
            return
        await self._mark_cleanup_completed(instance_id)

    async def _claim_provision(self, instance_id: UUID) -> EnvironmentProvisionPlan | None:
        async with self._session_maker() as session:
            instance = await EnvironmentLabRepository(session).get_instance_for_update(instance_id)
            if instance is None or instance.status not in {"queued", "provisioning"}:
                return None
            now = datetime.now(UTC)
            if (
                instance.cancellation_requested_at is not None
                or _as_utc(instance.expires_at) <= now
            ):
                instance.status = (
                    "cancelled" if instance.cancellation_requested_at is not None else "expired"
                )
                instance.cleanup_status = "pending"
                await session.commit()
                return None
            if instance.status == "provisioning":
                instance.fencing_token += 1
            instance.status = "provisioning"
            instance.cleanup_status = "none"
            instance.started_at = now
            manifest = EnvironmentTemplateManifest.model_validate(instance.manifest_snapshot)
            await session.commit()
            return EnvironmentProvisionPlan(
                instance_id=instance.id,
                project_id=instance.project_id,
                template_key=instance.template_key,
                template_version=instance.template_version,
                manifest=manifest,
                manifest_sha256=instance.manifest_sha256,
                signature=instance.signature,
                fencing_token=instance.fencing_token,
            )

    async def _is_current(self, plan: EnvironmentProvisionPlan) -> bool:
        async with self._session_maker() as session:
            instance = await EnvironmentLabRepository(session).get_instance(plan.instance_id)
            return bool(
                instance is not None
                and instance.status == "provisioning"
                and instance.fencing_token == plan.fencing_token
                and instance.cancellation_requested_at is None
                and _as_utc(instance.expires_at) > datetime.now(UTC)
            )

    async def _mark_ready(
        self,
        plan: EnvironmentProvisionPlan,
        provisioned: ProvisionedEnvironment,
        seed_evidence: tuple[EnvironmentSeedEvidence, ...],
    ) -> bool:
        async with self._session_maker() as session:
            instance = await EnvironmentLabRepository(session).get_instance_for_update(
                plan.instance_id
            )
            if instance is None or not _matches_fencing(instance, plan):
                return False
            instance.status = "ready"
            instance.cleanup_status = "none"
            instance.endpoints = [item.model_dump(mode="json") for item in provisioned.endpoints]
            instance.seed_evidence = [item.model_dump(mode="json") for item in seed_evidence]
            instance.ready_at = datetime.now(UTC)
            instance.error_code = None
            instance.error_message = None
            await session.commit()
            return True

    async def _fail_and_cleanup(
        self, plan: EnvironmentProvisionPlan, *, code: str, message: str
    ) -> None:
        cleanup_error: Exception | None = None
        try:
            async with asyncio.timeout(settings.environment_cleanup_timeout_seconds):
                await self._runtime.cleanup(plan.instance_id)
        except Exception as error:
            cleanup_error = error
            logger.exception(
                "Environment cleanup after failure failed",
                extra={"environment_instance_id": str(plan.instance_id)},
            )
        async with self._session_maker() as session:
            instance = await EnvironmentLabRepository(session).get_instance_for_update(
                plan.instance_id
            )
            if instance is None:
                return
            if instance.fencing_token == plan.fencing_token and instance.status == "provisioning":
                instance.status = "failed"
                instance.error_code = code[:64]
                instance.error_message = message[:500]
            instance.cleanup_attempts += 1
            instance.cleanup_status = "failed" if cleanup_error else "completed"
            instance.cleanup_error_code = "ENVIRONMENT_CLEANUP_FAILED" if cleanup_error else None
            if cleanup_error is None:
                instance.cleaned_at = datetime.now(UTC)
            await session.commit()

    async def _claim_cleanup(self, instance_id: UUID) -> bool:
        async with self._session_maker() as session:
            instance = await EnvironmentLabRepository(session).get_instance_for_update(instance_id)
            if instance is None or instance.cleanup_status == "completed":
                return False
            now = datetime.now(UTC)
            eligible = (
                instance.cleanup_status in {"pending", "failed"}
                or instance.cancellation_requested_at is not None
                or _as_utc(instance.expires_at) <= now
            )
            if not eligible:
                return False
            if instance.cancellation_requested_at is not None:
                instance.status = "cancelled"
            elif _as_utc(instance.expires_at) <= now:
                instance.status = "expired"
            elif instance.status == "ready":
                instance.status = "cleaned"
            instance.fencing_token += 1
            instance.cleanup_status = "running"
            instance.cleanup_attempts += 1
            instance.cleanup_started_at = now
            await session.commit()
            return True

    async def _mark_cleanup_completed(self, instance_id: UUID) -> None:
        async with self._session_maker() as session:
            instance = await EnvironmentLabRepository(session).get_instance_for_update(instance_id)
            if instance is None:
                return
            instance.cleanup_status = "completed"
            instance.cleanup_error_code = None
            instance.cleaned_at = datetime.now(UTC)
            if instance.status in {"queued", "provisioning", "ready"}:
                instance.status = "cleaned"
            await session.commit()

    async def _mark_cleanup_failed(self, instance_id: UUID, error: Exception) -> None:
        logger.exception(
            "Environment cleanup failed",
            extra={"environment_instance_id": str(instance_id)},
            exc_info=error,
        )
        async with self._session_maker() as session:
            instance = await EnvironmentLabRepository(session).get_instance_for_update(instance_id)
            if instance is None:
                return
            instance.cleanup_status = "failed"
            instance.cleanup_error_code = "ENVIRONMENT_CLEANUP_FAILED"
            await session.commit()

    def _verify_plan(self, plan: EnvironmentProvisionPlan) -> None:
        EnvironmentTemplateService._validate_images(plan.manifest)
        valid = plan.manifest.sha256 == plan.manifest_sha256 and self._signer.verify(
            template_key=plan.template_key,
            version=plan.template_version,
            manifest_sha256=plan.manifest_sha256,
            signature=plan.signature,
        )
        if not valid:
            raise AppError(
                code="ENVIRONMENT_TEMPLATE_SIGNATURE_INVALID",
                message="环境模板签名验证失败",
                status_code=409,
            )


class EnvironmentReconciliationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = EnvironmentLabRepository(session)

    async def dispatch_due(self, dispatcher: EnvironmentTaskDispatcher) -> int:
        now = datetime.now(UTC)
        stale_at = now - timedelta(seconds=settings.environment_provision_timeout_seconds)
        candidates = await self._repository.list_reconciliation_candidates(
            now=now,
            stale_at=stale_at,
            limit=100,
        )
        operations: list[tuple[str, UUID]] = []
        for instance in candidates:
            if _as_utc(instance.expires_at) <= now:
                instance.status = "expired"
                instance.cleanup_status = "pending"
                instance.fencing_token += 1
                operations.append(("cleanup", instance.id))
            elif instance.cleanup_status in {"pending", "failed"}:
                operations.append(("cleanup", instance.id))
            else:
                operations.append(("provision", instance.id))
        await self._session.commit()
        for operation, instance_id in operations:
            if operation == "cleanup":
                dispatcher.start_environment_cleanup(instance_id)
            else:
                dispatcher.start_environment_provision(instance_id)
        return len(operations)


def _signature_payload(template_key: str, version: int, manifest_sha256: str) -> bytes:
    return json.dumps(
        {
            "manifest_sha256": manifest_sha256,
            "template_key": template_key,
            "version": version,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _template_signer() -> EnvironmentTemplateSigner:
    return EnvironmentTemplateSigner(
        f"flowtest-environment-template-v1:{settings.data_encryption_key}"
    )


def _runtime_name(instance_id: UUID) -> str:
    return f"flowtest-env-{instance_id.hex}"


def _matches_fencing(instance: EnvironmentInstance | None, plan: EnvironmentProvisionPlan) -> bool:
    return bool(
        instance is not None
        and instance.status == "provisioning"
        and instance.fencing_token == plan.fencing_token
        and instance.cancellation_requested_at is None
        and _as_utc(instance.expires_at) > datetime.now(UTC)
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _template_not_found() -> AppError:
    return AppError(
        code="ENVIRONMENT_TEMPLATE_NOT_FOUND",
        message="环境模板不存在",
        status_code=404,
    )


def _instance_not_found() -> AppError:
    return AppError(
        code="ENVIRONMENT_INSTANCE_NOT_FOUND",
        message="环境实例不存在",
        status_code=404,
    )
