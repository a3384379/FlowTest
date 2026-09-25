"""Draft-only MCP proposals for one native workflow control block."""

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
    CONTROL_PROPOSAL_SCHEMA,
    MCPControlBlockProposalRequest,
    MCPControlBlockProposalResponse,
)
from app.services.audit import AuditService
from app.services.idempotency import IdempotencyService, require_idempotency_key
from app.services.mcp_flow_proposals import require_mcp_flow_propose_scope
from app.services.projects import ProjectService
from app.services.workflows import WorkflowService


class MCPControlBlockProposalService:
    """Validate and stage a native control edit without changing its workflow."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._workflows = WorkflowService(session)
        self._audit = AuditService(session)

    async def propose(
        self,
        *,
        actor: User,
        payload: MCPControlBlockProposalRequest,
        idempotency_key: str | None,
    ) -> MCPControlBlockProposalResponse:
        service_account_id = require_mcp_flow_propose_scope()
        await self._projects.authorize(actor=actor, project_id=payload.project_id, editing=True)
        key = require_idempotency_key(idempotency_key)
        request_payload = payload.model_dump(mode="json")
        if redaction_enabled() and sensitive_paths(request_payload):
            raise AppError(
                code="MCP_SENSITIVE_INPUT",
                message="控制块提案不能包含明文 Secret、凭据或 PII，请使用引用",
                status_code=422,
            )
        receipts = IdempotencyService(self._session)
        actor_key = f"service-account:{service_account_id}"
        cached = await receipts.completed_response(
            key=key,
            project_id=payload.project_id,
            actor_key=actor_key,
            operation="propose_control_block",
            request_payload=request_payload,
        )
        if cached is not None:
            cached["idempotency_replayed"] = True
            return MCPControlBlockProposalResponse.model_validate(cached)
        response = await receipts.run(
            key=key,
            project_id=payload.project_id,
            actor_key=actor_key,
            operation="propose_control_block",
            request_payload=request_payload,
            atomic_action=True,
            action=lambda: self._persist(
                actor=actor,
                payload=payload,
                service_account_id=service_account_id,
            ),
        )
        return MCPControlBlockProposalResponse.model_validate(response)

    async def _persist(
        self,
        *,
        actor: User,
        payload: MCPControlBlockProposalRequest,
        service_account_id: UUID,
    ) -> MCPControlBlockProposalResponse:
        edit = payload.edit
        workflow = await self._workflows.get(
            actor=actor,
            project_id=payload.project_id,
            workflow_id=payload.workflow_id,
        )
        proposed = await self._workflows.preview_control_block_insert(
            actor=actor,
            project_id=payload.project_id,
            workflow_id=payload.workflow_id,
            expected_revision=edit.expected_revision,
            edge_id=edit.edge_id,
            node=edit.node,
            regions=edit.regions,
            request_budget=edit.request_budget,
            cleanup_request_budget=edit.cleanup_request_budget,
        )
        content = edit.model_dump(mode="json", exclude_none=True)
        source_snapshot = {
            "schema_version": CONTROL_PROPOSAL_SCHEMA,
            "workflow_id": str(payload.workflow_id),
            "base_revision": edit.expected_revision,
            "governance": {
                "confidence": 1.0,
                "risk_level": "medium",
                "requires_review": True,
                "manual_approval_required": False,
                "reason_codes": [],
            },
        }
        change_set = AIChangeSet(
            project_id=payload.project_id,
            impact_run_id=None,
            release_risk_id=None,
            ai_job_id=None,
            title=f"控制块提案：{edit.node.name}",
            status="draft",
            source_snapshot=source_snapshot,
            source_fingerprint=_fingerprint(content),
            source_type="mcp",
            source_ref=f"mcp://workflows/{payload.workflow_id}/control-blocks",
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
            action="update",
            title=change_set.title,
            target_resource_id=workflow.id,
            target_snapshot_sha256=_fingerprint(workflow.draft_definition),
            proposed_content=content,
            review_status="pending",
        )
        self._session.add(item)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=payload.project_id,
            action="mcp.control_block_proposed",
            resource_type="ai_change_set",
            resource_id=change_set.id,
            details={
                "workflow_id": str(workflow.id),
                "base_revision": edit.expected_revision,
                "capability_id": edit.node.capability_id,
                "service_account_id": str(service_account_id),
            },
        )
        return MCPControlBlockProposalResponse(
            project_id=payload.project_id,
            workflow_id=workflow.id,
            base_revision=edit.expected_revision,
            proposal_id=change_set.id,
            item_id=item.id,
            proposed_fingerprint=_fingerprint(proposed.model_dump(mode="json", exclude_none=True)),
            review_url=f"/projects/{payload.project_id}/mcp-changes?focus={change_set.id}",
        )


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
