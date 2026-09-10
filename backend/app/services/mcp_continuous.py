"""MCP adaptation of the existing diagnosis, maintenance and regression services."""

from typing import cast
from uuid import UUID

from pydantic import BaseModel, JsonValue

from app.core.context import get_trace_id
from app.core.errors import AppError
from app.core.redaction import redaction_enabled
from app.domain.mcp_read import EvidenceRef, MCPReadCall, MCPReadEnvelope
from app.domain.test_contexts import first_sensitive_value
from app.models.access import User
from app.schemas.failure_repair import FailureDiagnosisResponse
from app.schemas.mcp_continuous import (
    MCPAffectedFlowsRequest,
    MCPContextComparisonRequest,
    MCPContinuousProposalResponse,
    MCPFailureRequest,
    MCPMaintenanceRequest,
    MCPRegressionRequest,
    MCPRegressionSummary,
    MCPRepairRequest,
)
from app.schemas.regression_maintenance import maintenance_snapshot
from app.services.affected_flows import AffectedFlowService
from app.services.change_regression import ChangeRegressionService
from app.services.context_inspector import ContextInspectorService
from app.services.failure_repair import FailureRepairService
from app.services.idempotency import IdempotencyService, require_idempotency_key
from app.services.mcp_flow_proposals import require_mcp_flow_propose_scope
from app.services.mcp_read import MCPReadService
from app.services.regression_maintenance import RegressionMaintenanceService


