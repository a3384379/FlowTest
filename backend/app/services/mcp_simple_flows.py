"""Deterministic quick-flow proposal service.

This adapter accepts a small intent contract and delegates persistence to the
existing FlowSpec change-set pipeline.  It never dispatches a workflow or
reads external evidence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter
from typing import Any, cast
from urllib.parse import quote
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.domain.flow_spec import (
    FlowSpec,
    FlowSpecEdge,
    FlowSpecNode,
    FlowSpecNodeTarget,
    FlowSpecOperation,
    FlowSpecParameter,
    FlowSpecParameterSource,
)
from app.domain.flow_spec import FlowSpecService as PortableFlowSpecService
from app.domain.proposal_provenance import QUICK_PROPOSAL_SCHEMA
from app.engine.contracts import (
    ApiNodeConfig,
    AssertNodeConfig,
    ExtractNodeConfig,
    FieldMapping,
    MappingSource,
    MappingTarget,
    MappingTargetLocation,
    MappingTransform,
    MappingTransformKind,
    Position,
    StartNodeConfig,
    WorkflowSettings,
)
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.repositories.api_assets import APIAssetRepository
from app.repositories.service_targets import ServiceTargetRepository
from app.schemas.mcp_simple_flows import (
    SimpleAssertion,
    SimpleBinding,
    SimpleFlowDiagnostic,
    SimpleFlowProposalResponse,
    SimpleFlowRequest,
    SimpleFlowStep,
    SimpleInputType,
)
from app.services.flow_spec import FlowSpecQuickProvenance, portable_contract_fingerprint
from app.services.flow_spec import FlowSpecService as ApplicationFlowSpecService
from app.services.idempotency import IdempotencyService, require_idempotency_key
from app.services.mcp_flow_proposals import require_mcp_flow_propose_scope
from app.services.projects import ProjectService

_PATH = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:(?:\.[A-Za-z_][A-Za-z0-9_]*)|(?:\[(?:0|[1-9][0-9]*)\]))*$"
)
_INPUT_REFERENCE = re.compile(r"^\{\{input\.([A-Za-z_][A-Za-z0-9_.-]*)\}\}$")
_RESPONSE_PATH_ROOTS = frozenset(
    {"body", "data", "error", "headers", "response", "status", "status_code", "value"}
)


@dataclass(frozen=True, slots=True)
class _ResolvedTarget:
    workflow_id: UUID | None
    expected_revision: int | None
    proposal_revision: int
    proposal_id: UUID | None


@dataclass(frozen=True, slots=True)
class _BuiltQuickFlow:
    spec: FlowSpec
    service_mappings: dict[str, UUID]
    operation_mappings: dict[str, UUID]
    operation_version_mappings: dict[str, int]
    missing_inputs: list[str]


class MCPSimpleFlowService:
    """Create one review-only quick FlowSpec proposal."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._assets = APIAssetRepository(session)
        self._targets = ServiceTargetRepository(session)
        self._flow_specs = ApplicationFlowSpecService(session)

    async def propose(
        self,
        *,
        actor: User,
        payload: SimpleFlowRequest,
        idempotency_key: str | None,
    ) -> SimpleFlowProposalResponse:
        service_account_id = require_mcp_flow_propose_scope()
        await self._projects.authorize(actor=actor, project_id=payload.project_id, editing=True)
        key = require_idempotency_key(idempotency_key)
        request_payload = payload.model_dump(mode="json")
        actor_key = f"service-account:{service_account_id}"
        idempotency = IdempotencyService(self._session)
        cached = await idempotency.completed_response(
            key=key,
            project_id=payload.project_id,
            actor_key=actor_key,
            operation="propose_simple_flow",
            request_payload=request_payload,
        )
        if cached is not None:
            cached["idempotency_replayed"] = True
            return SimpleFlowProposalResponse.model_validate(cached)
        response = await idempotency.run(
            key=key,
            project_id=payload.project_id,
            actor_key=actor_key,
            operation="propose_simple_flow",
            request_payload=request_payload,
            atomic_action=True,
            capture_server_timings=True,
            action=lambda: self._persist(
                actor=actor,
                payload=payload,
                service_account_id=service_account_id,
            ),
        )
        return SimpleFlowProposalResponse.model_validate(response)

    async def _persist(
        self,
        *,
        actor: User,
        payload: SimpleFlowRequest,
        service_account_id: UUID,
    ) -> SimpleFlowProposalResponse:
        resolve_started = perf_counter()
        await self._require_environment(payload.project_id, payload.environment_id)
        target = await self._resolve_target(payload)
        resolve_ms = _elapsed_ms(resolve_started)

        build_started = perf_counter()
        built = await self._build(payload)
        build_ms = _elapsed_ms(build_started)
        source_ref = payload.source_ref or _source_ref(payload)
        import_payload = _import_payload(
            built.spec,
            target,
            source_ref,
            service_mappings=built.service_mappings,
            operation_mappings=built.operation_mappings,
            operation_version_mappings=built.operation_version_mappings,
        )
        quick_provenance = FlowSpecQuickProvenance(
            task_ref=payload.task_ref,
            scenario_key=payload.scenario_key,
            source_ref=source_ref,
            service_account_id=service_account_id,
            environment_id=payload.environment_id,
            expected_target_revision=target.expected_revision,
            proposal_id=target.proposal_id,
            proposal_revision=target.proposal_revision,
        )

        validate_started = perf_counter()
        try:
            view = await self._flow_specs.create_import(
                actor=actor,
                project_id=payload.project_id,
                payload=import_payload,
                quick_provenance=quick_provenance,
                replace_change_set_id=target.proposal_id,
                commit=False,
            )
        except AppError as error:
            raise _with_quick_diagnostics(error) from error
        validate_and_stage_ms = _elapsed_ms(validate_started)
        if view.change_set.status != "draft" or view.item.review_status != "pending":
            raise AppError(
                code="QUICK_PROPOSAL_NOT_DRAFT",
                message="Quick 提案未创建为待审核草稿",
                status_code=500,
            )
        proposal_id = view.change_set.id
        return SimpleFlowProposalResponse(
            project_id=payload.project_id,
            environment_id=payload.environment_id,
            proposal_id=proposal_id,
            proposal_revision=target.proposal_revision,
            status="incomplete" if built.missing_inputs else "draft_created",
            static_validation="passed",
            readiness="needs_input" if built.missing_inputs else "ready",
            missing_inputs=built.missing_inputs,
            review_url=_ui_link(f"/projects/{payload.project_id}/workflows?proposal={proposal_id}"),
            diagnostics=[],
            timings_ms={
                "resolve": resolve_ms,
                "build": build_ms,
                "validate_and_stage": validate_and_stage_ms,
            },
            flow_spec_fingerprint=view.pipeline.fingerprint,
            target_workflow_id=view.item.target_resource_id,
            target_revision=_target_revision(view.change_set.source_snapshot),
            source_ref=source_ref,
        )

    async def _require_environment(self, project_id: UUID, environment_id: UUID) -> Environment:
        environment = await self._assets.get_environment(environment_id)
        if (
            environment is None
            or environment.project_id != project_id
            or environment.archived_at is not None
        ):
            raise _quick_error(
                code="QUICK_ENVIRONMENT_NOT_FOUND",
                message="Quick 提案环境不存在、已归档或不属于当前项目",
                field_path="environment_id",
            )
        return environment

    async def _resolve_target(self, payload: SimpleFlowRequest) -> _ResolvedTarget:
        if payload.proposal_id is None:
            return _ResolvedTarget(
                workflow_id=payload.workflow_id,
                expected_revision=payload.expected_revision,
                proposal_revision=1,
                proposal_id=None,
            )
        change_set = await self._session.get(AIChangeSet, payload.proposal_id)
        if (
            change_set is None
            or change_set.project_id != payload.project_id
            or change_set.source_type != "flow_spec"
            or change_set.source_snapshot.get("proposal_schema_version") != QUICK_PROPOSAL_SCHEMA
        ):
            raise _quick_error(
                code="QUICK_PROPOSAL_NOT_FOUND",
                message="可修订的 Quick 提案不存在",
                field_path="proposal_id",
            )
        snapshot = change_set.source_snapshot
        item = (
            await self._session.scalars(
                select(AIChangeItem)
                .where(AIChangeItem.change_set_id == change_set.id)
                .order_by(AIChangeItem.position)
            )
        ).first()
        snapshot_workflow_id = _uuid(snapshot.get("target_workflow_id"))
        if item is not None and item.target_resource_id != snapshot_workflow_id:
            raise _quick_error(
                code="QUICK_PROPOSAL_SNAPSHOT_INVALID",
                message="Quick 提案目标快照无效",
                field_path="proposal_id",
            )
        if payload.workflow_id is not None and payload.workflow_id != snapshot_workflow_id:
            raise _quick_error(
                code="QUICK_PROPOSAL_TARGET_MISMATCH",
                message="修订提案的 Workflow 目标不一致",
                field_path="workflow_id",
            )
        previous = snapshot.get("quick")
        previous_revision = (
            _int_or_none(previous.get("proposal_revision")) if isinstance(previous, dict) else None
        ) or 1
        if payload.expected_revision != previous_revision:
            raise _quick_error(
                code="QUICK_PROPOSAL_REVISION_CONFLICT",
                message="Quick 提案版本已变化, 请读取最新提案后重试",
                field_path="expected_revision",
                expected=str(previous_revision),
                actual=str(payload.expected_revision),
                status_code=409,
            )
        expected = _int_or_none(snapshot.get("target_revision"))
        return _ResolvedTarget(
            workflow_id=payload.workflow_id or snapshot_workflow_id,
            expected_revision=expected,
            proposal_revision=previous_revision + 1,
            proposal_id=payload.proposal_id,
        )

    async def _build(self, payload: SimpleFlowRequest) -> _BuiltQuickFlow:
        input_values, parameters, missing_inputs = _input_state(payload)
        services: dict[str, PortableFlowSpecService] = {}
        operations: dict[str, FlowSpecOperation] = {}
        service_mappings: dict[str, UUID] = {}
        operation_mappings: dict[str, UUID] = {}
        operation_version_mappings: dict[str, int] = {}
        nodes: list[FlowSpecNode] = [
            FlowSpecNode(
                id="start",
                kind="start",
                name="开始",
                position=Position(x=0, y=0),
                config=cast(dict[str, JsonValue], StartNodeConfig().model_dump(mode="json")),
            )
        ]
        edges: list[FlowSpecEdge] = []
        previous_node = "start"
        prior_steps: dict[str, SimpleFlowStep] = {}
        prior_sources: dict[str, str] = {}
        for index, step in enumerate(payload.steps, start=1):
            definition, version, service = await self._resolve_api(
                payload.project_id, step, services, service_mappings
            )
            operation_ref = f"quick:api:{definition.id}:v{version.version}"
            operations[operation_ref] = _operation(definition, version, service, operation_ref)
            operation_mappings[operation_ref] = definition.id
            operation_version_mappings[operation_ref] = version.version
            api_id = step.key
            nodes.append(
                FlowSpecNode(
                    id=api_id,
                    kind="api",
                    name=step.name,
                    position=Position(x=float(index * 260), y=0),
                    config=cast(
                        dict[str, JsonValue],
                        _api_node_config(step, definition.id, version).model_dump(mode="json"),
                    ),
                    operation_ref=operation_ref,
                    target=(
                        FlowSpecNodeTarget(service_ref=service.service_key)
                        if service is not None
                        else None
                    ),
                )
            )
            mappings = _bindings(
                step,
                prior_steps=prior_steps,
                prior_sources=prior_sources,
                input_types={item.name: item.type for item in payload.inputs},
                constant_values=input_values,
            )
            mapping_groups: dict[str, list[FieldMapping]] = {}
            for mapping in mappings:
                mapping_groups.setdefault(mapping.source.node_id, []).append(mapping)
            chain_mappings = mapping_groups.pop(previous_node, [])
            edges.append(
                FlowSpecEdge(
                    id=_edge_id(previous_node, api_id),
                    source=previous_node,
                    target=api_id,
                    mappings=chain_mappings,
                )
            )
            for source_node, source_mappings in mapping_groups.items():
                edges.append(
                    FlowSpecEdge(
                        id=_edge_id(source_node, api_id, "mapping"),
                        source=source_node,
                        target=api_id,
                        mappings=source_mappings,
                    )
                )
            previous_node = api_id
            for output_index, output in enumerate(step.outputs, start=1):
                output_id = _node_id(api_id, "output", output.name)
                expression = _path_expression(output.source, api_id, "outputs")
                nodes.append(
                    FlowSpecNode(
                        id=output_id,
                        kind="extract",
                        name=f"{step.name} · {output.name}",
                        position=Position(x=float(index * 260 + output_index * 20), y=120),
                        config=cast(
                            dict[str, JsonValue],
                            ExtractNodeConfig(
                                source_node_id=api_id,
                                expression=expression,
                                variable=output.name,
                            ).model_dump(mode="json"),
                        ),
                    )
                )
                edges.append(
                    FlowSpecEdge(
                        id=_edge_id(previous_node, output_id),
                        source=previous_node,
                        target=output_id,
                    )
                )
                previous_node = output_id
            for assertion_index, assertion in enumerate(step.assertions, start=1):
                assertion_id = _node_id(api_id, "assert", str(assertion_index))
                source_node, expression = _assertion_path(assertion.target, api_id)
                expected_source, expected_expression, expected = _assertion_expected(
                    assertion, set(input_values)
                )
                config = AssertNodeConfig(
                    source_node_id=source_node,
                    expression=expression,
                    operator=(
                        "equals" if assertion.operator == "status_code" else assertion.operator
                    ),
                    expected=expected,
                    expected_source_node_id=expected_source,
                    expected_expression=expected_expression,
                )
                nodes.append(
                    FlowSpecNode(
                        id=assertion_id,
                        kind="assert",
                        name=f"{step.name} · 断言 {assertion_index}",
                        position=Position(x=float(index * 260), y=220 + assertion_index * 80),
                        config=cast(dict[str, JsonValue], config.model_dump(mode="json")),
                    )
                )
                edges.append(
                    FlowSpecEdge(
                        id=_edge_id(previous_node, assertion_id),
                        source=previous_node,
                        target=assertion_id,
                    )
                )
                previous_node = assertion_id
            forward_id = _forward_node_id(step.key)
            nodes.append(
                FlowSpecNode(
                    id=forward_id,
                    kind="extract",
                    name=f"{step.name} · 输出",
                    position=Position(x=float(index * 260 + 140), y=360),
                    config=cast(
                        dict[str, JsonValue],
                        ExtractNodeConfig(
                            source_node_id=api_id,
                            expression="@",
                            variable=_forward_variable_name(step.key),
                        ).model_dump(mode="json"),
                    ),
                )
            )
            edges.append(
                FlowSpecEdge(
                    id=_edge_id(previous_node, forward_id),
                    source=previous_node,
                    target=forward_id,
                )
            )
            previous_node = forward_id
            prior_sources[step.key] = forward_id
            prior_steps[step.key] = step
        end_id = "end"
        nodes.append(
            FlowSpecNode(
                id=end_id,
                kind="end",
                name="结束",
                position=Position(x=float((len(payload.steps) + 1) * 260), y=0),
            )
        )
        edges.append(
            FlowSpecEdge(id=_edge_id(previous_node, end_id), source=previous_node, target=end_id)
        )
        return _BuiltQuickFlow(
            spec=FlowSpec(
                fingerprint_version="flowtest-flow-spec-fingerprint-v3",
                project_id=payload.project_id,
                name=payload.name,
                description=f"Quick · {payload.scenario_key}",
                source_evidence=[],
                services=list(services.values()),
                operations=list(operations.values()),
                nodes=nodes,
                edges=edges,
                variables=input_values,
                parameters=parameters,
                assertions=[],
                settings=WorkflowSettings(),
            ),
            service_mappings=service_mappings,
            operation_mappings=operation_mappings,
            operation_version_mappings=operation_version_mappings,
            missing_inputs=missing_inputs,
        )

    async def _resolve_api(
        self,
        project_id: UUID,
        step: SimpleFlowStep,
        services: dict[str, PortableFlowSpecService],
        service_mappings: dict[str, UUID],
    ) -> tuple[APIDefinition, APIVersion, Any]:
        definition = await self._assets.get_definition(step.api.api_definition_id)
        if definition is None or definition.project_id != project_id or not definition.is_active:
            raise _quick_error(
                code="QUICK_API_NOT_FOUND",
                message="Quick 步骤引用的 API 不存在、已停用或不属于当前项目",
                field_path=f"steps.{step.key}.api.api_definition_id",
                node_key=step.key,
            )
        version = await self._assets.get_version(
            definition_id=definition.id, version=step.api.version
        )
        if version is None:
            raise _quick_error(
                code="QUICK_API_VERSION_NOT_FOUND",
                message="Quick 步骤引用的 API 版本不存在",
                field_path=f"steps.{step.key}.api.version",
                node_key=step.key,
            )
        service_id = version.service_id or definition.service_id
        service = None
        if service_id is not None:
            service = await self._targets.get_service(service_id)
            if service is None or service.project_id != project_id:
                raise _quick_error(
                    code="QUICK_SERVICE_NOT_FOUND",
                    message="Quick API 绑定的 Service 不属于当前项目",
                    field_path=f"steps.{step.key}.api",
                    node_key=step.key,
                )
            services.setdefault(
                service.service_key,
                PortableFlowSpecService(
                    ref=service.service_key,
                    name=service.name,
                    service_type=service.service_type,
                ),
            )
            service_mappings[service.service_key] = service.id
        return definition, version, service


