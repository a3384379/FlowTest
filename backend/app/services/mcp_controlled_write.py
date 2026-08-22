"""Application service for MCP-proposed, human-controlled S42 writes."""

# Chinese product copy intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_tenant_context, get_trace_id
from app.core.errors import AppError
from app.domain.mcp_read import MCPReadCall
from app.domain.test_design import (
    TestDesignDocument,
    evaluate_governance,
    fingerprint_design,
    normalized_design,
    sensitive_paths,
)
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.test_design import ChangeSetApproval, TestDesign
from app.repositories.ai_change_sets import AIChangeSetRepository
from app.schemas.test_assets import TestCaseDefinitionInput
from app.schemas.test_design import (
    MCPControlledWriteCreate,
    MCPControlledWriteEnvelope,
    MCPControlledWriteReview,
    MCPManualApprovalCreate,
    MCPTestCaseDraft,
)
from app.services.audit import AuditService
from app.services.projects import ProjectService
from app.services.test_assets import TestCaseService

MCP_WRITE_SCOPE = "mcp:write"
MCP_WRITE_SCHEMA_VERSION = "flowtest-mcp-controlled-write-schema-v1"
_SOURCE_REF = re.compile(r"^mcp://[A-Za-z0-9._/-]{1,480}$")


class MCPControlledWriteService:
    """Keep MCP, REST, and the human review path behind one application boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._change_sets = AIChangeSetRepository(session)
        self._audit = AuditService(session)

    async def propose(
        self,
        *,
        actor: User,
        payload: MCPControlledWriteCreate,
        call: MCPReadCall,
    ) -> MCPControlledWriteEnvelope:
        self._require_write_scope()
        await self._projects.authorize(actor=actor, project_id=payload.project_id, editing=True)
        self._reject_sensitive(payload.model_dump(mode="json"))
        source_ref = _source_ref(payload.source_ref)
        governance = evaluate_governance(
            confidence=payload.confidence,
            risk_level=payload.risk_level,
            design=payload.design,
        )
        source_snapshot = _source_snapshot(payload, governance, source_ref)
        source_fingerprint = _fingerprint(source_snapshot)
        change_set = AIChangeSet(
            project_id=payload.project_id,
            impact_run_id=None,
            release_risk_id=None,
            ai_job_id=None,
            title=payload.title.strip(),
            status="draft",
            source_snapshot=source_snapshot,
            source_fingerprint=source_fingerprint,
            source_type="mcp",
            source_ref=source_ref,
            actor_type="service_account",
            actor_id=actor.id,
            created_by_id=actor.id,
        )
        self._session.add(change_set)
        await self._session.flush()
        self._session.add(
            AIChangeItem(
                change_set_id=change_set.id,
                suggestion_id=None,
                position=0,
                item_type="test_design",
                action="create",
                title=payload.title.strip(),
                target_resource_id=None,
                target_snapshot_sha256=None,
                proposed_content=normalized_design(payload.design),
                review_status="pending",
            )
        )
        for position, test_case in enumerate(payload.test_cases, start=1):
            self._session.add(
                AIChangeItem(
                    change_set_id=change_set.id,
                    suggestion_id=None,
                    position=position,
                    item_type="test_case",
                    action="create",
                    title=test_case.name.strip(),
                    target_resource_id=None,
                    target_snapshot_sha256=None,
                    proposed_content=_json_object(test_case.model_dump(mode="json")),
                    review_status="pending",
                )
            )
        self._audit_call(
            actor=actor,
            project_id=payload.project_id,
            change_set_id=change_set.id,
            call=call,
            action="mcp.change_set_proposed",
            details={
                "source_fingerprint": source_fingerprint,
                "item_count": len(payload.test_cases) + 1,
                "confidence": payload.confidence,
                "risk_level": payload.risk_level,
                "reason_codes": list(governance.reason_codes),
            },
        )
        await self._session.commit()
        await self._session.refresh(change_set)
        items = await self._change_sets.list_items(change_set.id)
        return _envelope(
            change_set=change_set,
            items=items,
            approval=None,
            confidence=payload.confidence,
            warnings=_warnings(governance),
        )

    async def get_for_user(self, *, actor: User, change_set_id: UUID) -> MCPControlledWriteEnvelope:
        change_set = await self._get_change_set(change_set_id)
        await self._projects.authorize(actor=actor, project_id=change_set.project_id, editing=False)
        items = await self._change_sets.list_items(change_set.id)
        approval = await self._approval(change_set.id)
        governance = _governance(change_set)
        return _envelope(
            change_set=change_set,
            items=items,
            approval=approval,
            confidence=_governance_confidence(governance),
            warnings=_warnings_from_snapshot(change_set),
        )

    async def approve(
        self,
        *,
        actor: User,
        change_set_id: UUID,
        payload: MCPManualApprovalCreate,
    ) -> MCPControlledWriteEnvelope:
        change_set = await self._change_sets.get_change_set_for_update(change_set_id)
        if change_set is None or change_set.source_type != "mcp":
            raise _not_found()
        await self._projects.authorize(actor=actor, project_id=change_set.project_id, editing=True)
        governance = _governance(change_set)
        if not bool(governance["manual_approval_required"]):
            raise AppError(
                code="MCP_APPROVAL_NOT_REQUIRED",
                message="当前变更集不需要高风险人工批准",
                status_code=409,
            )
        approval = await self._approval(change_set.id)
        if approval is None:
            approval = ChangeSetApproval(
                change_set_id=change_set.id,
                decision="approved",
                note=payload.note.strip(),
                approved_by_id=actor.id,
                approved_at=datetime.now(UTC),
            )
            self._session.add(approval)
            await self._session.flush()
            self._audit.record(
                actor_user_id=actor.id,
                project_id=change_set.project_id,
                action="mcp.change_set_manually_approved",
                resource_type="change_set_approval",
                resource_id=approval.id,
                details={
                    "change_set_id": str(change_set.id),
                    "risk_level": governance["risk_level"],
                },
            )
            await self._session.commit()
            await self._session.refresh(change_set)
        elif approval.decision != "approved":
            raise AppError(
                code="MCP_CHANGE_SET_NOT_APPROVED",
                message="变更集人工审批未通过",
                status_code=409,
            )
        items = await self._change_sets.list_items(change_set.id)
        return _envelope(
            change_set=change_set,
            items=items,
            approval=approval,
            confidence=_governance_confidence(governance),
            warnings=_warnings_from_snapshot(change_set),
        )

    async def review_item(
        self,
        *,
        actor: User,
        change_set_id: UUID,
        item_id: UUID,
        decision: Literal["accept", "reject"],
        payload: MCPControlledWriteReview,
    ) -> MCPControlledWriteEnvelope:
        change_set = await self._change_sets.get_change_set_for_update(change_set_id)
        if change_set is None or change_set.source_type != "mcp":
            raise _not_found()
        await self._projects.authorize(actor=actor, project_id=change_set.project_id, editing=True)
        item = await self._change_sets.get_item_for_update(item_id)
        if item is None or item.change_set_id != change_set.id:
            raise AppError(
                code="MCP_CHANGE_ITEM_NOT_FOUND", message="受控变更项不存在", status_code=404
            )
        if item.review_status != "pending":
            raise AppError(
                code="MCP_CHANGE_ITEM_ALREADY_REVIEWED",
                message="受控变更项已经完成审核",
                status_code=409,
            )
        if decision == "reject" and payload.content is not None:
            raise AppError(
                code="MCP_REJECT_EDIT_FORBIDDEN",
                message="拒绝变更项时不能修改内容",
                status_code=422,
            )
        governance = _governance(change_set)
        approval = await self._approval(change_set.id)
        if (
            decision == "accept"
            and bool(governance["manual_approval_required"])
            and (
                approval is None
                or approval.decision != "approved"
                or payload.approval_id != approval.id
            )
        ):
            raise AppError(
                code="MCP_MANUAL_APPROVAL_REQUIRED",
                message="高风险受控写入必须先完成人工审批",
                status_code=409,
            )
        content = await self._validated_content(item, payload.content)
        materialized_type: str | None = None
        materialized_id: UUID | None = None
        if decision == "accept":
            materialized_type, materialized_id = await self._materialize(
                actor=actor,
                change_set=change_set,
                item=item,
                content=content,
            )
        item.proposed_content = content
        item.review_status = "accepted" if decision == "accept" else "rejected"
        item.review_note = payload.note.strip()
        item.reviewed_by_id = actor.id
        item.reviewed_at = datetime.now(UTC)
        item.materialized_resource_type = materialized_type
        item.materialized_resource_id = materialized_id
        items = await self._change_sets.list_items(change_set.id)
        change_set.status = _review_status(items)
        if change_set.status == "accepted":
            change_set.applied_at = datetime.now(UTC)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=change_set.project_id,
            action=f"mcp.change_item_{item.review_status}",
            resource_type="mcp_change_item",
            resource_id=item.id,
            details={
                "change_set_id": str(change_set.id),
                "item_type": item.item_type,
                "materialized_resource_type": materialized_type,
                "materialized_resource_id": str(materialized_id) if materialized_id else None,
                "risk_level": governance["risk_level"],
            },
        )
        await self._session.commit()
        await self._session.refresh(change_set)
        await self._session.refresh(item)
        approval = await self._approval(change_set.id)
        return _envelope(
            change_set=change_set,
            items=await self._change_sets.list_items(change_set.id),
            approval=approval,
            confidence=_governance_confidence(governance),
            warnings=_warnings_from_snapshot(change_set),
        )

    async def _validated_content(
        self, item: AIChangeItem, content: dict[str, JsonValue] | None
    ) -> dict[str, JsonValue]:
        candidate = (
            content if content is not None else cast(dict[str, JsonValue], item.proposed_content)
        )
        self._reject_sensitive(candidate)
        try:
            if item.item_type == "test_design":
                validated = TestDesignDocument.model_validate(candidate)
                return normalized_design(validated)
            if item.item_type == "test_case":
                from app.schemas.test_design import MCPTestCaseDraft

                return _json_object(
                    MCPTestCaseDraft.model_validate(candidate).model_dump(mode="json")
                )
        except (TypeError, ValueError) as error:
            raise AppError(
                code="MCP_CHANGE_CONTENT_INVALID",
                message="受控变更内容不符合 Test Design 或 Test Case 契约",
                status_code=422,
            ) from error
        raise AppError(
            code="MCP_CHANGE_ITEM_INVALID", message="MCP 不支持此变更项类型", status_code=422
        )

    async def _materialize(
        self,
        *,
        actor: User,
        change_set: AIChangeSet,
        item: AIChangeItem,
        content: dict[str, JsonValue],
    ) -> tuple[str, UUID]:
        if item.item_type == "test_design":
            design = TestDesignDocument.model_validate(content)
            duplicate = await self._session.scalar(
                select(TestDesign.id).where(
                    TestDesign.project_id == change_set.project_id,
                    TestDesign.name == change_set.title,
                )
            )
            if duplicate is not None:
                raise AppError(
                    code="TEST_DESIGN_NAME_EXISTS",
                    message="Test Design 名称已存在",
                    status_code=409,
                )
            design_model = TestDesign(
                project_id=change_set.project_id,
                name=change_set.title,
                status="approved",
                intent=_json_object(design.intent.model_dump(mode="json")),
                knowledge_graph=_json_object(design.knowledge_graph.model_dump(mode="json")),
                state_model=_json_object(design.state_model.model_dump(mode="json")),
                oracles=cast(list[dict[str, Any]], design.model_dump(mode="json")["oracles"]),
                coverage=_json_object(design.coverage.model_dump(mode="json")),
                test_case_refs=list(design.test_case_refs),
                fingerprint=fingerprint_design(design),
                source_change_set_id=change_set.id,
                created_by_id=actor.id,
                reviewed_by_id=actor.id,
                reviewed_at=datetime.now(UTC),
            )
            self._session.add(design_model)
            await self._session.flush()
            return "test_design", design_model.id
        if item.item_type == "test_case":
            draft = MCPTestCaseDraft.model_validate(content)
            created_case = await TestCaseService(self._session).create(
                actor=actor,
                project_id=change_set.project_id,
                name=draft.name,
                description=draft.description,
                folder_id=None,
                tags=list(draft.tags),
                is_template=False,
                definition=TestCaseDefinitionInput.model_validate(draft.definition),
                commit=False,
            )
            return "test_case", created_case.id
        raise AppError(
            code="MCP_CHANGE_ITEM_INVALID", message="MCP 不支持此变更项类型", status_code=422
        )

    async def _get_change_set(self, change_set_id: UUID) -> AIChangeSet:
        change_set = await self._change_sets.get_change_set(change_set_id)
        if change_set is None or change_set.source_type != "mcp":
            raise _not_found()
        return change_set

    async def _approval(self, change_set_id: UUID) -> ChangeSetApproval | None:
        return cast(
            ChangeSetApproval | None,
            await self._session.scalar(
                select(ChangeSetApproval).where(ChangeSetApproval.change_set_id == change_set_id)
            ),
        )

    def _require_write_scope(self) -> None:
        context = get_tenant_context()
        if context is None or MCP_WRITE_SCOPE not in context.scopes:
            raise AppError(
                code="MCP_SCOPE_REQUIRED", message="MCP 需要受控写入权限范围", status_code=403
            )

    def _reject_sensitive(self, value: object) -> None:
        paths = sensitive_paths(value)
        if paths:
            raise AppError(
                code="MCP_SENSITIVE_INPUT",
                message="受控写入不能包含 Secret、凭据或 PII；请使用 secret:// 引用",
                status_code=422,
                details={"paths": list(paths[:20])},
            )

    def _audit_call(
        self,
        *,
        actor: User,
        project_id: UUID,
        change_set_id: UUID,
        call: MCPReadCall,
        action: str,
        details: dict[str, JsonValue],
    ) -> None:
        context = get_tenant_context()
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=context.organization_id if context else None,
            project_id=project_id,
            action=action,
            resource_type="mcp_change_set",
            resource_id=change_set_id,
            details={
                "operation": call.operation,
                "input_schema_hash": call.input_schema_hash,
                "client_version": call.client_version,
                **details,
            },
        )


def _source_ref(value: str | None) -> str:
    candidate = value.strip() if value else "mcp://controlled-writes/pending"
    if _SOURCE_REF.fullmatch(candidate) is None:
        raise AppError(
            code="MCP_SOURCE_REF_INVALID",
            message="source_ref 必须是无查询参数的 mcp:// 标识",
            status_code=422,
        )
    return candidate


def _source_snapshot(
    payload: MCPControlledWriteCreate, governance: Any, source_ref: str
) -> dict[str, JsonValue]:
    test_cases = [_json_object(item.model_dump(mode="json")) for item in payload.test_cases]
    return {
        "schema_version": "s42-test-design-v1",
        "source_ref": source_ref,
        "design": normalized_design(payload.design),
        "test_cases": cast(list[JsonValue], test_cases),
        "governance": {
            "confidence": governance.confidence,
            "risk_level": governance.risk_level,
            "requires_review": governance.requires_review,
            "manual_approval_required": governance.manual_approval_required,
            "reason_codes": list(governance.reason_codes),
        },
    }


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_object(value: object) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], value)


def _governance(change_set: AIChangeSet) -> dict[str, JsonValue]:
    raw = change_set.source_snapshot.get("governance")
    if not isinstance(raw, dict):
        raise AppError(
            code="MCP_CHANGE_SET_INVALID", message="受控变更集治理元数据缺失", status_code=409
        )
    return cast(dict[str, JsonValue], raw)


def _governance_confidence(governance: dict[str, JsonValue]) -> float:
    value = governance.get("confidence")
    if not isinstance(value, (int, float)):
        raise AppError(
            code="MCP_CHANGE_SET_INVALID", message="受控变更集置信度元数据无效", status_code=409
        )
    return float(value)


def _review_status(items: list[AIChangeItem]) -> str:
    accepted = sum(item.review_status == "accepted" for item in items)
    rejected = sum(item.review_status == "rejected" for item in items)
    pending = len(items) - accepted - rejected
    if pending:
        return "partially_reviewed" if accepted or rejected else "draft"
    return "accepted" if accepted else "rejected"


def _envelope(
    *,
    change_set: AIChangeSet,
    items: list[AIChangeItem],
    approval: ChangeSetApproval | None,
    confidence: float,
    warnings: list[str],
) -> MCPControlledWriteEnvelope:
    return MCPControlledWriteEnvelope(
        data=_change_set_data(change_set, items, approval),
        evidence_refs=[
            {
                "uri": f"flowtest://change-sets/{change_set.id}",
                "kind": "controlled-change-set",
                "version": "s42",
            }
        ],
        confidence=confidence,
        redactions=["secret_values", "pii_values", "authorization_values"],
        trace_id=get_trace_id(),
        warnings=warnings,
    )


def _change_set_data(
    change_set: AIChangeSet,
    items: list[AIChangeItem],
    approval: ChangeSetApproval | None,
) -> dict[str, JsonValue]:
    governance = _governance(change_set)
    return {
        "id": str(change_set.id),
        "project_id": str(change_set.project_id),
        "title": change_set.title,
        "status": change_set.status,
        "source_type": change_set.source_type,
        "source_ref": change_set.source_ref,
        "actor_type": change_set.actor_type,
        "source_fingerprint": change_set.source_fingerprint,
        "created_by_id": str(change_set.created_by_id),
        "created_at": change_set.created_at.isoformat(),
        "updated_at": change_set.updated_at.isoformat(),
        "applied_at": change_set.applied_at.isoformat() if change_set.applied_at else None,
        "governance": governance,
        "approval": (
            {
                "id": str(approval.id),
                "decision": approval.decision,
                "approved_by_id": str(approval.approved_by_id),
                "approved_at": approval.approved_at.isoformat(),
            }
            if approval
            else None
        ),
        "items": [
            {
                "id": str(item.id),
                "position": item.position,
                "item_type": item.item_type,
                "action": item.action,
                "title": item.title,
                "proposed_content": cast(dict[str, JsonValue], item.proposed_content),
                "review_status": item.review_status,
                "review_note": item.review_note,
                "reviewed_by_id": str(item.reviewed_by_id) if item.reviewed_by_id else None,
                "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
                "materialized_resource_type": item.materialized_resource_type,
                "materialized_resource_id": (
                    str(item.materialized_resource_id) if item.materialized_resource_id else None
                ),
            }
            for item in items
        ],
    }


def _warnings(governance: Any) -> list[str]:
    warnings = ["MCP 只能创建待审核 ChangeSet；不会自动发布、执行或修改权限。"]
    if governance.manual_approval_required:
        warnings.append("高风险写入必须由人工批准后才能接受变更项。")
    if "low_confidence_assertion_review" in governance.reason_codes:
        warnings.append("低置信度 Oracle 必须经过人工 Review。")
    return warnings


def _warnings_from_snapshot(change_set: AIChangeSet) -> list[str]:
    governance = _governance(change_set)
    warnings = ["MCP 只能创建待审核 ChangeSet；不会自动发布、执行或修改权限。"]
    if governance.get("manual_approval_required") is True:
        warnings.append("高风险写入必须由人工批准后才能接受变更项。")
    reasons = governance.get("reason_codes")
    if isinstance(reasons, list) and "low_confidence_assertion_review" in reasons:
        warnings.append("低置信度 Oracle 必须经过人工 Review。")
    return warnings


def _not_found() -> AppError:
    return AppError(code="MCP_CHANGE_SET_NOT_FOUND", message="受控变更集不存在", status_code=404)
