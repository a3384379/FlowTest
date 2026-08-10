import json
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.logging import redact
from app.domain.api_assets import BodyKind
from app.engine.contracts import (
    ForEachNodeConfig,
    NodeType,
    RedisNodeConfig,
    SqlNodeConfig,
    SubFlowNodeConfig,
    WorkflowDefinition,
    parse_api_node_config,
    parse_node_config,
)
from app.models.access import User
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.workflows import Workflow, WorkflowVersion
from app.repositories.api_assets import APIAssetRepository
from app.repositories.workflows import WorkflowRepository
from app.schemas.api_assets import MultipartBody
from app.services.api_assets import APIAssetService, PreparedRequest
from app.services.artifacts import ArtifactService
from app.services.credentials import CredentialMaterial, CredentialService
from app.services.data_nodes import PreparedDataNode
from app.services.datasets import WorkflowDatasetService
from app.services.executions import PreparedMultipart, PreparedUpload
from app.services.workflow_runtime import PreparedSubflow, PreparedWorkflowRequest


@dataclass(frozen=True, slots=True)
class PreparedExecution:
    snapshot: dict[str, JsonValue]
    requests: dict[str, PreparedWorkflowRequest]
    dataset_variables: dict[str, JsonValue]
    subflows: dict[str, PreparedSubflow] = dataclass_field(default_factory=dict)
    data_nodes: dict[str, PreparedDataNode] = dataclass_field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PreparedWorkflow:
    snapshot: dict[str, JsonValue]
    runs: tuple[PreparedExecution, ...]