def _input_state(
    payload: SimpleFlowRequest,
) -> tuple[dict[str, str], list[FlowSpecParameter], list[str]]:
    values: dict[str, str] = {}
    parameters: list[FlowSpecParameter] = []
    missing: list[str] = []
    for item in payload.inputs:
        has_default = "default" in item.model_fields_set
        value = _json_value(item.default) if has_default else None
        if value is not None:
            values[item.name] = value
        parameters.append(
            FlowSpecParameter(
                name=item.name,
                source=FlowSpecParameterSource.RUNTIME,
                value=value,
                value_type=item.type,
                required=item.required,
                nullable=item.nullable,
                description=item.description,
            )
        )
        if item.required and not has_default:
            missing.append(item.name)
    return values, parameters, missing


def _bindings(
    step: SimpleFlowStep,
    *,
    prior_steps: dict[str, SimpleFlowStep],
    prior_sources: dict[str, str],
    input_types: dict[str, SimpleInputType],
    constant_values: dict[str, str],
) -> list[FieldMapping]:
    mappings: list[FieldMapping] = []
    for _index, binding in enumerate(step.bindings, start=1):
        location, key = _target(binding.target, step.key)
        source_node, source_path = _source(
            binding,
            prior_steps=prior_steps,
            prior_sources=prior_sources,
            input_names=set(input_types),
            constant_values=constant_values,
        )
        parse_json = location in {
            MappingTargetLocation.BODY,
            MappingTargetLocation.VARIABLE,
        } and (
            (binding.source.kind == "constant" and not isinstance(binding.source.value, str))
            or (
                binding.source.kind == "input"
                and binding.source.name is not None
                and input_types[binding.source.name] != "string"
            )
        )
        mappings.append(
            FieldMapping(
                source=MappingSource(node_id=source_node, path=source_path),
                transform=MappingTransform(
                    kind=(
                        MappingTransformKind.JSON_PARSE
                        if parse_json
                        else MappingTransformKind.IDENTITY
                    )
                ),
                target=MappingTarget(node_id=step.key, location=location, key=key),
            )
        )
    return mappings


