"""Application services for the read-only FlowTest MCP surface.

The delivery adapters call this service through the regular application boundary.  The
service deliberately projects database entities into small allow-listed payloads; it
never returns request headers, variables, bodies, snapshots, or secret values.
"""

# Chinese product copy intentionally uses full-width punctuation.
# ruff: noqa: RUF001

import hashlib
import json
from datetime import datetime
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.context import get_tenant_context, get_trace_id
from app.core.errors import AppError
from app.domain.evidence import (
    DataProfile,
    EvidenceBundle,
    PythonSourceEvidenceProvider,
    SourceSnapshot,
    data_profile_evidence,
)
from app.domain.flow_spec import FlowSpec
from app.domain.mcp_read import (
    MCP_READ_SCOPE,
    EvidenceRef,
    MCPReadCall,
    MCPReadEnvelope,
)
from app.domain.test_design import normalized_design
from app.models.access import Project, User
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.service_targets import Service, ServiceEndpoint
from app.models.workflows import Workflow, WorkflowExecution, WorkflowNodeExecution
from app.repositories.api_assets import APIAssetRepository
from app.repositories.service_targets import ServiceTargetRepository
from app.repositories.workflows import WorkflowRepository
from app.schemas.test_engineering import TestEngineeringGenerateRequest
from app.services.audit import AuditService
from app.services.flow_spec import FlowSpecService
from app.services.impact import ImpactService
from app.services.projects import ProjectService
from app.services.test_engineering import TestEngineeringService
from app.services.workflows import WorkflowService

MAX_CONTRACTS = 100


