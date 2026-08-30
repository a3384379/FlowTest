import base64
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from app.domain.api_assets import BodyKind, HttpMethod
from app.domain.data_nodes import CredentialKind
from app.domain.event_protocols import EventSourceKind
from app.domain.protocols import ProtocolKind
from app.domain.scopes import HeaderScope, VariableScope
from app.engine.contracts import WorkflowDefinition
from app.engine.event_nodes import PreparedEventNode
from app.engine.protocol_nodes import PreparedProtocolNode, ProtocolCredentialMaterial
from app.services.api_assets import PreparedHeader, PreparedRequest, PreparedVariable
from app.services.credentials import CredentialMaterial
from app.services.data_nodes import PreparedDataNode
from app.services.executions import PreparedMultipart, PreparedUpload
from app.services.workflow_runtime import PreparedSubflow, PreparedWorkflowRequest
from app.services.workflow_snapshots import PreparedExecution
from app.services.workflows import WorkflowBatchPlan, WorkflowExecutionPlan, WorkflowRunPlan


class StoredHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    value: str
    source: HeaderScope


class StoredVariable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    value: str
    source: VariableScope
    secret: bool


class StoredUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    filename: str
    content_type: str
    content_base64: str


class StoredMultipart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: dict[str, str]
    files: list[StoredUpload]


class StoredRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: HttpMethod
    url: str
    headers: list[StoredHeader]
    body: JsonValue
    variables: list[StoredVariable]
    body_kind: BodyKind
    multipart: StoredMultipart | None
    redacted_url: str | None = None
    redacted_headers: list[StoredHeader] | None = None
    redacted_body: JsonValue = None
    target_snapshot: dict[str, JsonValue] = Field(default_factory=dict)


class StoredCredentialMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    project_id: UUID
    name: str
    kind: CredentialKind
    host: str
    port: int
    database_name: str
    username: str
    secret: str
    tls_enabled: bool


class StoredProtocolCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    project_id: UUID
    name: str
    kind: CredentialKind
    host: str
    port: int
    secret: str


class StoredProtocolNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: ProtocolKind
    schema_id: UUID
    schema_version: int
    schema_hash: str
    canonical_content_base64: str
    credential: StoredProtocolCredential | None = None


class StoredEventNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: UUID
    source_kind: EventSourceKind
    endpoints: list[str]
    schema_registry_url: str | None
    source_version: int
    source_hash: str
    schema_id: UUID | None = None
    schema_version: int | None = None
    schema_hash: str | None = None
    schema_content_base64: str | None = None
    schema_summary: dict[str, JsonValue] | None = None


class StoredPreparedExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: dict[str, JsonValue]
    requests: dict[str, StoredRequest]
    dataset_variables: dict[str, JsonValue]
    subflows: dict[str, "StoredPreparedSubflow"] = Field(default_factory=dict)
    data_nodes: dict[str, StoredCredentialMaterial] = Field(default_factory=dict)
    protocol_nodes: dict[str, StoredProtocolNode] = Field(default_factory=dict)
    event_nodes: dict[str, StoredEventNode] = Field(default_factory=dict)


class StoredPreparedSubflow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: UUID
    workflow_version: int
    fingerprint: str
    definition: WorkflowDefinition
    requests: dict[str, StoredRequest]
    subflows: dict[str, "StoredPreparedSubflow"]
    snapshot: dict[str, JsonValue]
    data_nodes: dict[str, StoredCredentialMaterial] = Field(default_factory=dict)
    protocol_nodes: dict[str, StoredProtocolNode] = Field(default_factory=dict)
    event_nodes: dict[str, StoredEventNode] = Field(default_factory=dict)


class StoredRunPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["run"] = "run"
    execution_id: UUID
    actor_id: UUID
    project_id: UUID
    workflow_version: int
    definition: WorkflowDefinition
    prepared: StoredPreparedExecution
    runtime_variables: dict[str, str]
    request_budget: int | None = Field(default=None, ge=1, le=10_000)


class StoredBatchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["batch"] = "batch"
    execution_id: UUID
    actor_id: UUID
    project_id: UUID
    workflow_version: int
    children: list[StoredRunPlan]
    concurrency: int


StoredPlan = Annotated[StoredRunPlan | StoredBatchPlan, Field(discriminator="kind")]
_PLAN_ADAPTER: TypeAdapter[StoredPlan] = TypeAdapter(StoredPlan)


def encode_execution_plan(plan: WorkflowExecutionPlan) -> str:
    stored = _store_batch(plan) if isinstance(plan, WorkflowBatchPlan) else _store_run(plan)
    return stored.model_dump_json()


def decode_execution_plan(payload: str) -> WorkflowExecutionPlan:
    stored = _PLAN_ADAPTER.validate_json(payload)
    if isinstance(stored, StoredBatchPlan):
        return WorkflowBatchPlan(
            execution_id=stored.execution_id,
            actor_id=stored.actor_id,
            project_id=stored.project_id,
            workflow_version=stored.workflow_version,
            children=tuple(_load_run(child) for child in stored.children),
            concurrency=stored.concurrency,
        )
    return _load_run(stored)


