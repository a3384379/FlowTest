"""Organization governance, quota enforcement and key lifecycle services."""

# Product copy intentionally uses Chinese punctuation.
# ruff: noqa: RUF001

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time
from hmac import compare_digest
from typing import Any, cast
from uuid import UUID

from cryptography.exceptions import InvalidTag
from sqlalchemy import Table, func, insert, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Insert

from app.core.encryption import DEFAULT_KEY_REFERENCE, SecretBox, secret_box
from app.core.errors import AppError
from app.domain.governance import (
    DEFAULT_QUOTA_POLICIES,
    QuotaDecision,
    QuotaDimension,
    QuotaRule,
    parse_quota_policies,
)
from app.models.access import AuditLog, Project, User
from app.models.ai import AIJob
from app.models.artifacts import Artifact
from app.models.capabilities import Runner, RunnerPool
from app.models.governance import OrganizationGovernance, OrganizationKeyVersion
from app.models.organizations import Organization
from app.models.workflows import WorkflowExecution
from app.repositories.organizations import OrganizationRepository
from app.schemas.governance import RunnerGovernancePolicy
from app.services.audit import AuditService
from app.services.organizations import OrganizationService

DEFAULT_RUNNER_POLICY: dict[str, Any] = {
    "allowed_runner_types": ["general", "data", "protocol", "performance", "environment"],
    "allowed_runtimes": ["docker", "kubernetes"],
    "max_pools": 20,
    "registration_requires_approval": False,
}
SUPPORT_BUNDLE_SCHEMA = "s44-redacted-support-bundle-v1"


@dataclass(frozen=True, slots=True)
class GovernanceRecords:
    policy: OrganizationGovernance
    key_versions: list[OrganizationKeyVersion]


