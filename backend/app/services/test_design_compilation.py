"""Authorized, read-only resolution around the pure frozen Design compiler."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_tenant_context
from app.core.errors import AppError
from app.domain.mcp_read import MCP_READ_SCOPE
from app.domain.test_contexts import context_revision_fingerprint
from app.domain.test_design import fingerprint_design
from app.domain.test_design_compilation import (
    CompileTestDesignRequest,
    CompileTestDesignResponse,
    compile_frozen_design,
    value_fingerprint,
)
from app.domain.test_engineering import (
    OperationContract,
    TestEngineeringEngine,
    fingerprint_contract,
)
from app.models.access import User
from app.models.test_contexts import TestContext, TestContextRevision
from app.repositories.api_assets import APIAssetRepository
from app.repositories.service_targets import ServiceTargetRepository
from app.services.mcp_flow_proposals import require_mcp_flow_propose_scope
from app.services.projects import ProjectService
from app.services.test_contexts import _revision_snapshot
from app.services.test_engineering import TestEngineeringService, generator_build_identity


def require_design_compilation_scopes() -> None:
    require_mcp_flow_propose_scope()
    tenant = get_tenant_context()
    if tenant is None or MCP_READ_SCOPE not in tenant.scopes:
        raise AppError(
            code="MCP_SCOPE_REQUIRED",
            message="固定 Design 编译同时需要 MCP 只读与流程提案权限",
            status_code=403,
        )


class TestDesignCompilationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._assets = APIAssetRepository(session)
        self._targets = ServiceTargetRepository(session)
        self._engineering = TestEngineeringService(session)

    async def compile(
        self, *, actor: User, payload: CompileTestDesignRequest
    ) -> CompileTestDesignResponse:
        require_design_compilation_scopes()
        await ProjectService(self._session).authorize(
            actor=actor, project_id=payload.project_id, editing=False
        )
        definition = await self._assets.get_definition(payload.origin.api_definition_id)
        if definition is None or definition.project_id != payload.project_id:
            raise AppError(
                code="API_DEFINITION_NOT_FOUND", message="API 定义不存在", status_code=404
            )
        contract = await self._engineering.contract_for_api(
            project_id=payload.project_id,
            definition_id=definition.id,
            version_number=payload.origin.api_version,
        )
        if fingerprint_contract(contract) != payload.origin.contract_fingerprint:
            raise _source_mismatch("冻结 API 契约 Fingerprint 不匹配")
        version = await self._assets.get_version(
            definition_id=definition.id, version=payload.origin.api_version
        )
        if version is None:
            raise AppError(code="API_VERSION_NOT_FOUND", message="API 版本不存在", status_code=404)
        if (version.method, version.path) != (contract.method, contract.path):
            raise _source_mismatch("冻结契约 method/path 与实际 API 版本不一致")
        variant = await self._validate_environment(payload, version.service_id)
        payload = payload.model_copy(update={"endpoint_variant": variant})
        await self._validate_context(payload)
        _validate_frozen_generation(payload, contract)
        return compile_frozen_design(payload, contract, service_id=version.service_id)

    async def _validate_environment(
        self, payload: CompileTestDesignRequest, service_id: UUID | None
    ) -> str | None:
        environment = await self._assets.get_environment(payload.environment_id)
        if (
            environment is None
            or environment.project_id != payload.project_id
            or environment.archived_at is not None
        ):
            raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)
        if service_id is None:
            if payload.endpoint_variant is not None:
                raise AppError(
                    code="TEST_ENGINEERING_ENDPOINT_VARIANT_INVALID",
                    message="未绑定 Service 的 API 不能指定 Endpoint Variant",
                    status_code=422,
                )
            return None
        endpoints = await self._targets.list_endpoints(
            project_id=payload.project_id, environment_id=environment.id
        )
        variants = {
            endpoint.variant
            for endpoint in endpoints
            if endpoint.enabled and endpoint.service_id == service_id
        }
        if payload.endpoint_variant is not None and payload.endpoint_variant in variants:
            return payload.endpoint_variant
        if payload.endpoint_variant is None and "default" in variants:
            return "default"
        if payload.endpoint_variant is None and len(variants) == 1:
            return next(iter(variants))
        raise AppError(
            code="SERVICE_ENDPOINT_NOT_FOUND",
            message="请选择当前环境已配置的 Service Endpoint Variant",
            status_code=422,
        )

    async def _validate_context(self, payload: CompileTestDesignRequest) -> None:
        binding = payload.context_binding
        if binding is None:
            return
        context = await self._session.scalar(
            select(TestContext).where(
                TestContext.id == binding.context_id, TestContext.project_id == payload.project_id
            )
        )
        if context is None:
            raise AppError(
                code="TEST_CONTEXT_NOT_FOUND", message="测试上下文不存在", status_code=404
            )
        expires = (
            context.expires_at.replace(tzinfo=UTC)
            if context.expires_at.tzinfo is None
            else context.expires_at
        )
        if context.status != "ready" or expires <= datetime.now(UTC):
            raise AppError(
                code="TEST_CONTEXT_NOT_READY", message="测试上下文未就绪或已过期", status_code=409
            )
        revision = await self._session.scalar(
            select(TestContextRevision).where(
                TestContextRevision.context_id == context.id,
                TestContextRevision.id == binding.context_revision_id,
                TestContextRevision.revision == context.current_revision,
            )
        )
        if revision is None or revision.fingerprint != binding.context_fingerprint:
            raise AppError(
                code="TEST_CONTEXT_REVISION_STALE",
                message="测试上下文 Revision 或 Fingerprint 已变化",
                status_code=409,
            )
        _validate_context_snapshot(revision)
        if (
            context.target_environment_id is not None
            and context.target_environment_id != payload.environment_id
        ):
            raise AppError(
                code="INTEGRATION_PLAN_ENVIRONMENT_MISMATCH",
                message="目标环境与 Context 不一致",
                status_code=409,
            )


def _validate_context_snapshot(revision: TestContextRevision) -> None:
    try:
        snapshot = _revision_snapshot(revision)
    except ValueError as error:
        raise AppError(
            code="TEST_CONTEXT_REVISION_INVALID",
            message="测试上下文 Revision 内容无效",
            status_code=409,
        ) from error
    if (
        not snapshot.completeness.complete
        or context_revision_fingerprint(snapshot) != revision.fingerprint
    ):
        raise AppError(
            code="TEST_CONTEXT_REVISION_INVALID",
            message="测试上下文 Revision 内容或摘要不一致",
            status_code=409,
        )


def _validate_frozen_generation(
    payload: CompileTestDesignRequest, contract: OperationContract
) -> None:
    if payload.origin.generator_build != generator_build_identity():
        raise _source_mismatch("生成器实现已变化,请重新生成 Design")
    if (
        sorted(value_fingerprint(bundle) for bundle in payload.origin.evidence)
        != payload.origin.evidence_fingerprints
    ):
        raise _source_mismatch("冻结 Evidence Fingerprint 不匹配")
    regenerated = TestEngineeringEngine().generate(
        contract=contract,
        policy=payload.origin.generation_policy,
        additional_evidence=payload.origin.evidence,
    )
    if (
        fingerprint_design(payload.design) != payload.design_fingerprint
        or fingerprint_design(regenerated) != payload.design_fingerprint
    ):
        raise _source_mismatch("冻结输入无法重现 Design,请对修订内容重新审核")


def _source_mismatch(message: str) -> AppError:
    return AppError(code="DESIGN_COMPILATION_SOURCE_MISMATCH", message=message, status_code=409)