class WorkflowSnapshotBuilder:
    def __init__(self, session: AsyncSession) -> None:
        self._workflows = WorkflowRepository(session)
        self._api_repository = APIAssetRepository(session)
        self._api_assets = APIAssetService(session)
        self._artifacts = ArtifactService(session)
        self._datasets = WorkflowDatasetService(session)
        self._credentials = CredentialService(session)

    async def prepare(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow: Workflow,
        version: WorkflowVersion,
        definition: WorkflowDefinition,
        environment_id: UUID,
        runtime_variables: dict[str, str],
        runtime_headers: dict[str, str],
    ) -> PreparedWorkflow:
        environment = await self._get_environment(project_id, environment_id)
        dataset = await self._datasets.prepare(project_id=project_id, definition=definition)
        rows: tuple[dict[str, JsonValue], ...] = (
            dataset.parsed.rows if dataset is not None else ({},)
        )
        runs: list[PreparedExecution] = []
        for row_index, row in enumerate(rows):
            requests, api_snapshots = await self._prepare_api_nodes(
                actor=actor,
                project_id=project_id,
                definition=definition,
                environment_id=environment_id,
                runtime_variables=runtime_variables,
                runtime_headers=runtime_headers,
                dataset_variables=row,
            )
            subflows = await self._prepare_subflows(
                actor=actor,
                project_id=project_id,
                definition=definition,
                environment_id=environment_id,
                runtime_variables=runtime_variables,
                runtime_headers=runtime_headers,
                dataset_variables=row,
                depth=1,
            )
            data_nodes = await self._prepare_data_nodes(
                project_id=project_id,
                definition=definition,
            )
            runs.append(
                PreparedExecution(
                    snapshot=_snapshot(
                        workflow=workflow,
                        version=version,
                        environment=environment,
                        apis=api_snapshots,
                        subflows=subflows,
                        data_nodes=data_nodes,
                        dataset=(
                            dataset.snapshot(
                                row_index=row_index,
                                row=cast(JsonValue, redact(row)),
                            )
                            if dataset is not None
                            else None
                        ),
                        runtime_variables=runtime_variables,
                        runtime_headers=runtime_headers,
                    ),
                    requests=requests,
                    subflows=subflows,
                    data_nodes=data_nodes,
                    dataset_variables=dict(row),
                )
            )
        parent_snapshot = runs[0].snapshot
        if dataset is not None:
            parent_snapshot = {
                **parent_snapshot,
                "dataset": dataset.snapshot(),
            }
        return PreparedWorkflow(snapshot=parent_snapshot, runs=tuple(runs))

    async def _prepare_subflows(
        self,
        *,
        actor: User,
        project_id: UUID,
        definition: WorkflowDefinition,
        environment_id: UUID,
        runtime_variables: dict[str, str],
        runtime_headers: dict[str, str],
        dataset_variables: dict[str, JsonValue],
        depth: int,
    ) -> dict[str, PreparedSubflow]:
        prepared: dict[str, PreparedSubflow] = {}
        for node in definition.nodes:
            config = parse_node_config(node)
            if not isinstance(config, (SubFlowNodeConfig, ForEachNodeConfig)):
                continue
            if depth >= 5:
                raise AppError(
                    code="SUBFLOW_DEPTH_EXCEEDED",
                    message="子流程最大嵌套深度为 5",
                    status_code=422,
                )
            workflow = await self._workflows.get(config.workflow_id)
            version = await self._workflows.find_version(
                config.workflow_id,
                config.workflow_version,
            )
            if workflow is None or workflow.project_id != project_id or version is None:
                raise AppError(
                    code="SUBFLOW_VERSION_NOT_FOUND",
                    message=f"节点 {node.name} 引用的子流程版本不存在",
                    status_code=422,
                )
            nested_definition = WorkflowDefinition.model_validate(version.definition)
            if any(item.type is NodeType.DATASET for item in nested_definition.nodes):
                raise AppError(
                    code="SUBFLOW_DATASET_NOT_SUPPORTED",
                    message="子流程暂不支持 Dataset 节点",
                    status_code=422,
                )
            requests, api_snapshots = await self._prepare_api_nodes(
                actor=actor,
                project_id=project_id,
                definition=nested_definition,
                environment_id=environment_id,
                runtime_variables=runtime_variables,
                runtime_headers=runtime_headers,
                dataset_variables=dataset_variables,
            )
            data_nodes = await self._prepare_data_nodes(
                project_id=project_id,
                definition=nested_definition,
            )
            children = await self._prepare_subflows(
                actor=actor,
                project_id=project_id,
                definition=nested_definition,
                environment_id=environment_id,
                runtime_variables=runtime_variables,
                runtime_headers=runtime_headers,
                dataset_variables=dataset_variables,
                depth=depth + 1,
            )
            snapshot = _nested_snapshot(
                workflow=workflow,
                version=version,
                apis=api_snapshots,
                subflows=children,
                data_nodes=data_nodes,
            )
            prepared[node.id] = PreparedSubflow(
                workflow_id=workflow.id,
                workflow_version=version.version,
                fingerprint=version.fingerprint,
                definition=nested_definition,
                requests=requests,
                subflows=children,
                snapshot=snapshot,
                data_nodes=data_nodes,
            )
        return prepared

    async def _prepare_data_nodes(
        self,
        *,
        project_id: UUID,
        definition: WorkflowDefinition,
    ) -> dict[str, PreparedDataNode]:
        prepared: dict[str, PreparedDataNode] = {}
        for node in definition.nodes:
            config = parse_node_config(node)
            if not isinstance(config, (SqlNodeConfig, RedisNodeConfig)):
                continue
            material = await self._credentials.load_material(
                project_id=project_id,
                credential_id=config.credential_id,
            )
            prepared[node.id] = PreparedDataNode(credential=material)
        return prepared

    async def _prepare_api_nodes(
        self,
        *,
        actor: User,
        project_id: UUID,
        definition: WorkflowDefinition,
        environment_id: UUID,
        runtime_variables: dict[str, str],
        runtime_headers: dict[str, str],
        dataset_variables: dict[str, JsonValue],
    ) -> tuple[dict[str, PreparedWorkflowRequest], dict[str, JsonValue]]:
        requests: dict[str, PreparedWorkflowRequest] = {}
        api_snapshots: dict[str, JsonValue] = {}
        for node in definition.nodes:
            if node.type is not NodeType.API:
                continue
            config = parse_api_node_config(node)
            api_definition, api_version = await self._api_assets.get_detail(
                actor=actor,
                project_id=project_id,
                definition_id=config.api_definition_id,
            )
            raw_request, redacted_request = await self._prepare_requests(
                actor=actor,
                project_id=project_id,
                definition=api_definition,
                version=api_version,
                environment_id=environment_id,
                workflow_variables=definition.variables,
                dataset_variables=_template_variables(dataset_variables),
                runtime_variables=runtime_variables,
                runtime_headers=runtime_headers,
            )
            body_kind = BodyKind(api_version.body_kind)
            multipart = (
                await self._prepare_multipart(project_id, raw_request)
                if body_kind is BodyKind.MULTIPART
                else None
            )
            requests[node.id] = PreparedWorkflowRequest(raw_request, body_kind, multipart)
            api_snapshots[node.id] = _api_snapshot(
                api_definition,
                api_version,
                redacted_request,
            )
        return requests, api_snapshots

    async def _prepare_requests(
        self,
        *,
        actor: User,
        project_id: UUID,
        definition: APIDefinition,
        version: APIVersion,
        environment_id: UUID,
        workflow_variables: dict[str, str],
        dataset_variables: dict[str, str],
        runtime_variables: dict[str, str],
        runtime_headers: dict[str, str],
    ) -> tuple[PreparedRequest, PreparedRequest]:
        raw = await self._api_assets.preview(
            actor=actor,
            project_id=project_id,
            definition_id=definition.id,
            environment_id=environment_id,
            runtime_variables=runtime_variables,
            runtime_headers=runtime_headers,
            body_override=None,
            use_body_override=False,
            version_number=version.version,
            workflow_variables=workflow_variables,
            dataset_variables=dataset_variables,
            redact=False,
        )
        redacted = await self._api_assets.preview(
            actor=actor,
            project_id=project_id,
            definition_id=definition.id,
            environment_id=environment_id,
            runtime_variables=runtime_variables,
            runtime_headers=runtime_headers,
            body_override=None,
            use_body_override=False,
            version_number=version.version,
            workflow_variables=workflow_variables,
            dataset_variables=dataset_variables,
            redact=True,
        )
        return raw, redacted

    async def _prepare_multipart(
        self, project_id: UUID, request: PreparedRequest
    ) -> PreparedMultipart:
        payload = MultipartBody.model_validate(request.body)
        files: list[PreparedUpload] = []
        for reference in payload.files:
            loaded = await self._artifacts.load(
                project_id=project_id,
                artifact_id=reference.artifact_id,
            )
            files.append(
                PreparedUpload(
                    field=reference.field,
                    filename=loaded.artifact.filename,
                    content_type=loaded.artifact.content_type,
                    content=loaded.content,
                )
            )
        return PreparedMultipart(fields=payload.fields, files=tuple(files))

    async def _get_environment(self, project_id: UUID, environment_id: UUID) -> Environment:
        environment = await self._api_repository.get_environment(environment_id)
        if environment is None or environment.project_id != project_id:
            raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)
        return environment