def _source(
    binding: SimpleBinding,
    *,
    prior_steps: dict[str, SimpleFlowStep],
    prior_sources: dict[str, str],
    input_names: set[str],
    constant_values: dict[str, str],
) -> tuple[str, str]:
    source = binding.source
    if source.kind == "input":
        if source.name not in input_names:
            raise _quick_error(
                code="QUICK_INPUT_NOT_DECLARED",
                message="绑定引用了未声明的输入变量",
                field_path="bindings.source.name",
            )
        return "start", f"variables.{source.name}"
    if source.kind == "constant":
        value = _json_value(source.value)
        digest = sha256(value.encode()).hexdigest()[:16]
        name = f"__quick_constant_{digest}"
        constant_values[name] = value
        return "start", f"variables.{name}"
    if source.name is None:
        raise _quick_error(
            code="QUICK_PREVIOUS_OUTPUT_INVALID",
            message="previous_output 必须包含来源路径",
            field_path="bindings.source.name",
        )
    step_key, path = _split_step_path(source.name, prior_steps)
    if step_key not in prior_steps or not path:
        raise _quick_error(
            code="QUICK_PREVIOUS_OUTPUT_INVALID",
            message="previous_output 必须引用之前步骤的输出路径",
            field_path="bindings.source.name",
        )
    source_node = prior_sources.get(step_key)
    if source_node is None:
        raise _quick_error(
            code="QUICK_PREVIOUS_OUTPUT_INVALID",
            message="previous_output 的步骤来源尚未完成生成",
            field_path="bindings.source.name",
        )
    return source_node, f"value.{path}"