class OrganizationGovernanceService:
    def __init__(self, session: AsyncSession, *, secrets: SecretBox = secret_box) -> None:
        self._session = session
        self._secrets = secrets
        self._organizations = OrganizationRepository(session)
        self._orgs = OrganizationService(session)
        self._audit = AuditService(session)

    async def get(self, *, actor: User, organization_id: UUID) -> OrganizationGovernance:
        await self._orgs.authorize(actor=actor, organization_id=organization_id, capability="read")
        policy, _created = await self._ensure_records(organization_id, actor.id)
        return policy

    async def update(
        self,
        *,
        actor: User,
        organization_id: UUID,
        audit_retention_days: int | None,
        quota_policies: dict[str, QuotaRule] | None,
        runner_policy: RunnerGovernancePolicy | None,
    ) -> OrganizationGovernance:
        organization = await self._orgs.authorize(
            actor=actor,
            organization_id=organization_id,
            capability="manage_governance",
        )
        policy, _created = await self._ensure_records(organization_id, actor.id)
        if audit_retention_days is not None:
            policy.audit_retention_days = audit_retention_days
        if quota_policies is not None:
            policy.quota_policies = _serialize_quota_policies(quota_policies)
        if runner_policy is not None:
            policy.runner_policy = runner_policy.model_dump(mode="json")
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=organization.organization.id,
            project_id=None,
            action="organization.governance_updated",
            resource_type="organization_governance",
            resource_id=organization.organization.id,
            details={
                "audit_retention_days": policy.audit_retention_days,
                "quota_dimensions": sorted(parse_quota_policies(policy.quota_policies)),
                "runner_policy_updated": runner_policy is not None,
            },
        )
        await self._session.commit()
        await self._session.refresh(policy)
        return policy

    async def list_audit_logs(
        self,
        *,
        actor: User,
        organization_id: UUID,
        action: str | None,
        resource_type: str | None,
        created_from: datetime | None,
        created_to: datetime | None,
        offset: int,
        limit: int,
    ) -> tuple[list[AuditLog], int]:
        await self._orgs.authorize(
            actor=actor, organization_id=organization_id, capability="view_audit"
        )
        filters = [AuditLog.organization_id == organization_id]
        if action:
            filters.append(AuditLog.action == action)
        if resource_type:
            filters.append(AuditLog.resource_type == resource_type)
        if created_from:
            filters.append(AuditLog.created_at >= created_from)
        if created_to:
            filters.append(AuditLog.created_at <= created_to)
        logs = list(
            (
                await self._session.scalars(
                    select(AuditLog)
                    .where(*filters)
                    .order_by(AuditLog.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(AuditLog).where(*filters)
        )
        return logs, int(total or 0)

    async def runner_summary(
        self, *, actor: User, organization_id: UUID
    ) -> tuple[list[RunnerPool], dict[UUID, tuple[int, int]]]:
        await self._orgs.authorize(actor=actor, organization_id=organization_id, capability="read")
        pools = list(
            (
                await self._session.scalars(
                    select(RunnerPool)
                    .where(RunnerPool.organization_id == organization_id)
                    .order_by(RunnerPool.created_at.desc())
                )
            ).all()
        )
        rows = await self._session.execute(
            select(
                Runner.pool_id,
                func.count(Runner.id),
                func.coalesce(func.sum(Runner.current_load), 0),
            )
            .join(RunnerPool, RunnerPool.id == Runner.pool_id)
            .where(RunnerPool.organization_id == organization_id)
            .group_by(Runner.pool_id)
        )
        return pools, {pool_id: (int(count), int(load)) for pool_id, count, load in rows.tuples()}

    async def security(self, *, actor: User, organization_id: UUID) -> GovernanceRecords:
        await self._orgs.authorize(actor=actor, organization_id=organization_id, capability="read")
        policy, _created = await self._ensure_records(organization_id, actor.id)
        versions = list(
            (
                await self._session.scalars(
                    select(OrganizationKeyVersion)
                    .where(OrganizationKeyVersion.organization_id == organization_id)
                    .order_by(OrganizationKeyVersion.version.desc())
                )
            ).all()
        )
        return GovernanceRecords(policy=policy, key_versions=versions)

    async def prepare_key_rotation(
        self,
        *,
        actor: User,
        organization_id: UUID,
        key_reference: str,
        key_fingerprint: str,
    ) -> OrganizationKeyVersion:
        organization = await self._orgs.authorize(
            actor=actor, organization_id=organization_id, capability="rotate_keys"
        )
        policy, _created = await self._ensure_records(organization_id, actor.id)
        active = await self._active_key(organization_id, policy.active_key_version)
        normalized_fingerprint = key_fingerprint.lower()
        if not self._secrets.has_reference(key_reference.strip()):
            raise AppError(
                code="KEY_ROTATION_KEY_UNAVAILABLE",
                message="新密钥引用未在服务端 Keyring 中配置",
                status_code=409,
            )
        actual_fingerprint = self._secrets.fingerprint(key_reference.strip())
        if not compare_digest(normalized_fingerprint, actual_fingerprint):
            raise AppError(
                code="KEY_ROTATION_FINGERPRINT_MISMATCH",
                message="新密钥指纹与服务端 Keyring 不匹配",
                status_code=409,
            )
        if compare_digest(active.key_fingerprint, normalized_fingerprint):
            raise AppError(
                code="KEY_ROTATION_SAME_FINGERPRINT",
                message="新密钥指纹不能与当前密钥相同",
                status_code=409,
            )
        pending = await self._session.scalar(
            select(OrganizationKeyVersion).where(
                OrganizationKeyVersion.organization_id == organization_id,
                OrganizationKeyVersion.status == "pending",
            )
        )
        if pending is not None:
            raise AppError(
                code="KEY_ROTATION_ALREADY_PENDING",
                message="组织已有待迁移的密钥版本",
                status_code=409,
            )
        next_version = (
            int(
                await self._session.scalar(
                    select(func.coalesce(func.max(OrganizationKeyVersion.version), 0)).where(
                        OrganizationKeyVersion.organization_id == organization_id
                    )
                )
                or 0
            )
            + 1
        )
        version = OrganizationKeyVersion(
            organization_id=organization_id,
            version=next_version,
            key_reference=key_reference.strip(),
            key_fingerprint=normalized_fingerprint,
            status="pending",
            migration_status="planned",
            previous_version=active.version,
            created_by_id=actor.id,
        )
        self._session.add(version)
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=organization.organization.id,
            project_id=None,
            action="organization.key_rotation_prepared",
            resource_type="organization_key_version",
            resource_id=version.id,
            details={"version": next_version, "key_fingerprint": normalized_fingerprint},
        )
        await self._session.commit()
        await self._session.refresh(version)
        return version

    async def apply_key_rotation(
        self, *, actor: User, organization_id: UUID, key_version_id: UUID
    ) -> OrganizationKeyVersion:
        organization = await self._orgs.authorize(
            actor=actor, organization_id=organization_id, capability="rotate_keys"
        )
        await self._ensure_records(organization_id, actor.id)
        policy = await self._locked_policy(organization_id)
        version = await self._get_key_version(organization_id, key_version_id)
        if version.status != "pending" or version.migration_status != "planned":
            raise AppError(
                code="KEY_LIFECYCLE_PLAN_NOT_PENDING",
                message="Key Lifecycle Plan 不在待确认状态",
                status_code=409,
            )
        if version.previous_version != policy.active_key_version:
            raise AppError(
                code="KEY_ROTATION_STALE_PLAN",
                message="当前活动密钥已变化，请重新创建轮换计划",
                status_code=409,
            )
        self._validate_available_key(version)
        previous = await self._active_key(organization_id, policy.active_key_version)
        version.migration_status = "migrating"
        await self._session.flush()
        try:
            from app.services.key_rotation import reencrypt_organization_ciphertexts

            evidence = await reencrypt_organization_ciphertexts(
                self._session,
                organization_id=organization_id,
                target_key_reference=version.key_reference,
                secrets=self._secrets,
            )
        except (InvalidTag, UnicodeDecodeError, ValueError) as error:
            await self._session.rollback()
            raise AppError(
                code="KEY_ROTATION_REENCRYPTION_FAILED",
                message="组织密文重加密或校验失败，事务已回滚",
                status_code=409,
            ) from error
        now = datetime.now(UTC)
        previous.status = "retiring"
        version.status = "active"
        version.migration_status = "migrated"
        version.migrated_at = now
        version.activated_at = now
        policy.active_key_version = version.version
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=organization.organization.id,
            project_id=None,
            action="organization.key_rotation_applied",
            resource_type="organization_key_version",
            resource_id=version.id,
            details={
                "version": version.version,
                "previous_version": previous.version,
                "migrated": evidence.total,
                "verified": evidence.verified,
                "resource_counts": evidence.resource_counts,
                "ciphertext_digest": evidence.ciphertext_digest,
            },
        )
        await self._session.commit()
        await self._session.refresh(version)
        return version

    async def rollback_key_rotation(
        self, *, actor: User, organization_id: UUID, key_version_id: UUID
    ) -> OrganizationKeyVersion:
        organization = await self._orgs.authorize(
            actor=actor, organization_id=organization_id, capability="rotate_keys"
        )
        await self._ensure_records(organization_id, actor.id)
        policy = await self._locked_policy(organization_id)
        version = await self._get_key_version(organization_id, key_version_id)
        if (
            version.status != "active"
            or version.migration_status != "migrated"
            or policy.active_key_version != version.version
            or version.previous_version is None
        ):
            raise AppError(
                code="KEY_ROTATION_NOT_ROLLBACKABLE",
                message="密钥版本不是当前可回滚的活动版本",
                status_code=409,
            )
        previous = await self._active_key(organization_id, version.previous_version)
        self._validate_available_key(previous)
        try:
            from app.services.key_rotation import reencrypt_organization_ciphertexts

            evidence = await reencrypt_organization_ciphertexts(
                self._session,
                organization_id=organization_id,
                target_key_reference=previous.key_reference,
                secrets=self._secrets,
            )
        except (InvalidTag, UnicodeDecodeError, ValueError) as error:
            await self._session.rollback()
            raise AppError(
                code="KEY_ROTATION_ROLLBACK_FAILED",
                message="组织密文回滚重加密或校验失败，事务已回滚",
                status_code=409,
            ) from error
        now = datetime.now(UTC)
        version.status = "rolled_back"
        version.migration_status = "rolled_back"
        version.rolled_back_at = now
        previous.status = "active"
        policy.active_key_version = previous.version
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=organization.organization.id,
            project_id=None,
            action="organization.key_rotation_rolled_back",
            resource_type="organization_key_version",
            resource_id=version.id,
            details={
                "version": version.version,
                "restored_version": previous.version,
                "migrated": evidence.total,
                "verified": evidence.verified,
                "resource_counts": evidence.resource_counts,
                "ciphertext_digest": evidence.ciphertext_digest,
            },
        )
        await self._session.commit()
        await self._session.refresh(version)
        return version

    async def support_bundle_redaction(
        self, *, actor: User, organization_id: UUID
    ) -> dict[str, object]:
        await self._orgs.authorize(actor=actor, organization_id=organization_id, capability="read")
        manifest: dict[str, object] = {
            "organization_id": organization_id,
            "schema_version": SUPPORT_BUNDLE_SCHEMA,
            "data_classification": "internal-redacted",
            "included_sections": ["runtime_profile", "migrations", "audit_summary", "health"],
            "redacted_fields": [
                "authorization",
                "cookies",
                "service_account_token",
                "request_headers",
                "request_body",
            ],
            "excluded_fields": [
                "password_hash",
                "data_encryption_key",
                "secret_value",
                "ciphertext",
                "private_key",
            ],
        }
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=organization_id,
            project_id=None,
            action="support_bundle.redaction_previewed",
            resource_type="support_bundle",
            resource_id=organization_id,
            details={"schema_version": SUPPORT_BUNDLE_SCHEMA},
        )
        await self._session.commit()
        return manifest

    async def _ensure_records(
        self, organization_id: UUID, actor_id: UUID
    ) -> tuple[OrganizationGovernance, bool]:
        organization = await self._organizations.get(organization_id)
        if organization is None or not organization.enabled:
            raise AppError(code="ORGANIZATION_NOT_FOUND", message="组织不存在", status_code=404)
        policy = await self._session.get(OrganizationGovernance, organization_id)
        created = policy is None
        if policy is None:
            created = await self._insert_if_absent(
                cast(Table, OrganizationGovernance.__table__),
                {
                    "organization_id": organization_id,
                    "quota_policies": dict(DEFAULT_QUOTA_POLICIES),
                    "runner_policy": dict(DEFAULT_RUNNER_POLICY),
                },
                conflict_columns=("organization_id",),
            )
            policy = await self._session.get(OrganizationGovernance, organization_id)
            if policy is None:
                raise AppError(
                    code="ORGANIZATION_GOVERNANCE_INIT_FAILED",
                    message="组织治理策略初始化失败",
                    status_code=503,
                )
        initial_key = await self._session.scalar(
            select(OrganizationKeyVersion).where(
                OrganizationKeyVersion.organization_id == organization_id,
                OrganizationKeyVersion.version == 1,
            )
        )
        key_created = initial_key is None
        if key_created:
            now = datetime.now(UTC)
            key_created = await self._insert_if_absent(
                cast(Table, OrganizationKeyVersion.__table__),
                {
                    "organization_id": organization_id,
                    "version": 1,
                    "key_reference": DEFAULT_KEY_REFERENCE,
                    "key_fingerprint": self._secrets.fingerprint(DEFAULT_KEY_REFERENCE),
                    "status": "active",
                    "migration_status": "migrated",
                    "created_by_id": actor_id,
                    "activated_at": now,
                    "migrated_at": now,
                },
                conflict_columns=("organization_id", "version"),
            )
        if created or key_created:
            await self._session.commit()
            await self._session.refresh(policy)
        return policy, created or key_created

    async def _insert_if_absent(
        self,
        table: Table,
        values: Mapping[str, Any],
        *,
        conflict_columns: Sequence[str],
    ) -> bool:
        dialect = self._session.get_bind().dialect.name
        statement: Insert
        if dialect == "postgresql":
            statement = (
                postgresql_insert(table)
                .values(dict(values))
                .on_conflict_do_nothing(index_elements=list(conflict_columns))
            )
        elif dialect == "sqlite":
            statement = (
                sqlite_insert(table)
                .values(dict(values))
                .on_conflict_do_nothing(index_elements=list(conflict_columns))
            )
        else:
            statement = insert(table).values(dict(values))
        result = await self._session.execute(statement)
        await self._session.flush()
        return bool(getattr(result, "rowcount", 0))

    async def _active_key(self, organization_id: UUID, version: int) -> OrganizationKeyVersion:
        key = await self._session.scalar(
            select(OrganizationKeyVersion).where(
                OrganizationKeyVersion.organization_id == organization_id,
                OrganizationKeyVersion.version == version,
            )
        )
        if key is None:
            raise AppError(
                code="ACTIVE_KEY_VERSION_NOT_FOUND", message="当前密钥版本不存在", status_code=409
            )
        return key

    async def _locked_policy(self, organization_id: UUID) -> OrganizationGovernance:
        policy = await self._session.scalar(
            select(OrganizationGovernance)
            .where(OrganizationGovernance.organization_id == organization_id)
            .with_for_update()
        )
        if policy is None:
            raise AppError(
                code="ORGANIZATION_GOVERNANCE_NOT_FOUND",
                message="组织治理策略不存在",
                status_code=409,
            )
        return policy

    def _validate_available_key(self, version: OrganizationKeyVersion) -> None:
        if not self._secrets.has_reference(version.key_reference):
            raise AppError(
                code="KEY_ROTATION_KEY_UNAVAILABLE",
                message="密钥引用未在服务端 Keyring 中配置",
                status_code=409,
            )
        actual_fingerprint = self._secrets.fingerprint(version.key_reference)
        if not compare_digest(actual_fingerprint, version.key_fingerprint):
            raise AppError(
                code="KEY_ROTATION_FINGERPRINT_MISMATCH",
                message="密钥指纹与服务端 Keyring 不匹配",
                status_code=409,
            )

    async def _get_key_version(
        self, organization_id: UUID, key_version_id: UUID
    ) -> OrganizationKeyVersion:
        key = await self._session.get(OrganizationKeyVersion, key_version_id)
        if key is None or key.organization_id != organization_id:
            raise AppError(code="KEY_VERSION_NOT_FOUND", message="密钥版本不存在", status_code=404)
        return key


