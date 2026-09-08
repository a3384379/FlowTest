"""Controlled MCP adapter for draft-only FlowSpec proposals."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.context import get_tenant_context
from app.core.errors import AppError
from app.domain.flow_spec import FlowSpecIssue
from app.domain.flow_spec_security import contains_sensitive_flow_spec_value
from app.domain.flow_spec_security import (
    contains_unsafe_jmespath_literal as _shared_contains_unsafe_jmespath_literal,
)
from app.domain.test_contexts import first_sensitive_value
from app.models.access import User
from app.schemas.flow_spec import FlowSpecImportRequest
from app.schemas.test_contexts import (
    FlowSpecProposalInspectionResponse,
    FlowSpecProposalRequest,
    FlowSpecProposalResponse,
)
from app.services.flow_spec import FlowSpecImportProvenance, FlowSpecService
from app.services.idempotency import IdempotencyService, require_idempotency_key
from app.services.projects import ProjectService
from app.services.test_contexts import ProposableContext, TestContextService

MCP_FLOW_PROPOSE_SCOPE = "mcp:flow:propose"


def _contains_unsafe_jmespath_literal(expression: str) -> bool:
    """Compatibility wrapper for existing S51 security characterization tests."""

    return _shared_contains_unsafe_jmespath_literal(expression)


class MCPFlowProposalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._contexts = TestContextService(session)
        self._flow_specs = FlowSpecService(session)
        self._projects = ProjectService(session)

    async def propose(
        self,
        *,
        actor: User,
        payload: FlowSpecProposalRequest,
        idempotency_key: str | None,
    ) -> FlowSpecProposalResponse:
        service_account_id = self._require_scope()
        try:
            await self._projects.authorize(actor=actor, project_id=payload.project_id, editing=True)
        except AppError as error:
            # Keep the historical generic 404 for an unknown or inaccessible project.
            # Authorization still runs before the receipt lookup; this mapping only
            # preserves the non-disclosing error contract for callers.
            if error.code != "PROJECT_NOT_FOUND":
                raise
            raise AppError(
                code="TEST_CONTEXT_NOT_FOUND",
                message="Test Context 不存在",
                status_code=404,
            ) from error
        key = require_idempotency_key(idempotency_key)
        self._reject_sensitive(payload)
        request_payload = payload.model_dump(mode="json")
        actor_key = f"service-account:{service_account_id}"
        idempotency = IdempotencyService(self._session)
        cached = await idempotency.completed_response(
            key=key,
            project_id=payload.project_id,
            actor_key=actor_key,
            operation="propose_flow_draft",
            request_payload=request_payload,
        )
        if cached is not None:
            cached["idempotency_replayed"] = True
            return FlowSpecProposalResponse.model_validate(cached)
        if payload.dry_run:
            context = await self._context(actor=actor, payload=payload)
            return await self._preview(
                actor=actor,
                payload=payload,
                service_account_id=service_account_id,
                context=context,
            )
        response = await idempotency.run(
            key=key,
            project_id=payload.project_id,
            actor_key=actor_key,
            operation="propose_flow_draft",
            request_payload=request_payload,
            atomic_action=True,
            action=lambda: self._persist(
                actor=actor,
                payload=payload,
                service_account_id=service_account_id,
            ),
        )
        return FlowSpecProposalResponse.model_validate(response)

    async def inspect(
        self,
        *,
        actor: User,
        project_id: UUID,
        change_set_id: UUID,
    ) -> FlowSpecProposalInspectionResponse:
        self._require_scope()
        proposal = await self._flow_specs.get_visual_proposal(
            actor=actor,
            project_id=project_id,
            change_set_id=change_set_id,
        )
        snapshot = proposal.view.change_set.source_snapshot
        return FlowSpecProposalInspectionResponse(
            change_set_id=proposal.view.change_set.id,
            project_id=proposal.view.change_set.project_id,
            status=proposal.view.change_set.status,
            review_status=proposal.view.item.review_status,
            applied=proposal.view.change_set.applied_at is not None,
            target_workflow_id=proposal.view.item.target_resource_id,
            target_revision=_target_revision(snapshot),
            context_revision_id=_uuid(snapshot.get("context_revision_id")),
            context_fingerprint=_string(snapshot.get("context_fingerprint")),
            integration_plan=proposal.integration_plan,
            compilation=proposal.compilation,
            existing_definition=proposal.existing_definition,
            proposed_definition=proposal.proposed_definition,
            human_actions_required=_proposal_actions(
                review_status=proposal.view.item.review_status,
                applied=proposal.view.change_set.applied_at is not None,
            ),
            review_url=_ui_link(f"/projects/{project_id}/workflows?proposal={change_set_id}"),
            approval_url=(
                _ui_link(f"/projects/{project_id}/workflows?proposal={change_set_id}")
                if proposal.view.item.review_status == "accepted"
                and proposal.view.change_set.applied_at is None
                else None
            ),
            next_action=_proposal_next_action(
                review_status=proposal.view.item.review_status,
                applied=proposal.view.change_set.applied_at is not None,
            ),
        )

    async def _preview(
        self,
        *,
        actor: User,
        payload: FlowSpecProposalRequest,
        service_account_id: UUID,
        context: ProposableContext,
    ) -> FlowSpecProposalResponse:
        source_ref = _source_ref(payload)
        preview = await self._flow_specs.preview_import(
            actor=actor,
            project_id=payload.project_id,
            payload=_import_request(payload, source_ref),
            provenance=_provenance(
                payload=payload,
                context=context,
                source_ref=source_ref,
                service_account_id=service_account_id,
            ),
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
            provenance=_provenance(
                payload=payload,
                context=context,
                source_ref=source_ref,
                service_account_id=service_account_id,
            ),
            commit=False,
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
        return require_mcp_flow_propose_scope()

    def _reject_sensitive(self, payload: FlowSpecProposalRequest) -> None:
        if first_sensitive_value(
            payload.model_dump(mode="json")
        ) is not None or contains_sensitive_flow_spec_value(payload.spec):
            raise AppError(
                code="MCP_SENSITIVE_INPUT",
                message="FlowSpec 提案不能包含 Secret、凭据或 PII, 请使用 secret:// 引用",
                status_code=422,
            )


def require_mcp_flow_propose_scope() -> UUID:
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


def _ui_link(path: str) -> str:
    """Build a trusted UI hand-off link without carrying a token or user input."""

    origin = next((item.strip().rstrip("/") for item in settings.cors_origins if item.strip()), "")
    return f"{origin}{path}" if origin else path


def _proposal_actions(*, review_status: str, applied: bool) -> list[str]:
    if applied:
        return ["提案已经应用; 请读取执行或 Preview 证据"]
    if review_status == "pending":
        return ["请由人工检查并接受或拒绝该 Proposal"]
    if review_status == "accepted":
        return ["请创建一次性 Sandbox Preview Approval"]
    return ["提案已拒绝; 如需继续请生成新的修订"]


def _proposal_next_action(*, review_status: str, applied: bool) -> str:
    return _proposal_actions(review_status=review_status, applied=applied)[0]


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


def _provenance(
    *,
    payload: FlowSpecProposalRequest,
    context: ProposableContext,
    source_ref: str,
    service_account_id: UUID,
) -> FlowSpecImportProvenance:
    return FlowSpecImportProvenance(
        context_revision_id=context.revision.id,
        context_fingerprint=context.revision.fingerprint,
        source_ref=source_ref,
        service_account_id=service_account_id,
        expected_target_revision=payload.expected_revision,
        integration_plan=payload.integration_plan,
        compilation=payload.compilation,
    )


def _warnings(values: list[FlowSpecIssue]) -> list[str]:
    return sorted({value.code for value in values})


def _target_revision(snapshot: dict[str, object]) -> int | None:
    value = snapshot.get("target_revision")
    return value if isinstance(value, int) else None


def _uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None