def _target(value: str, step_key: str) -> tuple[MappingTargetLocation, str]:
    location_name, key = value.split(".", 1)
    try:
        location = MappingTargetLocation(location_name)
    except ValueError as error:
        raise _quick_error(
            code="QUICK_BINDING_TARGET_INVALID",
            message="绑定目标位置无效",
            field_path=f"steps.{step_key}.bindings.target",
            node_key=step_key,
        ) from error
    return location, key


def _split_step_path(value: str, prior_steps: dict[str, SimpleFlowStep]) -> tuple[str, str]:
    for key in sorted(prior_steps, key=len, reverse=True):
        prefix = f"{key}."
        if value.startswith(prefix):
            path = value[len(prefix) :]
            if _PATH.fullmatch(path):
                return key, path
    return "", ""


def _assertion_path(value: str, current_step: str) -> tuple[str, str]:
    if value == "status_code":
        return current_step, "status_code"
    if value.startswith("input.") and _PATH.fullmatch(value[6:]):
        return "start", f"variables.{value[6:]}"
    if value.startswith(f"{current_step}."):
        value = value[len(current_step) + 1 :]
    elif "." in value and value.split(".", 1)[0] not in _RESPONSE_PATH_ROOTS:
        raise _quick_error(
            code="QUICK_ASSERTION_PATH_INVALID",
            message="断言只能引用当前步骤响应或流程输入",
            field_path=f"steps.{current_step}.assertions.target",
            node_key=current_step,
            expected="当前步骤响应路径或 input.*",
            actual=value,
        )
    if not _PATH.fullmatch(value):
        raise _quick_error(
            code="QUICK_ASSERTION_PATH_INVALID",
            message="断言目标必须是安全的响应路径",
            field_path=f"steps.{current_step}.assertions.target",
            node_key=current_step,
        )
    return current_step, value