class OrganizationQuotaService:
    """Read organization usage and apply its mode-specific quota decision."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enforce(
        self,
        *,
        organization_id: UUID | None,
        dimension: QuotaDimension,
        increment: int = 1,
    ) -> QuotaDecision | None:
        if organization_id is None:
            return None
        await self._lock_organization(organization_id)
        usage = await self._usage(organization_id, dimension)
        policy = await self._session.get(OrganizationGovernance, organization_id)
        rules = parse_quota_policies(policy.quota_policies if policy else {})
        decision = replace(
            rules[dimension.value].evaluate(usage + increment), dimension=dimension.value
        )
        if decision.blocked:
            raise AppError(
                code="ORGANIZATION_QUOTA_EXCEEDED",
                message="组织配额已达到硬限制",
                status_code=429,
                details={
                    "dimension": decision.dimension,
                    "mode": decision.mode.value,
                    "usage": decision.usage,
                    "limit": decision.limit,
                },
            )
        return decision

    async def _lock_organization(self, organization_id: UUID) -> None:
        await self._session.scalar(
            select(Organization.id).where(Organization.id == organization_id).with_for_update()
        )

    async def validate_runner_pool(
        self, *, organization_id: UUID | None, runner_type: str, runtime: str
    ) -> None:
        if organization_id is None:
            return
        policy = await self._session.get(OrganizationGovernance, organization_id)
        runner_policy = RunnerGovernancePolicy.model_validate(
            policy.runner_policy if policy is not None else DEFAULT_RUNNER_POLICY
        )
        if runner_type not in runner_policy.allowed_runner_types:
            raise AppError(
                code="RUNNER_TYPE_NOT_ALLOWED",
                message="组织 Runner 治理策略不允许该 Runner 类型",
                status_code=403,
            )
        if runtime not in runner_policy.allowed_runtimes:
            raise AppError(
                code="RUNNER_RUNTIME_NOT_ALLOWED",
                message="组织 Runner 治理策略不允许该 Runtime",
                status_code=403,
            )
        pool_count = await self._session.scalar(
            select(func.count())
            .select_from(RunnerPool)
            .where(RunnerPool.organization_id == organization_id)
        )
        if int(pool_count or 0) >= runner_policy.max_pools:
            raise AppError(
                code="RUNNER_POOL_QUOTA_EXCEEDED",
                message="组织 Runner Pool 数量已达到治理上限",
                status_code=429,
                details={"limit": runner_policy.max_pools},
            )

    async def _usage(self, organization_id: UUID, dimension: QuotaDimension) -> int:
        if dimension is QuotaDimension.PROJECT_COUNT:
            value = await self._session.scalar(
                select(func.count())
                .select_from(Project)
                .where(Project.organization_id == organization_id)
            )
        elif dimension is QuotaDimension.USER_COUNT:
            from app.models.organizations import OrganizationMember

            value = await self._session.scalar(
                select(func.count())
                .select_from(OrganizationMember)
                .where(OrganizationMember.organization_id == organization_id)
            )
        elif dimension is QuotaDimension.RUNNER_CONCURRENCY:
            value = await self._session.scalar(
                select(func.coalesce(func.sum(Runner.current_load), 0))
                .join(RunnerPool, RunnerPool.id == Runner.pool_id)
                .where(RunnerPool.organization_id == organization_id)
            )
        elif dimension is QuotaDimension.EXECUTION_CONCURRENCY:
            value = await self._session.scalar(
                select(func.count())
                .select_from(WorkflowExecution)
                .join(Project, Project.id == WorkflowExecution.project_id)
                .where(
                    Project.organization_id == organization_id,
                    WorkflowExecution.parent_execution_id.is_(None),
                    WorkflowExecution.status == "running",
                )
            )
        elif dimension is QuotaDimension.AI_REQUEST_COUNT:
            start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
            value = await self._session.scalar(
                select(func.count())
                .select_from(AIJob)
                .join(Project, Project.id == AIJob.project_id)
                .where(Project.organization_id == organization_id, AIJob.created_at >= start)
            )
        else:
            value = await self._session.scalar(
                select(func.coalesce(func.sum(Artifact.size_bytes), 0))
                .join(Project, Project.id == Artifact.project_id)
                .where(Project.organization_id == organization_id)
            )
        return int(value or 0)


def _serialize_quota_policies(policies: dict[str, QuotaRule]) -> dict[str, dict[str, Any]]:
    return {
        dimension: {
            "mode": rule.mode.value,
            "limit": rule.limit,
            "warn_at": rule.warn_at,
        }
        for dimension, rule in policies.items()
    }