class MCPReadService:
    """Read-only, tenant-scoped application service used by REST and MCP."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._targets = ServiceTargetRepository(session)
        self._assets = APIAssetRepository(session)
        self._workflows = WorkflowRepository(session)
        self._workflow_service = WorkflowService(session)
        self._audit = AuditService(session)

    async def list_projects(
        self,
        *,
        actor: User,
        call: MCPReadCall,
        page: int,
        page_size: int,
    ) -> MCPReadEnvelope:
        self._require_scope()
        projects, total = await self._projects.list_projects(
            actor=actor,
            page=page,
            page_size=page_size,
        )
        data: dict[str, JsonValue] = {
            "items": [_project_summary(access.project) for access in projects],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
        return await self._envelope(
            actor=actor,
            call=call,
            data=data,
            evidence_refs=[
                EvidenceRef(uri="flowtest://projects", kind="project-index", version="v1")
            ],
            redactions=["project.description", "project.variables", "project.headers"],
        )

    async def get_project(
        self,
        *,
        actor: User,
        project_id: UUID,
        call: MCPReadCall,
    ) -> MCPReadEnvelope:
        self._require_scope()
        access = await self._projects.get(actor=actor, project_id=project_id)
        return await self._envelope(
            actor=actor,
            call=call,
            project_id=project_id,
            data=_project_summary(access.project),
            evidence_refs=[
                EvidenceRef(
                    uri=f"flowtest://projects/{project_id}",
                    kind="project",
                    version="v1",
                )
            ],
            redactions=["project.description", "project.variables", "project.headers"],
        )

    async def discover_services(
        self,
        *,
        actor: User,
        project_id: UUID,
        call: MCPReadCall,
        environment_id: UUID | None,
    ) -> MCPReadEnvelope:
        self._require_scope()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        environments = await self._assets.list_environments(project_id)
        environment_map = {environment.id: environment for environment in environments}
        if environment_id is not None and environment_id not in environment_map:
            raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)
        services = await self._targets.list_services(project_id)
        endpoints = await self._targets.list_endpoints(
            project_id=project_id,
            environment_id=environment_id,
        )
        service_map = {service.id: service for service in services}
        data: dict[str, JsonValue] = {
            "services": [_service_summary(service) for service in services],
            "environments": [
                _environment_summary(environment)
                for environment in environments
                if environment_id is None or environment.id == environment_id
            ],
            "endpoints": [
                _endpoint_summary(endpoint, service_map.get(endpoint.service_id), environment_map)
                for endpoint in endpoints
            ],
        }
        return await self._envelope(
            actor=actor,
            call=call,
            project_id=project_id,
            data=data,
            evidence_refs=[
                EvidenceRef(
                    uri=f"flowtest://projects/{project_id}/services",
                    kind="service-discovery",
                    version="v1",
                )
            ],
            redactions=[
                "service_endpoint.headers",
                "service_endpoint.variables",
                "service_endpoint.secret_refs",
                "service_endpoint.proxy_ref",
                "environment.headers",
                "environment.variables",
            ],
        )

    async def inspect_contract(
        self,
        *,
        actor: User,
        project_id: UUID,
        call: MCPReadCall,
        api_definition_id: UUID | None,
    ) -> MCPReadEnvelope:
        self._require_scope()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        definitions: list[APIDefinition]
        if api_definition_id is None:
            definitions, _ = await self._assets.list_definitions(
                project_id=project_id,
                offset=0,
                limit=MAX_CONTRACTS,
            )
        else:
            definition = await self._assets.get_definition(api_definition_id)
            if definition is None or definition.project_id != project_id:
                raise AppError(
                    code="API_DEFINITION_NOT_FOUND", message="API 定义不存在", status_code=404
                )
            definitions = [definition]
        entries: list[JsonValue] = []
        for definition in definitions:
            version = await self._assets.get_version(
                definition_id=definition.id,
                version=definition.current_version,
            )
            if version is not None:
                entries.append(_contract_summary(definition, version))
        return await self._envelope(
            actor=actor,
            call=call,
            project_id=project_id,
            data={"items": entries, "total": len(entries)},
            evidence_refs=[
                EvidenceRef(
                    uri=f"flowtest://projects/{project_id}/contract",
                    kind="api-contract",
                    version="v1",
                )
            ],
            redactions=[
                "api_version.headers",
                "api_version.variables",
                "api_version.body",
                "api_version.auth_config",
                "api_version.extraction_rules.expression",
                "api_version.assertions.expected",
            ],
            warnings=["仅返回当前版本的结构化摘要；请求值、认证值和断言期望值已省略。"],
        )

    async def inspect_workflow(
        self,
        *,
        actor: User,
        workflow_id: UUID,
        call: MCPReadCall,
    ) -> MCPReadEnvelope:
        self._require_scope()
        workflow = await self._workflows.get(workflow_id)
        if workflow is None:
            raise AppError(code="WORKFLOW_NOT_FOUND", message="工作流不存在", status_code=404)
        await self._projects.authorize(actor=actor, project_id=workflow.project_id, editing=False)
        data = _workflow_summary(workflow)
        return await self._envelope(
            actor=actor,
            call=call,
            project_id=workflow.project_id,
            data=data,
            evidence_refs=[
                EvidenceRef(
                    uri=f"flowtest://drafts/{workflow_id}",
                    kind="workflow-draft",
                    version="v1",
                )
            ],
            redactions=[
                "workflow.node.config",
                "workflow.runtime_variables",
                "workflow.request_headers",
                "workflow.request_body",
                "workflow.assertion.expected",
            ],
        )

    async def inspect_run_evidence(
        self,
        *,
        actor: User,
        execution_id: UUID,
        call: MCPReadCall,
    ) -> MCPReadEnvelope:
        self._require_scope()
        execution = await self._workflows.get_execution(execution_id)
        if execution is None:
            raise AppError(
                code="WORKFLOW_EXECUTION_NOT_FOUND",
                message="工作流执行不存在",
                status_code=404,
            )
        execution, nodes, children = await self._workflow_service.get_execution(
            actor=actor,
            project_id=execution.project_id,
            execution_id=execution_id,
        )
        data: dict[str, JsonValue] = {
            "execution": _execution_summary(execution),
            "nodes": [_node_execution_summary(node) for node in nodes],
            "children": [_execution_summary(child) for child in children],
        }
        return await self._envelope(
            actor=actor,
            call=call,
            project_id=execution.project_id,
            data=data,
            evidence_refs=[
                EvidenceRef(
                    uri=f"flowtest://runs/{execution_id}/evidence",
                    kind="execution-evidence",
                    version="v1",
                )
            ],
            redactions=[
                "execution.snapshot",
                "execution.context",
                "execution.run_payload",
                "execution.error_message",
                "node.output",
                "node.result",
                "node.error_message",
            ],
        )

    async def generate_test_design(
        self,
        *,
        actor: User,
        project_id: UUID,
        call: MCPReadCall,
        payload: TestEngineeringGenerateRequest,
        coverage_only: bool = False,
    ) -> MCPReadEnvelope:
        self._require_scope()
        design, fingerprint = await TestEngineeringService(self._session).generate(
            actor=actor, project_id=project_id, payload=payload
        )
        data = (
            cast(JsonValue, design.coverage.model_dump(mode="json"))
            if coverage_only
            else cast(
                JsonValue,
                {
                    "fingerprint": fingerprint,
                    "design": normalized_design(design),
                    "persisted": False,
                },
            )
        )
        refs = [
            EvidenceRef(
                uri=ref.source_ref,
                kind=ref.source_type.value,
                version=ref.revision,
            )
            for ref in design.evidence_refs[:200]
        ]
        return await self._envelope(
            actor=actor,
            call=call,
            project_id=project_id,
            data=data,
            evidence_refs=refs,
            confidence=design.confidence,
            warnings=design.warnings,
        )

    async def inspect_source_evidence(
        self,
        *,
        actor: User,
        project_id: UUID,
        call: MCPReadCall,
        snapshot: SourceSnapshot,
    ) -> MCPReadEnvelope:
        self._require_scope()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        bundle = PythonSourceEvidenceProvider().analyze(snapshot)
        return await self._evidence_envelope(actor, project_id, call, bundle)

    async def inspect_data_profile(
        self,
        *,
        actor: User,
        project_id: UUID,
        call: MCPReadCall,
        profile: DataProfile,
    ) -> MCPReadEnvelope:
        self._require_scope()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._evidence_envelope(
            actor, project_id, call, data_profile_evidence(profile)
        )

    async def validate_flow_spec(
        self,
        *,
        actor: User,
        project_id: UUID,
        call: MCPReadCall,
        spec: FlowSpec,
    ) -> MCPReadEnvelope:
        self._require_scope()
        pipeline = await FlowSpecService(self._session).validate(
            actor=actor, project_id=project_id, spec=spec
        )
        return await self._envelope(
            actor=actor,
            call=call,
            project_id=project_id,
            data=cast(
                JsonValue,
                {
                    "fingerprint": pipeline.fingerprint,
                    "spec": pipeline.spec.model_dump(mode="json"),
                    "validation": pipeline.validation.model_dump(mode="json"),
                    "compatibility": pipeline.compatibility.model_dump(mode="json"),
                },
            ),
            evidence_refs=[
                EvidenceRef(
                    uri=f"flowtest://flowspec/{pipeline.fingerprint}",
                    kind="flow-spec-validation",
                    version=pipeline.spec.fingerprint_version,
                )
            ],
        )

    async def diff_flow_specs(
        self,
        *,
        actor: User,
        project_id: UUID,
        call: MCPReadCall,
        before: FlowSpec | None,
        after: FlowSpec,
    ) -> MCPReadEnvelope:
        self._require_scope()
        result = await FlowSpecService(self._session).diff(
            actor=actor, project_id=project_id, before=before, after=after
        )
        return await self._envelope(
            actor=actor,
            call=call,
            project_id=project_id,
            data={
                "before_fingerprint": result.before_fingerprint,
                "after_fingerprint": result.after_fingerprint,
                "changes": cast(
                    list[JsonValue], [item.model_dump(mode="json") for item in result.changes]
                ),
            },
            evidence_refs=[
                EvidenceRef(
                    uri=f"flowtest://flowspec/{result.after_fingerprint}",
                    kind="flow-spec-diff",
                    version="v1",
                )
            ],
        )

    async def export_flow_spec(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow_id: UUID,
        version: int | None,
        call: MCPReadCall,
    ) -> MCPReadEnvelope:
        self._require_scope()
        exported = await FlowSpecService(self._session).export(
            actor=actor,
            project_id=project_id,
            workflow_id=workflow_id,
            version=version,
        )
        return await self._envelope(
            actor=actor,
            call=call,
            project_id=project_id,
            data={
                "workflow_id": str(workflow_id),
                "version": version,
                "fingerprint": exported.pipeline.fingerprint,
                "spec": cast(JsonValue, exported.pipeline.spec.model_dump(mode="json")),
                "validation": cast(JsonValue, exported.pipeline.validation.model_dump(mode="json")),
                "compatibility": cast(
                    JsonValue, exported.pipeline.compatibility.model_dump(mode="json")
                ),
            },
            evidence_refs=[
                EvidenceRef(
                    uri=f"flowtest://flowspec/{exported.pipeline.fingerprint}",
                    kind="flow-spec-export",
                    version=exported.pipeline.spec.fingerprint_version,
                )
            ],
            redactions=["secret_values", "instance_resource_ids"],
        )

    async def inspect_change_impact(
        self,
        *,
        actor: User,
        project_id: UUID,
        impact_run_id: UUID,
        call: MCPReadCall,
    ) -> MCPReadEnvelope:
        self._require_scope()
        bundle = await ImpactService(
            self._session, enabled=settings.feature_impact_engine_enabled
        ).get_run(actor=actor, project_id=project_id, run_id=impact_run_id)
        return await self._envelope(
            actor=actor,
            call=call,
            project_id=project_id,
            data=cast(
                JsonValue,
                {
                    "impact_run_id": str(bundle.run.id),
                    "source_ref": bundle.run.source_ref,
                    "source_fingerprint": bundle.run.source_fingerprint,
                    "changes": bundle.run.changes,
                    "summary": bundle.run.summary,
                    "selected_assets": bundle.selection.selected_assets,
                    "coverage": {
                        "total_changes": bundle.coverage.total_changes,
                        "covered_changes": bundle.coverage.covered_changes,
                        "coverage_percent": bundle.coverage.coverage_percent,
                        "gaps": bundle.coverage.gaps,
                    },
                },
            ),
            evidence_refs=[
                EvidenceRef(
                    uri=f"flowtest://change-impact/{bundle.run.id}",
                    kind="structured-change-impact",
                    version="v2",
                )
            ],
            redactions=["git_diff", "request_values", "secret_values", "pii_values"],
        )

    async def _evidence_envelope(
        self,
        actor: User,
        project_id: UUID,
        call: MCPReadCall,
        bundle: EvidenceBundle,
    ) -> MCPReadEnvelope:
        refs = [
            EvidenceRef(
                uri=finding.source_ref,
                kind=finding.kind,
                version=finding.revision,
            )
            for finding in bundle.findings[:200]
        ]
        return await self._envelope(
            actor=actor,
            call=call,
            project_id=project_id,
            data=cast(JsonValue, bundle.model_dump(mode="json")),
            evidence_refs=refs,
            confidence=min((item.confidence for item in bundle.findings), default=1),
            redactions=["source.content", "raw_rows", "secret_values", "pii_values"],
            warnings=bundle.warnings,
        )

    def _require_scope(self) -> None:
        context = get_tenant_context()
        if context is None or MCP_READ_SCOPE not in context.scopes:
            raise AppError(
                code="MCP_SCOPE_REQUIRED",
                message="MCP 需要只读权限范围",
                status_code=403,
            )

    async def _envelope(
        self,
        *,
        actor: User,
        call: MCPReadCall,
        data: JsonValue,
        evidence_refs: list[EvidenceRef],
        project_id: UUID | None = None,
        confidence: float = 1.0,
        redactions: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> MCPReadEnvelope:
        self._require_scope()
        context = get_tenant_context()
        if context is None:
            raise AppError(
                code="MCP_SCOPE_REQUIRED",
                message="MCP 需要只读权限范围",
                status_code=403,
            )
        safe_resource_uri = _safe_resource_uri(call.resource_uri)
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=context.organization_id,
            project_id=project_id,
            action=f"mcp.{call.call_type.value}.read",
            resource_type="mcp_read",
            resource_id=project_id,
            details={
                "server_version": "s41-read-v1",
                "operation": call.operation,
                "input_schema_hash": call.input_schema_hash,
                "client_version": call.client_version,
                "resource_uri": safe_resource_uri,
                "evidence_refs": [ref.model_dump(mode="json") for ref in evidence_refs],
                "confidence": confidence,
                "redactions": redactions or [],
            },
        )
        await self._session.commit()
        return MCPReadEnvelope(
            data=data,
            evidence_refs=evidence_refs,
            confidence=confidence,
            redactions=redactions or [],
            trace_id=get_trace_id(),
            warnings=warnings or [],
        )


def _project_summary(project: Project) -> dict[str, JsonValue]:
    return {
        "id": str(project.id),
        "organization_id": str(project.organization_id) if project.organization_id else None,
        "name": project.name,
        "created_at": _timestamp(project.created_at),
        "updated_at": _timestamp(project.updated_at),
        "outbound_policy_enabled": project.outbound_policy_enabled,
        "retention_days": project.retention_days,
        "execution_concurrency_limit": project.execution_concurrency_limit,
    }


def _service_summary(service: Service) -> dict[str, JsonValue]:
    return {
        "id": str(service.id),
        "project_id": str(service.project_id),
        "service_key": service.service_key,
        "name": service.name,
        "service_type": service.service_type,
        "enabled": service.enabled,
    }


def _environment_summary(environment: Environment) -> dict[str, JsonValue]:
    return {
        "id": str(environment.id),
        "name": environment.name,
        "base_origin": _safe_origin(environment.base_url),
        "default_service_id": (
            str(environment.default_service_id) if environment.default_service_id else None
        ),
    }


def _endpoint_summary(
    endpoint: ServiceEndpoint,
    service: Service | None,
    environments: dict[UUID, Environment],
) -> dict[str, JsonValue]:
    environment = environments.get(endpoint.environment_id)
    return {
        "id": str(endpoint.id),
        "project_id": str(endpoint.project_id),
        "environment_id": str(endpoint.environment_id),
        "environment_name": environment.name if environment else None,
        "service_id": str(endpoint.service_id),
        "service_key": service.service_key if service else None,
        "variant": endpoint.variant,
        "revision": endpoint.revision,
        "base_origin": _safe_origin(endpoint.base_url),
        "enabled": endpoint.enabled,
        "tls_verify": endpoint.tls_verify,
        "connect_timeout_ms": endpoint.connect_timeout_ms,
        "read_timeout_ms": endpoint.read_timeout_ms,
        "proxy_configured": bool(endpoint.proxy_ref),
        "secret_ref_count": len(endpoint.secret_refs),
    }


def _contract_summary(definition: APIDefinition, version: APIVersion) -> dict[str, JsonValue]:
    return {
        "id": str(definition.id),
        "name": definition.name,
        "service_id": str(definition.service_id) if definition.service_id else None,
        "is_active": definition.is_active,
        "current_version": definition.current_version,
        "version": version.version,
        "method": version.method,
        "path": _safe_path(version.path),
        "query_parameter_names": _names(version.query_parameters),
        "body_kind": version.body_kind,
        "auth_kind": version.auth_kind,
        "assertion_kinds": _string_values(version.assertions, "kind"),
        "extraction_names": _string_values(version.extraction_rules, "name"),
    }


def _workflow_summary(workflow: Workflow) -> dict[str, JsonValue]:
    definition = workflow.draft_definition if isinstance(workflow.draft_definition, dict) else {}
    nodes = definition.get("nodes", [])
    edges = definition.get("edges", [])
    node_values = nodes if isinstance(nodes, list) else []
    edge_values = edges if isinstance(edges, list) else []
    return {
        "id": str(workflow.id),
        "project_id": str(workflow.project_id),
        "name": workflow.name,
        "draft_revision": workflow.draft_revision,
        "current_version": workflow.current_version,
        "draft_fingerprint": _fingerprint(definition),
        "nodes": [_node_summary(node) for node in node_values if isinstance(node, dict)],
        "edges": [_edge_summary(edge) for edge in edge_values if isinstance(edge, dict)],
    }


def _node_summary(node: dict[str, Any]) -> dict[str, JsonValue]:
    depends_on = node.get("depends_on", [])
    return {
        "id": _safe_scalar(node.get("id"), "unknown"),
        "kind": _safe_scalar(node.get("type", node.get("kind")), "unknown"),
        "name": _safe_scalar(node.get("name"), ""),
        "depends_on": [str(value) for value in depends_on if isinstance(value, (str, int))]
        if isinstance(depends_on, list)
        else [],
        "operation_ref": _operation_ref(node),
    }


def _edge_summary(edge: dict[str, Any]) -> dict[str, JsonValue]:
    return {
        "source": _safe_scalar(edge.get("source", edge.get("from")), ""),
        "target": _safe_scalar(edge.get("target", edge.get("to")), ""),
    }


def _operation_ref(node: dict[str, Any]) -> dict[str, JsonValue] | None:
    config = node.get("config")
    if not isinstance(config, dict):
        return None
    allowed = (
        "api_definition_id",
        "api_version",
        "service_id",
        "service_key",
        "endpoint_variant",
    )
    values = {
        key: config[key]
        for key in allowed
        if key in config and isinstance(config[key], (str, int, float, bool))
    }
    return values or None


def _execution_summary(execution: WorkflowExecution) -> dict[str, JsonValue]:
    return {
        "id": str(execution.id),
        "project_id": str(execution.project_id),
        "workflow_id": str(execution.workflow_id),
        "workflow_version_id": str(execution.workflow_version_id),
        "environment_id": str(execution.environment_id),
        "status": execution.status,
        "error_code": execution.error_code,
        "dataset_row_index": execution.dataset_row_index,
        "started_at": _timestamp(execution.started_at),
        "completed_at": _timestamp(execution.completed_at),
    }


def _node_execution_summary(node: WorkflowNodeExecution) -> dict[str, JsonValue]:
    return {
        "id": str(node.id),
        "node_id": node.node_id,
        "node_type": node.node_type,
        "name": node.name,
        "status": node.status,
        "attempts": node.attempts,
        "error_code": node.error_code,
        "started_at": _timestamp(node.started_at),
        "completed_at": _timestamp(node.completed_at),
    }


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _safe_scalar(value: Any, fallback: str) -> str | int | float | bool:
    return value if isinstance(value, (str, int, float, bool)) else fallback


def _names(values: Any) -> JsonValue:
    if not isinstance(values, list):
        return []
    names: set[str] = set()
    for item in values:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.add(item["name"])
    return cast(JsonValue, sorted(names))


def _string_values(values: Any, key: str) -> JsonValue:
    if not isinstance(values, list):
        return []
    result: set[str] = set()
    for item in values:
        if isinstance(item, dict) and isinstance(item.get(key), str):
            result.add(item[key])
    return cast(JsonValue, sorted(result))


def _fingerprint(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not hostname:
            return "[redacted]"
        host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"{parsed.scheme}://{host}{port}"
    except ValueError:
        return "[redacted]"


def _safe_path(value: str) -> str:
    try:
        parsed = urlsplit(value)
        return parsed.path or "/"
    except ValueError:
        return "/"


def _safe_resource_uri(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme != "flowtest" or parsed.username or parsed.password:
        return None
    return f"flowtest://{parsed.netloc}{parsed.path}"