def _assertion_expected(
    assertion: SimpleAssertion, input_names: set[str]
) -> tuple[str | None, str | None, JsonValue]:
    if isinstance(assertion.expected, str):
        match = _INPUT_REFERENCE.fullmatch(assertion.expected)
        if match is not None:
            name = match.group(1)
            if name not in input_names:
                raise _quick_error(
                    code="QUICK_INPUT_NOT_DECLARED",
                    message="断言引用了未声明的输入变量",
                    field_path="assertions.expected",
                )
            return "start", f"variables.{name}", None
    return None, None, assertion.expected


def _path_expression(value: str, step_key: str, kind: str) -> str:
    expression = value
    if expression.startswith(f"{step_key}."):
        expression = expression[len(step_key) + 1 :]
    elif "." in expression and expression.split(".", 1)[0] not in _RESPONSE_PATH_ROOTS:
        raise _quick_error(
            code="QUICK_OUTPUT_PATH_INVALID",
            message=f"{kind} 只能引用当前步骤响应路径",
            field_path=f"steps.{step_key}.outputs.source",
            node_key=step_key,
            expected="当前步骤响应路径",
            actual=value,
        )
    if not _PATH.fullmatch(expression):
        raise _quick_error(
            code="QUICK_OUTPUT_PATH_INVALID",
            message=f"{kind} 路径必须是安全的响应路径",
            field_path=f"steps.{step_key}.outputs.source",
            node_key=step_key,
        )
    return expression


