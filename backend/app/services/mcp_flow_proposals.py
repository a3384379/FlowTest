"""Controlled MCP adapter for draft-only FlowSpec proposals."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_tenant_context
from app.core.errors import AppError
from app.domain.flow_spec import FlowSpecIssue
from app.models.access import User
from app.schemas.flow_spec import FlowSpecImportRequest
from app.schemas.test_contexts import FlowSpecProposalRequest, FlowSpecProposalResponse
from app.services.flow_spec import FlowSpecImportProvenance, FlowSpecService
from app.services.idempotency import IdempotencyService, require_idempotency_key
from app.services.test_contexts import ProposableContext, TestContextService

MCP_FLOW_PROPOSE_SCOPE = "mcp:flow:propose"


class MCPFlowProposalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._contexts = TestContextService(session)
        self._flow_specs = FlowSpecService(session)

    async def propose(
        self,
        *,
        actor: User,
        payload: FlowSpecProposalRequest,
        idempotency_key: str | None,
    ) -> FlowSpecProposalResponse:
        service_account_id = self._require_scope()
        key = require_idempotency_key(idempotency_key)
        if payload.dry_run:
            return await self._preview(
                actor=actor,
                payload=payload,
                service_account_id=service_account_id,
            )
        response = await IdempotencyService(self._session).run(
            key=key,
            project_id=payload.project_id,
            actor_key=f"service-account:{service_account_id}",
            operation="propose_flow_draft",
            request_payload=payload.model_dump(mode="json"),
            action=lambda: self._persist(
                actor=actor,
                payload=payload,
                service_account_id=service_account_id,
            ),
        )
        return FlowSpecProposalResponse.model_validate(response)

    async def _preview(
        self,
        *,
        actor: User,
        payload: FlowSpecProposalRequest,
        service_account_id: UUID,
    ) -> FlowSpecProposalResponse:
        context = await self._context(actor=actor, payload=payload)
        source_ref = _source_ref(payload)
        preview = await self._flow_specs.preview_import(
            actor=actor,
            project_id=payload.project_id,
            payload=_import_request(payload, source_ref),
        )
        return FlowSpecProposalResponse(
            dry_run=True,
            status="preview",
            context_id=context.context.id,
            context_revision_id=context.revision.id,
            context_fingerprint=context.revision.fingerprint,
            flow_spec_fingerprint=preview.pipeline.fingerprint,
            source_ref=source_ref,
            change_set_id=None,
            target_workflow_id=preview.target_workflow_id,
            target_revision=preview.target_revision,
            warnings=_warnings(preview.pipeline.compatibility.warnings),
        )

    async def _persist(
        self,
        *,
        actor: User,
        payload: FlowSpecProposalRequest,
        service_account_id: UUID,
    ) -> FlowSpecProposalResponse:
        context = await self._context(actor=actor, payload=payload)
        source_ref = _source_ref(payload)
        view = await self._flow_specs.create_import(
            actor=actor,
            project_id=payload.project_id,
            payload=_import_request(payload, source_ref),
            provenance=FlowSpecImportProvenance(
                context_revision_id=context.revision.id,
                context_fingerprint=context.revision.fingerprint,
                source_ref=source_ref,
                service_account_id=service_account_id,
            ),
        )
        if view.change_set.status != "draft" or view.item.review_status != "pending":
            raise RuntimeError("FlowSpec proposal adapter created a non-draft change set")
        return FlowSpecProposalResponse(
            dry_run=False,
            status="draft",
            context_id=context.context.id,
            context_revision_id=context.revision.id,
            context_fingerprint=context.revision.fingerprint,
            flow_spec_fingerprint=view.pipeline.fingerprint,
            source_ref=source_ref,
            change_set_id=view.change_set.id,
            target_workflow_id=view.item.target_resource_id,
            target_revision=_target_revision(view.change_set.source_snapshot),
            warnings=_warnings(view.pipeline.compatibility.warnings),
        )

    async def _context(self, *, actor: User, payload: FlowSpecProposalRequest) -> ProposableContext:
        return await self._contexts.require_proposable(
            actor=actor,
            project_id=payload.project_id,
            context_id=payload.context_id,
            revision_id=payload.context_revision_id,
        )

    def _require_scope(self) -> UUID:
        tenant = get_tenant_context()
        if (
            tenant is None
            or tenant.service_account_id is None
            or MCP_FLOW_PROPOSE_SCOPE not in tenant.scopes
        ):
            raise AppError(
                code="MCP_SCOPE_REQUIRED",
                message="MCP 需要 FlowSpec 提案权限范围",
                status_code=403,
            )
        return tenant.service_account_id


def _source_ref(payload: FlowSpecProposalRequest) -> str:
    return payload.source_ref or (
        f"mcp://contexts/{payload.context_id}/revisions/{payload.context_revision_id}/flow-drafts"
    )


def _import_request(payload: FlowSpecProposalRequest, source_ref: str) -> FlowSpecImportRequest:
    return FlowSpecImportRequest(
        spec=payload.spec,
        workflow_id=payload.workflow_id,
        source_ref=source_ref,
        service_mappings=payload.service_mappings,
        operation_mappings=payload.operation_mappings,
        operation_version_mappings=payload.operation_version_mappings,
    )


def _warnings(values: list[FlowSpecIssue]) -> list[str]:
    return sorted({value.code for value in values})


def _target_revision(snapshot: dict[str, object]) -> int | None:
    value = snapshot.get("target_revision")
    return value if isinstance(value, int) else None
