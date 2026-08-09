import base64
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from app.domain.api_assets import BodyKind, HttpMethod
from app.domain.scopes import HeaderScope, VariableScope
from app.engine.contracts import WorkflowDefinition
from app.services.api_assets import PreparedHeader, PreparedRequest, PreparedVariable
from app.services.executions import PreparedMultipart, PreparedUpload
from app.services.workflow_runtime import PreparedWorkflowRequest
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


class StoredPreparedExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: dict[str, JsonValue]
    requests: dict[str, StoredRequest]
    dataset_variables: dict[str, JsonValue]


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
            dataset_variables=plan.prepared.dataset_variables,
        ),
        runtime_variables=plan.runtime_variables,
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
    )


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
            dataset_variables=stored.prepared.dataset_variables,
        ),
        runtime_variables=stored.runtime_variables,
    )


def _load_request(stored: StoredRequest) -> PreparedWorkflowRequest:
    return PreparedWorkflowRequest(
        request=PreparedRequest(
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
        ),
        body_kind=stored.body_kind,
        multipart=_load_multipart(stored.multipart),
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