def _forward_node_id(step_key: str) -> str:
    return _node_id(step_key, "output", "forward")


def _node_id(*parts: str) -> str:
    return _bounded_id(".".join(parts))


def _edge_id(*parts: str) -> str:
    return _bounded_id(f"edge-{'-'.join(parts)}")


def _bounded_id(value: str) -> str:
    if len(value) <= 128:
        return value
    digest = sha256(value.encode()).hexdigest()[:16]
    return f"{value[:111]}.{digest}"


def _forward_variable_name(step_key: str) -> str:
    digest = sha256(step_key.encode()).hexdigest()[:16]
    return f"__quick_output_{digest}"


def _operation(
    definition: APIDefinition,
    version: APIVersion,
    service: Any,
    operation_ref: str,
) -> FlowSpecOperation:
    service_ref = service.service_key if service is not None else None
    fingerprint = portable_contract_fingerprint(
        version,
        service_ref=service.service_key if service is not None else None,
    )
    return FlowSpecOperation(
        ref=operation_ref,
        service_ref=service_ref,
        name=definition.name,
        method=version.method,
        path=version.path,
        version_strategy="pinned",
        source_version=version.version,
        contract_fingerprint=fingerprint,
    )


def _api_node_config(
    step: SimpleFlowStep, api_definition_id: UUID, version: APIVersion
) -> ApiNodeConfig:
    polling = step.polling
    if polling is None:
        return ApiNodeConfig(api_definition_id=api_definition_id, api_version=version.version)
    if polling.max_attempts > 1 and version.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        raise _quick_error(
            code="QUICK_POLLING_SIDE_EFFECT",
            message="Quick 轮询只允许 GET、HEAD 或 OPTIONS 等只读请求",
            field_path=f"steps.{step.key}.polling.max_attempts",
            node_key=step.key,
            expected="只读 HTTP 方法",
            actual=version.method.upper(),
            repair_hint="提交类接口不要自动重试,先查询受理状态",
        )
    return ApiNodeConfig(
        api_definition_id=api_definition_id,
        api_version=version.version,
        timeout_seconds=polling.timeout_seconds,
        polling={
            "expression": _path_expression(polling.target, step.key, "polling"),
            "operator": polling.operator,
            "expected": polling.expected,
            "terminal_failure_values": polling.terminal_failure_values,
            "max_attempts": polling.max_attempts,
            "interval_seconds": polling.interval_seconds,
            "timeout_seconds": polling.timeout_seconds,
        },
    )