class MCPContinuousService(MCPReadService):
    async def context_diff(
        self, *, actor: User, payload: MCPContextComparisonRequest, call: MCPReadCall
    ) -> MCPReadEnvelope:
        self._require_scope()
        result = await ContextInspectorService(self._session).compare_revisions(
            actor=actor, **payload.model_dump()
        )
        return await self._read_result(actor, payload.project_id, call, result)

    async def affected_flows(
        self, *, actor: User, payload: MCPAffectedFlowsRequest, call: MCPReadCall
    ) -> MCPReadEnvelope:
        self._require_scope()
        result = await AffectedFlowService(self._session).analyze(
            actor=actor, **payload.model_dump()
        )
        return await self._read_result(actor, payload.project_id, call, result)

    async def failure_diagnosis(
        self, *, actor: User, payload: MCPFailureRequest, call: MCPReadCall
    ) -> MCPReadEnvelope:
        self._require_scope()
        view = await FailureRepairService(self._session).diagnose(
            actor=actor, **payload.model_dump()
        )
        # Operation paths and display names can originate in failed, untrusted executions.
        triage = view.diagnosis.triage.model_copy(
            update={"affected_service": None, "endpoint_variant": None, "affected_operation": None}
        )
        result = FailureDiagnosisResponse(
            execution_id=view.execution.id,
            workflow_id=view.workflow_id,
            diagnosis=view.diagnosis.model_copy(update={"triage": triage}),
        )
        return await self._read_result(actor, payload.project_id, call, result)

    async def regression(
        self, *, actor: User, payload: MCPRegressionRequest, call: MCPReadCall
    ) -> MCPReadEnvelope:
        self._require_scope()
        bundle = await ChangeRegressionService(self._session).inspect(
            actor=actor, **payload.model_dump()
        )
        run = bundle.run
        snapshot = maintenance_snapshot(run.selection_summary)
        result = MCPRegressionSummary(
            project_id=run.project_id,
            run_id=run.id,
            status=run.status,
            impact_run_id=run.impact_run_id,
            test_plan_id=run.test_plan_id,
            test_plan_run_id=run.test_plan_run_id,
            release_decision_id=run.release_decision_id,
            context_diff_ref=snapshot.context_diff_ref if snapshot else None,
            knowledge_diff_ref=snapshot.knowledge_diff_ref if snapshot else None,
            analysis_complete=snapshot.affected.analysis_complete if snapshot else None,
            proposals=snapshot.proposals if snapshot else [],
            required_workflows=snapshot.required_workflows if snapshot else [],
        )
        return await self._read_result(actor, payload.project_id, call, result)

    async def propose_repair(
        self, *, actor: User, payload: MCPRepairRequest, idempotency_key: str | None
    ) -> MCPContinuousProposalResponse:
        account_id = require_mcp_flow_propose_scope()
        await self._projects.authorize(actor=actor, project_id=payload.project_id, editing=True)
        if not payload.dry_run:
            cached = await IdempotencyService(self._session).completed_response(
                key=require_idempotency_key(idempotency_key),
                project_id=payload.project_id,
                actor_key=f"service-account:{account_id}",
                operation=f"mcp.repair:{payload.execution_id}",
                request_payload=payload.model_dump(mode="json"),
            )
            if cached is not None:
                return MCPContinuousProposalResponse.model_validate(cached)
        service = FailureRepairService(self._session)
        prepared = await service.prepare_repair_proposal(
            actor=actor,
            project_id=payload.project_id,
            execution_id=payload.execution_id,
            payload=payload.repair,
        )
        workflow_id = prepared.import_request.workflow_id
        if workflow_id is None:
            raise RuntimeError("repair preflight did not resolve its target")
        response = MCPContinuousProposalResponse(
            project_id=payload.project_id,
            proposal_origin="repair",
            dry_run=True,
            change_set_id=None,
            target_workflow_id=workflow_id,
            target_revision=payload.repair.expected_target_revision,
            context_revision_id=prepared.provenance.context_revision_id,
            trace_id=get_trace_id(),
        )
        if payload.dry_run:
            return response

        async def persist() -> MCPContinuousProposalResponse:
            # Revalidate after claim commits; no user-controlled provenance is reused.
            refreshed = await service.prepare_repair_proposal(
                actor=actor,
                project_id=payload.project_id,
                execution_id=payload.execution_id,
                payload=payload.repair,
            )
            view = await service.persist_repair_proposal(refreshed)
            return self._persisted(response, view.change_set.id, actor, account_id)

        result = await IdempotencyService(self._session).run(
            key=require_idempotency_key(idempotency_key),
            project_id=payload.project_id,
            actor_key=f"service-account:{account_id}",
            operation=f"mcp.repair:{payload.execution_id}",
            request_payload=payload.model_dump(mode="json"),
            action=persist,
            atomic_action=True,
        )
        return MCPContinuousProposalResponse.model_validate(result)

    async def propose_maintenance(
        self, *, actor: User, payload: MCPMaintenanceRequest, idempotency_key: str | None
    ) -> MCPContinuousProposalResponse:
        account_id = require_mcp_flow_propose_scope()
        await self._projects.authorize(actor=actor, project_id=payload.project_id, editing=True)
        if not payload.dry_run:
            cached = await IdempotencyService(self._session).completed_response(
                key=require_idempotency_key(idempotency_key),
                project_id=payload.project_id,
                actor_key=f"service-account:{account_id}",
                operation=f"mcp.maintenance:{payload.run_id}:{payload.workflow_id}",
                request_payload=payload.model_dump(mode="json"),
            )
            if cached is not None:
                return MCPContinuousProposalResponse.model_validate(cached)
        service = RegressionMaintenanceService(self._session)
        prepared = await service.prepare_proposal(
            actor=actor,
            project_id=payload.project_id,
            run_id=payload.run_id,
            workflow_id=payload.workflow_id,
            payload=payload.maintenance,
        )
        response = MCPContinuousProposalResponse(
            project_id=payload.project_id,
            proposal_origin="maintenance",
            dry_run=True,
            change_set_id=None,
            target_workflow_id=payload.workflow_id,
            target_revision=payload.maintenance.expected_target_revision,
            context_revision_id=prepared.provenance.context_revision_id,
            regression_run_id=payload.run_id,
            trace_id=get_trace_id(),
        )
        if payload.dry_run:
            return response

        async def persist() -> MCPContinuousProposalResponse:
            bundle = await service.persist_proposal(payload.run_id, prepared)
            snapshot = maintenance_snapshot(bundle.run.selection_summary)
            if snapshot is None or not snapshot.proposals:
                raise RuntimeError("maintenance action did not link its proposal")
            return self._persisted(
                response, snapshot.proposals[-1].change_set_id, actor, account_id
            )

        result = await IdempotencyService(self._session).run(
            key=require_idempotency_key(idempotency_key),
            project_id=payload.project_id,
            actor_key=f"service-account:{account_id}",
            operation=f"mcp.maintenance:{payload.run_id}:{payload.workflow_id}",
            request_payload=payload.model_dump(mode="json"),
            action=persist,
            atomic_action=True,
        )
        return MCPContinuousProposalResponse.model_validate(result)

    def _persisted(
        self,
        response: MCPContinuousProposalResponse,
        proposal_id: UUID,
        actor: User,
        account_id: UUID,
    ) -> MCPContinuousProposalResponse:
        self._audit.record(
            actor_user_id=actor.id,
            project_id=response.project_id,
            action=f"mcp.{response.proposal_origin}.proposed",
            resource_type="ai_change_set",
            resource_id=proposal_id,
            details={"service_account_id": str(account_id), "requires_human_review": True},
        )
        return response.model_copy(update={"change_set_id": proposal_id, "dry_run": False})

    async def _read_result(
        self, actor: User, project_id: UUID, call: MCPReadCall, result: BaseModel
    ) -> MCPReadEnvelope:
        data = cast(JsonValue, result.model_dump(mode="json"))
        if len(result.model_dump_json()) > 2_000_000 or (
            redaction_enabled() and first_sensitive_value(data) is not None
        ):
            raise AppError(
                code="MCP_CONTINUOUS_OUTPUT_UNAVAILABLE",
                message="当前结果超出安全输出边界, 请在授权的产品界面检查",
                status_code=422,
            )
        return await self._envelope(
            actor=actor,
            project_id=project_id,
            call=call,
            data=data,
            evidence_refs=[
                EvidenceRef(
                    uri=f"flowtest://projects/{project_id}/continuous",
                    kind="continuous-qa",
                    version="s60-continuous-qa-v1",
                )
            ],
            redactions=["source_content", "raw_bodies", "display_names", "review_notes"],
        )
