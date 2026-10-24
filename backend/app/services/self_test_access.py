"""One authorization boundary for user selection and deployment-owned external workers."""

import hashlib
import hmac
from datetime import UTC, datetime
from uuid import UUID

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.self_tests import SelfTestBinding, SelfTestPrincipal, SelfTestSettings
from app.domain.self_tests import aware, document_digest
from app.models.access import User
from app.models.self_tests import SelfTestBatch, SelfTestInstallation
from app.repositories.self_tests import SelfTestRepository
from app.schemas.self_tests import LeaseRequest, TemplateResponse
from app.services.projects import ProjectService
from app.services.self_test_catalog import templates


def self_test_error(code: str, message: str, status: int = 409) -> AppError:
    return AppError(code=code, message=message, status_code=status)


def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def authenticate_agent(token: str, config: SelfTestSettings) -> SelfTestPrincipal:
    for principal in config.principals:
        try:
            claims = jwt.decode(
                token,
                principal.public_key,
                algorithms=[principal.algorithm],
                issuer=principal.issuer,
                audience=principal.audience,
                options={"require": ["iss", "sub", "aud", "iat", "exp", "nbf"]},
            )
            valid = claims["sub"] == principal.subject and 0 < claims["exp"] - claims["iat"] <= 3600
            if valid:
                return principal
        except (jwt.InvalidTokenError, TypeError, ValueError):
            continue
    raise self_test_error("SELFTEST_AGENT_UNAUTHORIZED", "外部自测身份无效", 401)


class SelfTestAccess:
    def __init__(self, session: AsyncSession, config: SelfTestSettings) -> None:
        self.session, self.config = session, config
        self.repository = SelfTestRepository(session)

    def catalog(self) -> tuple[TemplateResponse, ...]:
        values = (*templates(), *self.config.extra_templates)
        if len({item.id for item in values}) != len(values):
            raise self_test_error("SELFTEST_CATALOG_INVALID", "模板目录存在重复身份", 503)
        return values

    def template(self, identifier: str, version: str) -> TemplateResponse:
        found = next(
            (item for item in self.catalog() if (item.id, item.version) == (identifier, version)),
            None,
        )
        if found is None:
            raise self_test_error("SELFTEST_TEMPLATE_NOT_FOUND", "模板版本未登记", 404)
        return found

    def binding(self, project_id: UUID, identifier: UUID) -> SelfTestBinding:
        found = next(
            (
                item
                for item in self.config.bindings
                if item.id == identifier and project_id in item.allowed_project_ids
            ),
            None,
        )
        if found is None:
            raise self_test_error("SELFTEST_BINDING_NOT_FOUND", "目标绑定不存在或未授权", 404)
        return found

    def safe_binding(self, binding: SelfTestBinding) -> None:
        if self.config.fixture_run_depth >= 1:
            raise self_test_error(
                "SELFTEST_RECURSION_LIMIT_REACHED", "业务夹具实例不能继续发起系统自测", 403
            )
        if not all(
            (binding.enabled, binding.non_production, binding.isolated, binding.outbound_authorized)
        ):
            raise self_test_error(
                "SELFTEST_BINDING_UNSAFE", "目标的隔离、非生产或出站证明不完整", 403
            )
        if binding.runner_instance_id == binding.target_instance_id:
            raise self_test_error("SELFTEST_BINDING_NOT_ISOLATED", "A/B 必须为不同实例", 403)

    async def installation(self, project_id: UUID, identifier: UUID) -> SelfTestInstallation:
        model = await self.repository.installation(project_id, identifier)
        if model is None:
            raise self_test_error("SELFTEST_INSTALLATION_NOT_FOUND", "自测安装不存在", 404)
        return model

    async def batch(self, project_id: UUID, identifier: UUID) -> SelfTestBatch:
        model = await self.repository.batch(project_id, identifier)
        if model is None:
            raise self_test_error("SELFTEST_BATCH_NOT_FOUND", "自测批次不存在", 404)
        return model

    async def actor(self, identifier: UUID, project_id: UUID, *, editing: bool) -> User:
        actor = await self.session.get(User, identifier)
        if actor is None or not actor.is_active:
            raise self_test_error("SELFTEST_ACTOR_INACTIVE", "批次操作主体已不可用", 403)
        await ProjectService(self.session).authorize(
            actor=actor, project_id=project_id, editing=editing
        )
        return actor

    def agent_binding(
        self, principal: SelfTestPrincipal, project_id: UUID, binding_id: UUID, capability: str
    ) -> SelfTestBinding:
        allowed = (
            project_id in principal.allowed_project_ids
            and binding_id in principal.allowed_binding_ids
            and capability in principal.capabilities
        )
        if not allowed:
            raise self_test_error("SELFTEST_AGENT_FORBIDDEN", "外部身份没有此任务权限", 403)
        binding = self.binding(project_id, binding_id)
        identity = binding.observer_id if capability == "verify" else binding.agent_id
        if principal.id != identity:
            raise self_test_error("SELFTEST_AGENT_BINDING_MISMATCH", "外部身份未分配给此绑定", 403)
        self.safe_binding(binding)
        return binding

    def frozen_binding(self, model: SelfTestBatch | SelfTestInstallation) -> SelfTestBinding:
        binding = self.binding(model.project_id, model.binding_id)
        self.safe_binding(binding)
        if (
            document_digest(binding) != model.binding_fingerprint
            or binding.environment_fingerprint != model.environment_fingerprint
        ):
            raise self_test_error(
                "SELFTEST_BINDING_CHANGED", "目标绑定或环境指纹已变化, 请重新预检"
            )
        return binding

    def lease(
        self,
        model: SelfTestBatch | SelfTestInstallation,
        principal: SelfTestPrincipal,
        payload: LeaseRequest,
        *,
        allow_sealed: bool = False,
    ) -> None:
        identity = (
            model.lease_owner == principal.id
            and hmac.compare_digest(model.lease_hash or "", token_digest(payload.lease_token))
            and hmac.compare_digest(model.nonce_hash or "", token_digest(payload.nonce))
        )
        if not identity:
            raise self_test_error("SELFTEST_LEASE_INVALID", "任务租约或批次 nonce 不匹配", 403)
        if not allow_sealed and (
            model.lease_expires_at is None or aware(model.lease_expires_at) <= datetime.now(UTC)
        ):
            raise self_test_error(
                "SELFTEST_LEASE_EXPIRED", "任务租约已过期, 未知执行结果须人工核对"
            )

    def active_batch(self, model: SelfTestBatch) -> None:
        if model.sealed_at is not None or model.phase in {"cancelled", "expired", "completed"}:
            raise self_test_error("SELFTEST_BATCH_FINISHED", "批次已结束, 不能恢复写入")
        if aware(model.deadline) <= datetime.now(UTC):
            raise self_test_error("SELFTEST_BATCH_EXPIRED", "批次已到截止时间, 保持未完成结果")