def _import_payload(
    spec: FlowSpec,
    target: _ResolvedTarget,
    source_ref: str,
    *,
    service_mappings: dict[str, UUID],
    operation_mappings: dict[str, UUID],
    operation_version_mappings: dict[str, int],
) -> Any:
    from app.schemas.flow_spec import FlowSpecImportRequest

    return FlowSpecImportRequest(
        spec=spec,
        workflow_id=target.workflow_id,
        source_ref=source_ref,
        service_mappings=service_mappings,
        operation_mappings=operation_mappings,
        operation_version_mappings=operation_version_mappings,
    )


def _source_ref(payload: SimpleFlowRequest) -> str:
    task = quote(payload.task_ref, safe="-._~")
    scenario = quote(payload.scenario_key, safe="-._~")
    return f"mcp://quick/{payload.project_id}/{scenario}/{task}"[:512]


def _json_value(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _quick_error(
    *,
    code: str,
    message: str,
    field_path: str,
    node_key: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
    repair_hint: str = "修正该字段后重新提交 Quick 提案",
    status_code: int = 422,
) -> AppError:
    diagnostic = SimpleFlowDiagnostic(
        code=code,
        node_key=node_key,
        field_path=field_path,
        expected=expected,
        actual=actual,
        repair_hint=repair_hint,
    )
    return AppError(
        code=code,
        message=message,
        status_code=status_code,
        details={"diagnostics": [diagnostic.model_dump(mode="json")]},
    )


def _with_quick_diagnostics(error: AppError) -> AppError:
    if isinstance(error.details, dict) and "diagnostics" in error.details:
        return error
    details = dict(error.details) if isinstance(error.details, dict) else {}
    details["diagnostics"] = [
        SimpleFlowDiagnostic(
            code=error.code,
            field_path="steps",
            repair_hint="根据静态校验详情修正后重新提交",
        ).model_dump(mode="json")
    ]
    return AppError(
        code=error.code,
        message=error.message,
        status_code=error.status_code,
        details=details,
    )


def _target_revision(snapshot: dict[str, object]) -> int | None:
    return _int_or_none(snapshot.get("target_revision"))


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _ui_link(path: str) -> str:
    origin = next((item.strip().rstrip("/") for item in settings.cors_origins if item.strip()), "")
    return f"{origin}{path}" if origin else path
