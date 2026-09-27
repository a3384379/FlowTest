"""Draft-only MCP proposals for a new native control-flow workflow."""

# Chinese product copy intentionally uses full-width punctuation.
# ruff: noqa: RUF001

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.redaction import redaction_enabled
from app.domain.test_design import sensitive_paths
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet
from app.schemas.mcp_control_blocks import (
    CONTROL_WORKFLOW_PROPOSAL_SCHEMA,
    MCPControlWorkflowDraft,
    MCPControlWorkflowProposalRequest,
    MCPControlWorkflowProposalResponse,
)
from app.services.audit import AuditService
from app.services.idempotency import IdempotencyService, require_idempotency_key
from app.services.mcp_flow_proposals import require_mcp_flow_propose_scope
from app.services.projects import ProjectService
from app.services.workflows import WorkflowService


class MCPControlWorkflowProposalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._workflows = WorkflowService(session)
        self._audit = AuditService(session)

    async def propose(
        self,
        *,
        actor: User,
        payload: MCPControlWorkflowProposalRequest,
        idempotency_key: str | None,
    ) -> MCPControlWorkflowProposalResponse:
        service_account_id = require_mcp_flow_propose_scope()
        await self._projects.authorize(actor=actor, project_id=payload.project_id, editing=True)
        key = require_idempotency_key(idempotency_key)
        request_payload = payload.model_dump(mode="json")
        if redaction_enabled() and sensitive_paths(request_payload):
            raise AppError(
                code="MCP_SENSITIVE_INPUT",
                message="工作流提案不能包含明文 Secret、凭据或 PII，请使用引用",
                status_code=422,
            )
        receipts = IdempotencyService(self._session)
        actor_key = f"service-account:{service_account_id}"
        cached = await receipts.completed_response(
            key=key,
            project_id=payload.project_id,
            actor_key=actor_key,
            operation="propose_control_workflow",
            request_payload=request_payload,
        )
        if cached is not None:
            cached["idempotency_replayed"] = True
            return MCPControlWorkflowProposalResponse.model_validate(cached)
        response = await receipts.run(
            key=key,
            project_id=payload.project_id,
            actor_key=actor_key,
            operation="propose_control_workflow",
            request_payload=request_payload,
            atomic_action=True,
            action=lambda: self._persist(
                actor=actor,
                payload=payload,
                service_account_id=service_account_id,
            ),
        )
        return MCPControlWorkflowProposalResponse.model_validate(response)

    async def _persist(
        self,
        *,
        actor: User,
        payload: MCPControlWorkflowProposalRequest,
        service_account_id: UUID,
    ) -> MCPControlWorkflowProposalResponse:
        await self._workflows.validate_proposed_definition(
            actor=actor,
            project_id=payload.project_id,
            definition=payload.definition,
        )
        draft = MCPControlWorkflowDraft.model_validate(
            payload.model_dump(mode="json", exclude={"project_id"})
        )
        content = draft.model_dump(mode="json", exclude_none=True)
        fingerprint = _fingerprint(content)
        change_set = AIChangeSet(
            project_id=payload.project_id,
            impact_run_id=None,
            release_risk_id=None,
            ai_job_id=None,
            title=draft.name.strip(),
            status="draft",
            source_snapshot={
                "schema_version": CONTROL_WORKFLOW_PROPOSAL_SCHEMA,
                "proposed_fingerprint": fingerprint,
                "governance": {
                    "confidence": 1.0,
                    "risk_level": "medium",
                    "requires_review": True,
                    "manual_approval_required": False,
                    "reason_codes": [],
                },
            },
            source_fingerprint=fingerprint,
            source_type="mcp",
            source_ref=f"mcp://projects/{payload.project_id}/control-workflows",
            actor_type="service_account",
            actor_id=actor.id,
            created_by_id=actor.id,
        )
        self._session.add(change_set)
        await self._session.flush()
        item = AIChangeItem(
            change_set_id=change_set.id,
            suggestion_id=None,
            position=0,
            item_type="workflow",
            action="create",
            title=draft.name.strip(),
            target_resource_id=None,
            target_snapshot_sha256=None,
            proposed_content=content,
            review_status="pending",
        )
        self._session.add(item)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=payload.project_id,
            action="mcp.control_workflow_proposed",
            resource_type="ai_change_set",
            resource_id=change_set.id,
            details={
                "schema_version": CONTROL_WORKFLOW_PROPOSAL_SCHEMA,
                "service_account_id": str(service_account_id),
                "node_count": len(draft.definition.nodes),
                "region_count": len(draft.definition.regions),
            },
        )
        return MCPControlWorkflowProposalResponse(
            project_id=payload.project_id,
            proposal_id=change_set.id,
            item_id=item.id,
            proposed_fingerprint=fingerprint,
            review_url=f"/projects/{payload.project_id}/mcp-changes?focus={change_set.id}",
        )


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
