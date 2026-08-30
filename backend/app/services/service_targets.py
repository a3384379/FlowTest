from __future__ import annotations

from time import perf_counter
from typing import Protocol
from urllib.parse import urljoin
from uuid import UUID

import httpx
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.network import OutboundNetworkPolicy
from app.models.access import Project, User
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.release_gate import ReleasePolicy
from app.models.service_targets import Service, ServiceEndpoint
from app.models.tasking import TestPlan, TestPlanItem
from app.models.workflows import Workflow, WorkflowVersion
from app.repositories.service_targets import ServiceTargetRepository
from app.services.audit import AuditService
from app.services.outbound import OutboundRequestGuard, outbound_request_guard
from app.services.projects import ProjectService


class ServiceTargetService:
    """Application boundary for project request services and endpoint variants."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        outbound_guard: OutboundRequestGuard = outbound_request_guard,
    ) -> None:
        self._session = session
        self._targets = ServiceTargetRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)
        self._outbound_guard = outbound_guard

    async def list_services(self, *, actor: User, project_id: UUID) -> list[Service]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._targets.list_services(project_id)

    async def create_service(
        self,
        *,
        actor: User,
        project_id: UUID,
        service_key: str,
        name: str,
        description: str,
        owner_team: str | None,
        service_type: str,
        enabled: bool,
    ) -> Service:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        normalized_key = service_key.strip()
        if await self._targets.find_service_by_key(
            project_id=project_id,
            service_key=normalized_key,
        ):
            raise AppError(code="SERVICE_KEY_EXISTS", message="Service Key 已存在", status_code=409)
        service = Service(
            project_id=project_id,
            service_key=normalized_key,
            name=name.strip(),
            description=description.strip(),
            owner_team=owner_team.strip() if owner_team else None,
            service_type=service_type,
            enabled=enabled,
            created_by_id=actor.id,
        )
        self._targets.add(service)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="service_target.created",
            resource_type="service",
            resource_id=service.id,
            details={"service_key": service.service_key},
        )
        await self._session.commit()
        await self._session.refresh(service)
        return service

    async def update_service(
        self,
        *,
        actor: User,
        project_id: UUID,
        service_id: UUID,
        name: str | None,
        description: str | None,
        owner_team: str | None,
        service_type: str | None,
        enabled: bool | None,
    ) -> Service:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        service = await self._get_service(project_id=project_id, service_id=service_id)
        if name is not None:
            service.name = name.strip()
        if description is not None:
            service.description = description.strip()
        if owner_team is not None:
            service.owner_team = owner_team.strip() or None
        if service_type is not None:
            service.service_type = service_type
        if enabled is not None:
            service.enabled = enabled
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="service_target.updated",
            resource_type="service",
            resource_id=service.id,
            details={"service_key": service.service_key},
        )
        await self._session.commit()
        await self._session.refresh(service)
        return service

    async def list_endpoints(
        self,
        *,
        actor: User,
        project_id: UUID,
        environment_id: UUID | None,
    ) -> list[ServiceEndpoint]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        if environment_id is not None:
            await self._get_environment(project_id=project_id, environment_id=environment_id)
        return await self._targets.list_endpoints(
            project_id=project_id,
            environment_id=environment_id,
        )

    async def impact_preview(
        self,
        *,
        actor: User,
        project_id: UUID,
        service_id: UUID,
    ) -> dict[str, object]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        service = await self._get_service(project_id=project_id, service_id=service_id)
        apis = list(
            (
                await self._session.scalars(
                    select(APIDefinition)
                    .join(APIVersion, APIVersion.api_definition_id == APIDefinition.id)
                    .where(
                        APIDefinition.project_id == project_id,
                        APIVersion.service_id == service_id,
                    )
                    .distinct()
                )
            ).all()
        )
        affected_versions = list(
            (
                await self._session.scalars(
                    select(APIVersion)
                    .join(APIDefinition, APIDefinition.id == APIVersion.api_definition_id)
                    .where(
                        APIDefinition.project_id == project_id,
                        APIVersion.service_id == service_id,
                    )
                )
            ).all()
        )
        workflows = list(
            (
                await self._session.scalars(
                    select(Workflow).where(Workflow.project_id == project_id)
                )
            ).all()
        )
        version_refs = {
            (str(version.api_definition_id), version.version) for version in affected_versions
        }
        current_versions = {str(api.id): api.current_version for api in apis}
        draft_affected_workflows = [
            workflow
            for workflow in workflows
            if _workflow_uses_service(
                workflow.draft_definition,
                service.service_key,
                version_refs,
                current_versions,
            )
        ]
        referenced_versions = (
            await self._session.execute(
                select(TestPlanItem, WorkflowVersion)
                .join(TestPlan, TestPlan.id == TestPlanItem.test_plan_id)
                .join(
                    WorkflowVersion,
                    and_(
                        WorkflowVersion.workflow_id == TestPlanItem.workflow_id,
                        WorkflowVersion.version == TestPlanItem.workflow_version,
                    ),
                )
                .where(
                    TestPlan.project_id == project_id,
                    TestPlanItem.target_type == "workflow",
                )
            )
        ).all()
        published_workflow_ids: set[UUID] = set()
        affected_plan_ids: set[UUID] = set()
        for item, version in referenced_versions:
            if _workflow_uses_service(
                version.definition,
                service.service_key,
                version_refs,
                current_versions,
            ):
                published_workflow_ids.add(version.workflow_id)
                affected_plan_ids.add(item.test_plan_id)
        affected_workflow_ids = {
            workflow.id for workflow in draft_affected_workflows
        } | published_workflow_ids
        affected_workflows = [
            workflow for workflow in workflows if workflow.id in affected_workflow_ids
        ]
        plans = await self._affected_plans(project_id, affected_plan_ids)
        release_policies = (
            list(
                (
                    await self._session.scalars(
                        select(ReleasePolicy).where(
                            ReleasePolicy.project_id == project_id,
                            ReleasePolicy.enabled.is_(True),
                        )
                    )
                ).all()
            )
            if plans
            else []
        )
        return {
            "strategy": "request_target_dependency_v1",
            "service_id": service.id,
            "service_key": service.service_key,
            "affected_apis": [_impact_item(api, "API 版本绑定 Service") for api in apis],
            "affected_workflows": [
                _impact_item(workflow, "Workflow 节点继承或覆盖 Service")
                for workflow in affected_workflows
            ],
            "affected_test_plans": [
                _impact_item(plan, "Test Plan 包含受影响 Workflow") for plan in plans
            ],
            "affected_scheduled_runs": [
                _impact_item(plan, "Test Plan 已配置定时触发")
                for plan in plans
                if plan.schedule_interval_seconds is not None or plan.schedule_cron is not None
            ],
            "affected_release_gates": [
                _impact_item(policy, "受影响 Test Plan 可作为发布门禁证据")
                for policy in release_policies
            ],
        }

    async def _affected_plans(self, project_id: UUID, plan_ids: set[UUID]) -> list[TestPlan]:
        if not plan_ids:
            return []
        return list(
            (
                await self._session.scalars(
                    select(TestPlan).where(
                        TestPlan.project_id == project_id, TestPlan.id.in_(plan_ids)
                    )
                )
            ).all()
        )

    async def create_endpoint(
        self,
        *,
        actor: User,
        project_id: UUID,
        environment_id: UUID,
        service_id: UUID,
        variant: str,
        base_url: str,
        enabled: bool,
        connect_timeout_ms: int,
        read_timeout_ms: int,
        tls_verify: bool,
        proxy_ref: str | None,
        headers: dict[str, str],
        variables: dict[str, str],
        secret_refs: list[str],
        health_check_path: str | None,
        health_expected_status: int | None,
    ) -> ServiceEndpoint:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        await self._get_environment(project_id=project_id, environment_id=environment_id)
        await self._get_service(project_id=project_id, service_id=service_id)
        if await self._targets.find_endpoint(
            environment_id=environment_id,
            service_id=service_id,
            variant=variant,
        ):
            raise AppError(
                code="SERVICE_ENDPOINT_EXISTS",
                message="该环境下的 Service Endpoint Variant 已存在",
                status_code=409,
            )
        _validate_headers(headers)
        endpoint = ServiceEndpoint(
            project_id=project_id,
            environment_id=environment_id,
            service_id=service_id,
            variant=variant,
            base_url=base_url.rstrip("/"),
            enabled=enabled,
            connect_timeout_ms=connect_timeout_ms,
            read_timeout_ms=read_timeout_ms,
            tls_verify=tls_verify,
            proxy_ref=proxy_ref,
            headers=headers,
            variables=variables,
            secret_refs=secret_refs,
            health_check_path=health_check_path,
            health_expected_status=health_expected_status,
            created_by_id=actor.id,
        )
        self._targets.add(endpoint)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="service_endpoint.created",
            resource_type="service_endpoint",
            resource_id=endpoint.id,
            details={"variant": endpoint.variant, "service_id": str(service_id)},
        )
        await self._session.commit()
        await self._session.refresh(endpoint)
        return endpoint

    async def update_endpoint(
        self,
        *,
        actor: User,
        project_id: UUID,
        endpoint_id: UUID,
        variant: str | None,
        base_url: str | None,
        enabled: bool | None,
        connect_timeout_ms: int | None,
        read_timeout_ms: int | None,
        tls_verify: bool | None,
        proxy_ref: str | None,
        headers: dict[str, str] | None,
        variables: dict[str, str] | None,
        secret_refs: list[str] | None,
        health_check_path: str | None,
        health_expected_status: int | None,
        changed_fields: set[str],
    ) -> ServiceEndpoint:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        endpoint = await self._get_endpoint(project_id=project_id, endpoint_id=endpoint_id)
        next_variant = (
            variant if "variant" in changed_fields and variant is not None else endpoint.variant
        )
        if next_variant != endpoint.variant and await self._targets.find_endpoint(
            environment_id=endpoint.environment_id,
            service_id=endpoint.service_id,
            variant=next_variant,
        ):
            raise AppError(
                code="SERVICE_ENDPOINT_EXISTS",
                message="该环境下的 Service Endpoint Variant 已存在",
                status_code=409,
            )
        _apply_endpoint_updates(
            endpoint=endpoint,
            variant=variant,
            base_url=base_url,
            enabled=enabled,
            connect_timeout_ms=connect_timeout_ms,
            read_timeout_ms=read_timeout_ms,
            tls_verify=tls_verify,
            proxy_ref=proxy_ref,
            headers=headers,
            variables=variables,
            secret_refs=secret_refs,
            health_check_path=health_check_path,
            health_expected_status=health_expected_status,
            changed_fields=changed_fields,
        )
        endpoint.revision += 1
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="service_endpoint.updated",
            resource_type="service_endpoint",
            resource_id=endpoint.id,
            details={"variant": endpoint.variant, "revision": endpoint.revision},
        )
        await self._session.commit()
        await self._session.refresh(endpoint)
        return endpoint

    async def check_connectivity(
        self,
        *,
        actor: User,
        project_id: UUID,
        endpoint_id: UUID,
    ) -> dict[str, object]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        endpoint = await self._get_endpoint(project_id=project_id, endpoint_id=endpoint_id)
        project = await self._session.get(Project, project_id)
        if project is None:
            raise AppError(code="PROJECT_NOT_FOUND", message="项目不存在", status_code=404)
        policy = OutboundNetworkPolicy(
            allowed_hosts=tuple(project.outbound_allowed_hosts),
            allowed_private_cidrs=tuple(project.outbound_allowed_private_cidrs),
            enabled=project.outbound_policy_enabled,
        ).normalized()
        url = _health_url(endpoint)
        addresses = await self._outbound_guard.enforce(url, policy)
        started = perf_counter()
        try:
            timeout = httpx.Timeout(
                connect=endpoint.connect_timeout_ms / 1000,
                read=endpoint.read_timeout_ms / 1000,
                write=endpoint.read_timeout_ms / 1000,
                pool=endpoint.connect_timeout_ms / 1000,
            )
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=timeout,
                verify=endpoint.tls_verify,
            ) as client:
                response = await client.head(url, headers={"User-Agent": "FlowTest/0.1"})
        except httpx.TimeoutException:
            return {
                "endpoint_id": endpoint.id,
                "status": "timeout",
                "dns": ", ".join(addresses),
                "http_status": None,
                "latency_ms": (perf_counter() - started) * 1000,
                "redirect": False,
                "error_code": "CONNECT_TIMEOUT",
            }
        except httpx.HTTPError:
            return {
                "endpoint_id": endpoint.id,
                "status": "unreachable",
                "dns": ", ".join(addresses),
                "http_status": None,
                "latency_ms": (perf_counter() - started) * 1000,
                "redirect": False,
                "error_code": "CONNECTIVITY_ERROR",
            }
        expected = endpoint.health_expected_status
        status = (
            "reachable"
            if expected is None or response.status_code == expected
            else "unexpected_status"
        )
        return {
            "endpoint_id": endpoint.id,
            "status": status,
            "dns": ", ".join(addresses),
            "http_status": response.status_code,
            "latency_ms": (perf_counter() - started) * 1000,
            "redirect": 300 <= response.status_code < 400,
            "error_code": None,
        }

    async def _get_service(self, *, project_id: UUID, service_id: UUID) -> Service:
        service = await self._targets.get_service(service_id)
        if service is None or service.project_id != project_id:
            raise AppError(code="SERVICE_NOT_FOUND", message="Service 不存在", status_code=404)
        return service

    async def _get_environment(self, *, project_id: UUID, environment_id: UUID) -> Environment:
        environment = await self._session.get(Environment, environment_id)
        if environment is None or environment.project_id != project_id:
            raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)
        return environment

    async def _get_endpoint(self, *, project_id: UUID, endpoint_id: UUID) -> ServiceEndpoint:
        endpoint = await self._targets.get_endpoint(endpoint_id)
        if endpoint is None or endpoint.project_id != project_id:
            raise AppError(
                code="SERVICE_ENDPOINT_NOT_FOUND",
                message="Service Endpoint 不存在",
                status_code=404,
            )
        return endpoint


def _apply_endpoint_updates(
    *,
    endpoint: ServiceEndpoint,
    variant: str | None,
    base_url: str | None,
    enabled: bool | None,
    connect_timeout_ms: int | None,
    read_timeout_ms: int | None,
    tls_verify: bool | None,
    proxy_ref: str | None,
    headers: dict[str, str] | None,
    variables: dict[str, str] | None,
    secret_refs: list[str] | None,
    health_check_path: str | None,
    health_expected_status: int | None,
    changed_fields: set[str],
) -> None:
    _apply_endpoint_metadata(
        endpoint=endpoint,
        variant=variant,
        base_url=base_url,
        proxy_ref=proxy_ref,
        health_check_path=health_check_path,
        health_expected_status=health_expected_status,
        changed_fields=changed_fields,
    )
    _apply_endpoint_connection_settings(
        endpoint=endpoint,
        enabled=enabled,
        connect_timeout_ms=connect_timeout_ms,
        read_timeout_ms=read_timeout_ms,
        tls_verify=tls_verify,
    )
    _apply_endpoint_values(
        endpoint=endpoint,
        headers=headers,
        variables=variables,
        secret_refs=secret_refs,
    )


def _apply_endpoint_metadata(
    *,
    endpoint: ServiceEndpoint,
    variant: str | None,
    base_url: str | None,
    proxy_ref: str | None,
    health_check_path: str | None,
    health_expected_status: int | None,
    changed_fields: set[str],
) -> None:
    if "variant" in changed_fields and variant is not None:
        endpoint.variant = variant
    if "base_url" in changed_fields and base_url is not None:
        endpoint.base_url = base_url.rstrip("/")
    if "proxy_ref" in changed_fields:
        endpoint.proxy_ref = proxy_ref
    if "health_check_path" in changed_fields:
        endpoint.health_check_path = health_check_path
    if "health_expected_status" in changed_fields:
        endpoint.health_expected_status = health_expected_status


def _apply_endpoint_connection_settings(
    *,
    endpoint: ServiceEndpoint,
    enabled: bool | None,
    connect_timeout_ms: int | None,
    read_timeout_ms: int | None,
    tls_verify: bool | None,
) -> None:
    if enabled is not None:
        endpoint.enabled = enabled
    if connect_timeout_ms is not None:
        endpoint.connect_timeout_ms = connect_timeout_ms
    if read_timeout_ms is not None:
        endpoint.read_timeout_ms = read_timeout_ms
    if tls_verify is not None:
        endpoint.tls_verify = tls_verify


def _apply_endpoint_values(
    *,
    endpoint: ServiceEndpoint,
    headers: dict[str, str] | None,
    variables: dict[str, str] | None,
    secret_refs: list[str] | None,
) -> None:
    if headers is not None:
        _validate_headers(headers)
        endpoint.headers = headers
    if variables is not None:
        endpoint.variables = variables
    if secret_refs is not None:
        endpoint.secret_refs = secret_refs


def _health_url(endpoint: ServiceEndpoint) -> str:
    base_url = endpoint.base_url.rstrip("/") + "/"
    path = endpoint.health_check_path or ""
    return urljoin(base_url, path.lstrip("/"))


def _workflow_uses_service(
    definition: dict[str, object],
    service_key: str,
    version_refs: set[tuple[str, int]],
    current_versions: dict[str, int],
) -> bool:
    nodes = definition.get("nodes")
    if not isinstance(nodes, list):
        return False
    return any(
        _node_uses_service(node, service_key, version_refs, current_versions) for node in nodes
    )


def _node_uses_service(
    node: object,
    service_key: str,
    version_refs: set[tuple[str, int]],
    current_versions: dict[str, int],
) -> bool:
    if not isinstance(node, dict):
        return False
    config = node.get("config")
    if not isinstance(config, dict):
        return False
    service_override = config.get("service_override")
    if service_override is not None:
        return isinstance(service_override, str) and service_override == service_key
    definition_id = str(config.get("api_definition_id"))
    configured_version = config.get("api_version")
    version = (
        configured_version
        if isinstance(configured_version, int)
        else current_versions.get(definition_id)
    )
    return version is not None and (definition_id, version) in version_refs


class _ImpactNamed(Protocol):
    id: UUID
    name: str


def _impact_item(item: _ImpactNamed, reason: str) -> dict[str, object]:
    return {
        "id": item.id,
        "name": item.name,
        "reason": reason,
    }


def _validate_headers(headers: dict[str, str]) -> None:
    for name in headers:
        if not name.strip() or any(character in name for character in "\r\n:"):
            raise AppError(code="INVALID_HEADER_NAME", message="Header 名称不合法", status_code=422)