def _store_batch(plan: WorkflowBatchPlan) -> StoredBatchPlan:
    return StoredBatchPlan(
        execution_id=plan.execution_id,
        actor_id=plan.actor_id,
        project_id=plan.project_id,
        workflow_version=plan.workflow_version,
        children=[_store_run(child) for child in plan.children],
        concurrency=plan.concurrency,
    )


def _store_run(plan: WorkflowRunPlan) -> StoredRunPlan:
    return StoredRunPlan(
        execution_id=plan.execution_id,
        actor_id=plan.actor_id,
        project_id=plan.project_id,
        workflow_version=plan.workflow_version,
        definition=plan.definition,
        prepared=StoredPreparedExecution(
            snapshot=plan.prepared.snapshot,
            requests={
                name: _store_request(value) for name, value in plan.prepared.requests.items()
            },
            subflows={
                node_id: _store_subflow(value) for node_id, value in plan.prepared.subflows.items()
            },
            data_nodes={
                node_id: _store_credential(value.credential)
                for node_id, value in plan.prepared.data_nodes.items()
            },
            protocol_nodes={
                node_id: _store_protocol_node(value)
                for node_id, value in plan.prepared.protocol_nodes.items()
            },
            event_nodes={
                node_id: _store_event_node(value)
                for node_id, value in plan.prepared.event_nodes.items()
            },
            dataset_variables=plan.prepared.dataset_variables,
        ),
        runtime_variables=plan.runtime_variables,
        request_budget=plan.request_budget,
    )


def _store_request(prepared: PreparedWorkflowRequest) -> StoredRequest:
    request = prepared.request
    return StoredRequest(
        method=request.method,
        url=request.url,
        headers=[
            StoredHeader(name=item.name, value=item.value, source=item.source)
            for item in request.headers
        ],
        body=request.body,
        variables=[
            StoredVariable(name=item.name, value=item.value, source=item.source, secret=item.secret)
            for item in request.variables
        ],
        body_kind=prepared.body_kind,
        multipart=_store_multipart(prepared.multipart),
        redacted_url=prepared.redacted_request.url,
        redacted_headers=[
            StoredHeader(name=item.name, value=item.value, source=item.source)
            for item in prepared.redacted_request.headers
        ],
        redacted_body=prepared.redacted_request.body,
        target_snapshot=request.target_snapshot,
    )


def _store_subflow(prepared: PreparedSubflow) -> StoredPreparedSubflow:
    return StoredPreparedSubflow(
        workflow_id=prepared.workflow_id,
        workflow_version=prepared.workflow_version,
        fingerprint=prepared.fingerprint,
        definition=prepared.definition,
        requests={name: _store_request(value) for name, value in prepared.requests.items()},
        subflows={node_id: _store_subflow(value) for node_id, value in prepared.subflows.items()},
        snapshot=prepared.snapshot,
        data_nodes={
            node_id: _store_credential(value.credential)
            for node_id, value in prepared.data_nodes.items()
        },
        protocol_nodes={
            node_id: _store_protocol_node(value)
            for node_id, value in prepared.protocol_nodes.items()
        },
        event_nodes={
            node_id: _store_event_node(value) for node_id, value in prepared.event_nodes.items()
        },
    )


def _store_credential(value: CredentialMaterial) -> StoredCredentialMaterial:
    return StoredCredentialMaterial.model_validate(value, from_attributes=True)


def _store_multipart(value: PreparedMultipart | None) -> StoredMultipart | None:
    if value is None:
        return None
    return StoredMultipart(
        fields=value.fields,
        files=[
            StoredUpload(
                field=item.field,
                filename=item.filename,
                content_type=item.content_type,
                content_base64=base64.b64encode(item.content).decode(),
            )
            for item in value.files
        ],
    )


def _load_run(stored: StoredRunPlan) -> WorkflowRunPlan:
    return WorkflowRunPlan(
        execution_id=stored.execution_id,
        actor_id=stored.actor_id,
        project_id=stored.project_id,
        workflow_version=stored.workflow_version,
        definition=stored.definition,
        prepared=PreparedExecution(
            snapshot=stored.prepared.snapshot,
            requests={
                name: _load_request(value) for name, value in stored.prepared.requests.items()
            },
            subflows={
                node_id: _load_subflow(value) for node_id, value in stored.prepared.subflows.items()
            },
            dataset_variables=stored.prepared.dataset_variables,
            data_nodes={
                node_id: PreparedDataNode(credential=_load_credential(value))
                for node_id, value in stored.prepared.data_nodes.items()
            },
            protocol_nodes={
                node_id: _load_protocol_node(value)
                for node_id, value in stored.prepared.protocol_nodes.items()
            },
            event_nodes={
                node_id: _load_event_node(value)
                for node_id, value in stored.prepared.event_nodes.items()
            },
        ),
        runtime_variables=stored.runtime_variables,
        request_budget=stored.request_budget,
    )


