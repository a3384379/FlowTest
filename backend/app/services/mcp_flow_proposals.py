"""Controlled MCP adapter for draft-only FlowSpec proposals."""

import re
from uuid import UUID

import jmespath
from jmespath.exceptions import JMESPathError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_tenant_context
from app.core.errors import AppError
from app.domain.flow_spec import FlowSpecIssue
from app.domain.test_contexts import first_sensitive_value, is_sensitive_identifier
from app.models.access import User
from app.schemas.flow_spec import FlowSpecImportRequest
from app.schemas.test_contexts import (
    FlowSpecProposalInspectionResponse,
    FlowSpecProposalRequest,
    FlowSpecProposalResponse,
)
from app.services.flow_spec import FlowSpecImportProvenance, FlowSpecService
from app.services.idempotency import IdempotencyService, require_idempotency_key
from app.services.test_contexts import ProposableContext, TestContextService

MCP_FLOW_PROPOSE_SCOPE = "mcp:flow:propose"
_SECRET_TEMPLATE = re.compile(r"(?:\{\{[^{}]+\}\}|\$\{[^{}]+\})")
_SECRET_REFERENCE = re.compile(r"secret://[A-Za-z0-9._:/-]+")


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
        self._reject_sensitive(payload)
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
        )

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
        ) is not None or _has_sensitive_parameter_literal(payload):
            raise AppError(
                code="MCP_SENSITIVE_INPUT",
                message="FlowSpec 提案不能包含 Secret、凭据或 PII, 请使用 secret:// 引用",
                status_code=422,
            )


def _has_sensitive_parameter_literal(payload: FlowSpecProposalRequest) -> bool:
    if any(is_sensitive_identifier(name) for name in payload.spec.variables):
        return True
    for parameter in payload.spec.parameters:
        if parameter.value is None:
            continue
        if is_sensitive_identifier(parameter.name):
            return True
    for node in payload.spec.nodes:
        if _has_sensitive_mapping_literal(node.model_dump(mode="json")):
            return True
    for edge in payload.spec.edges:
        for mapping in edge.mappings:
            if is_sensitive_identifier(mapping.target.key) and (
                (
                    mapping.transform.kind.value == "template"
                    and _contains_unsafe_literal(mapping.transform.template)
                )
                or (
                    mapping.transform.kind.value == "identity"
                    and _contains_unsafe_jmespath_literal(mapping.source.path)
                )
            ):
                return True
    return False


def _has_sensitive_mapping_literal(value: object) -> bool:
    if isinstance(value, list):
        return any(_has_sensitive_mapping_literal(item) for item in value)
    if not isinstance(value, dict):
        return False
    for identifier_field, literal_field in (
        ("name", "value"),
        ("key", "value"),
        ("input", "expression"),
        ("expression", "expected"),
    ):
        named_value = value.get(identifier_field)
        if (
            isinstance(named_value, str)
            and is_sensitive_identifier(named_value)
            and _contains_unsafe_literal(value.get(literal_field))
        ):
            return True
    variable = value.get("variable")
    expression = value.get("expression")
    if (
        isinstance(variable, str)
        and is_sensitive_identifier(variable)
        and isinstance(expression, str)
        and _contains_unsafe_jmespath_literal(expression)
    ):
        return True
    for name, child in value.items():
        if is_sensitive_identifier(str(name)) and _contains_unsafe_literal(child):
            return True
        if _has_sensitive_mapping_literal(child):
            return True
    return False


def _contains_unsafe_literal(value: object) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, str):
        return (
            _SECRET_REFERENCE.fullmatch(value) is None and _SECRET_TEMPLATE.fullmatch(value) is None
        )
    if isinstance(value, dict):
        return any(_contains_unsafe_literal(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_unsafe_literal(child) for child in value)
    return True


def _contains_unsafe_jmespath_literal(expression: str) -> bool:
    try:
        parsed = jmespath.compile(expression).parsed
    except JMESPathError:
        return True
    return _contains_unsafe_jmespath_ast(parsed)


def _contains_unsafe_jmespath_ast(value: object) -> bool:
    if isinstance(value, list):
        return any(_contains_unsafe_jmespath_ast(child) for child in value)
    if not isinstance(value, dict):
        return False
    if value.get("type") == "literal" and _contains_unsafe_literal(value.get("value")):
        return True
    return _contains_unsafe_jmespath_ast(value.get("children"))


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
