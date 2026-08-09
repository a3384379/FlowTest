from dataclasses import dataclass
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.logging import redact
from app.domain.api_assets import BodyKind
from app.engine.contracts import NodeType, WorkflowDefinition, parse_api_node_config
from app.models.access import User
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.workflows import Workflow, WorkflowVersion
from app.repositories.api_assets import APIAssetRepository
from app.schemas.api_assets import MultipartBody
from app.services.api_assets import APIAssetService, PreparedRequest
from app.services.artifacts import ArtifactService
from app.services.executions import PreparedMultipart, PreparedUpload
from app.services.workflow_runtime import PreparedWorkflowRequest


@dataclass(frozen=True, slots=True)
class PreparedExecution:
    snapshot: dict[str, JsonValue]
    requests: dict[str, PreparedWorkflowRequest]


class WorkflowSnapshotBuilder:
    def __init__(self, session: AsyncSession) -> None:
        self._api_repository = APIAssetRepository(session)
        self._api_assets = APIAssetService(session)
        self._artifacts = ArtifactService(session)

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
    ) -> PreparedExecution:
        environment = await self._get_environment(project_id, environment_id)
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
        return PreparedExecution(
            snapshot=_snapshot(
                workflow=workflow,
                version=version,
                environment=environment,
                apis=api_snapshots,
                runtime_variables=runtime_variables,
                runtime_headers=runtime_headers,
            ),
            requests=requests,
        )

    async def _prepare_requests(
        self,
        *,
        actor: User,
        project_id: UUID,
        definition: APIDefinition,
        version: APIVersion,
        environment_id: UUID,
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
        "dataset": None,
        "runtime": cast(
            JsonValue,
            redact({"variables": runtime_variables, "headers": runtime_headers}),
        ),
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