def _load_request(stored: StoredRequest) -> PreparedWorkflowRequest:
    request = PreparedRequest(
        method=stored.method,
        url=stored.url,
        headers=tuple(
            PreparedHeader(name=item.name, value=item.value, source=item.source)
            for item in stored.headers
        ),
        body=stored.body,
        variables=tuple(
            PreparedVariable(
                name=item.name,
                value=item.value,
                source=item.source,
                secret=item.secret,
            )
            for item in stored.variables
        ),
        target_snapshot=stored.target_snapshot,
    )
    safe_headers = stored.redacted_headers or stored.headers
    return PreparedWorkflowRequest(
        request=request,
        redacted_request=PreparedRequest(
            method=stored.method,
            url=stored.redacted_url or stored.url,
            headers=tuple(
                PreparedHeader(name=item.name, value=item.value, source=item.source)
                for item in safe_headers
            ),
            body=stored.redacted_body if stored.redacted_url is not None else stored.body,
            variables=request.variables,
            target_snapshot=stored.target_snapshot,
        ),
        body_kind=stored.body_kind,
        multipart=_load_multipart(stored.multipart),
    )


def _load_subflow(stored: StoredPreparedSubflow) -> PreparedSubflow:
    return PreparedSubflow(
        workflow_id=stored.workflow_id,
        workflow_version=stored.workflow_version,
        fingerprint=stored.fingerprint,
        definition=stored.definition,
        requests={name: _load_request(value) for name, value in stored.requests.items()},
        subflows={node_id: _load_subflow(value) for node_id, value in stored.subflows.items()},
        snapshot=stored.snapshot,
        data_nodes={
            node_id: PreparedDataNode(credential=_load_credential(value))
            for node_id, value in stored.data_nodes.items()
        },
        protocol_nodes={
            node_id: _load_protocol_node(value) for node_id, value in stored.protocol_nodes.items()
        },
        event_nodes={
            node_id: _load_event_node(value) for node_id, value in stored.event_nodes.items()
        },
    )


def _load_credential(value: StoredCredentialMaterial) -> CredentialMaterial:
    return CredentialMaterial(**value.model_dump())


def _store_protocol_node(value: PreparedProtocolNode) -> StoredProtocolNode:
    credential = (
        StoredProtocolCredential.model_validate(value.credential, from_attributes=True)
        if value.credential is not None
        else None
    )
    return StoredProtocolNode(
        protocol=value.protocol,
        schema_id=value.schema_id,
        schema_version=value.schema_version,
        schema_hash=value.schema_hash,
        canonical_content_base64=base64.b64encode(value.canonical_content).decode(),
        credential=credential,
    )


def _load_protocol_node(value: StoredProtocolNode) -> PreparedProtocolNode:
    credential = (
        ProtocolCredentialMaterial(**value.credential.model_dump())
        if value.credential is not None
        else None
    )
    return PreparedProtocolNode(
        protocol=value.protocol,
        schema_id=value.schema_id,
        schema_version=value.schema_version,
        schema_hash=value.schema_hash,
        canonical_content=base64.b64decode(value.canonical_content_base64, validate=True),
        credential=credential,
    )


def _store_event_node(value: PreparedEventNode) -> StoredEventNode:
    return StoredEventNode(
        source_id=value.source_id,
        source_kind=value.source_kind,
        endpoints=list(value.endpoints),
        schema_registry_url=value.schema_registry_url,
        source_version=value.source_version,
        source_hash=value.source_hash,
        schema_id=value.schema_id,
        schema_version=value.schema_version,
        schema_hash=value.schema_hash,
        schema_content_base64=(
            base64.b64encode(value.schema_content).decode()
            if value.schema_content is not None
            else None
        ),
        schema_summary=value.schema_summary,
    )


def _load_event_node(value: StoredEventNode) -> PreparedEventNode:
    return PreparedEventNode(
        source_id=value.source_id,
        source_kind=value.source_kind,
        endpoints=tuple(value.endpoints),
        schema_registry_url=value.schema_registry_url,
        source_version=value.source_version,
        source_hash=value.source_hash,
        schema_id=value.schema_id,
        schema_version=value.schema_version,
        schema_hash=value.schema_hash,
        schema_content=(
            base64.b64decode(value.schema_content_base64, validate=True)
            if value.schema_content_base64 is not None
            else None
        ),
        schema_summary=value.schema_summary,
    )


def _load_multipart(value: StoredMultipart | None) -> PreparedMultipart | None:
    if value is None:
        return None
    return PreparedMultipart(
        fields=value.fields,
        files=tuple(
            PreparedUpload(
                field=item.field,
                filename=item.filename,
                content_type=item.content_type,
                content=base64.b64decode(item.content_base64, validate=True),
            )
            for item in value.files
        ),
    )