def _snapshot(
    *,
    workflow: Workflow,
    version: WorkflowVersion,
    environment: Environment,
    apis: dict[str, JsonValue],
    subflows: dict[str, PreparedSubflow],
    data_nodes: dict[str, PreparedDataNode],
    dataset: JsonValue,
    runtime_variables: dict[str, str],
    runtime_headers: dict[str, str],
) -> dict[str, JsonValue]:
    return {
        "schema_version": "1.0",
        "workflow": {
            "id": str(workflow.id),
            "version_id": str(version.id),
            "version": version.version,
            "fingerprint": version.fingerprint,
            "definition": version.definition,
        },
        "environment": _environment_snapshot(environment),
        "apis": apis,
        "subflows": {node_id: prepared.snapshot for node_id, prepared in subflows.items()},
        "data_nodes": _data_node_snapshots(data_nodes),
        "dataset": dataset,
        "runtime": cast(
            JsonValue,
            redact({"variables": runtime_variables, "headers": runtime_headers}),
        ),
    }


def _nested_snapshot(
    *,
    workflow: Workflow,
    version: WorkflowVersion,
    apis: dict[str, JsonValue],
    subflows: dict[str, PreparedSubflow],
    data_nodes: dict[str, PreparedDataNode],
) -> dict[str, JsonValue]:
    return {
        "workflow": {
            "id": str(workflow.id),
            "version_id": str(version.id),
            "version": version.version,
            "fingerprint": version.fingerprint,
            "definition": version.definition,
        },
        "apis": apis,
        "subflows": {node_id: prepared.snapshot for node_id, prepared in subflows.items()},
        "data_nodes": _data_node_snapshots(data_nodes),
    }


def _data_node_snapshots(data_nodes: dict[str, PreparedDataNode]) -> dict[str, JsonValue]:
    return {
        node_id: _credential_snapshot(prepared.credential)
        for node_id, prepared in data_nodes.items()
    }


def _credential_snapshot(credential: CredentialMaterial) -> JsonValue:
    return {
        "credential_id": str(credential.id),
        "name": credential.name,
        "kind": credential.kind.value,
        "host": credential.host,
        "port": credential.port,
        "database_name": credential.database_name,
        "username": credential.username,
        "tls_enabled": credential.tls_enabled,
    }


def _api_snapshot(
    definition: APIDefinition,
    version: APIVersion,
    request: PreparedRequest,
) -> JsonValue:
    return {
        "definition_id": str(definition.id),
        "definition_name": definition.name,
        "version_id": str(version.id),
        "version": version.version,
        "spec": cast(JsonValue, _redacted_api_spec(version)),
        "prepared_request": {
            "method": request.method.value,
            "url": request.url,
            "headers": {item.name: item.value for item in request.headers},
            "body": request.body,
        },
        "variables": {
            item.name: {"value": item.value, "source": item.source.value}
            for item in request.variables
        },
    }


def _template_variables(values: dict[str, JsonValue]) -> dict[str, str]:
    return {
        name: value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        for name, value in values.items()
    }


def _environment_snapshot(environment: Environment) -> JsonValue:
    return cast(
        JsonValue,
        redact(
            {
                "id": str(environment.id),
                "name": environment.name,
                "base_url": environment.base_url,
                "variables": environment.variables,
                "headers": environment.headers,
                "updated_at": environment.updated_at.isoformat(),
            }
        ),
    )


def _redacted_api_spec(version: APIVersion) -> dict[str, object]:
    auth_config = dict(version.auth_config)
    sensitive_auth_fields = {
        "bearer": {"token"},
        "basic": {"password"},
        "api_key": {"value"},
    }.get(version.auth_kind, set())
    for field in sensitive_auth_fields:
        if field in auth_config:
            auth_config[field] = "***"
    return cast(
        dict[str, object],
        redact(
            {
                "method": version.method,
                "path": version.path,
                "query_parameters": version.query_parameters,
                "headers": version.headers,
                "body_kind": version.body_kind,
                "body": version.body,
                "auth_kind": version.auth_kind,
                "auth_config": auth_config,
            }
        ),
    )
