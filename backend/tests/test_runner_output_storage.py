import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

import pytest
from pydantic import JsonValue

from app.core.config import settings
from app.domain.workflow_output_refs import REFERENCE_KEY
from app.engine.contracts import NodeStatus, NodeType, WorkflowRunStatus
from app.engine.results import NodeResult
from app.engine.scheduler import NodeRunRecord, WorkflowRunResult
from app.runner.agent import (
    _compact_checkpoint,
    _compact_result,
    _restore_resume_checkpoints,
    _submit_completion,
)
from app.runner.output_storage import RunnerLeaseOutputStores, RunnerWorkflowBodyStore
from app.runner.results import (
    RunnerBatchChildResult,
    RunnerBatchExecutionResult,
    RunnerSingleExecutionResult,
    RunnerWorkflowResult,
)
from app.schemas.runner_fabric import (
    RunnerCheckpointRequest,
    RunnerCheckpointResume,
    RunnerLeaseResponse,
    RunnerLeaseTaskResponse,
)


class MemoryOutputControlPlane:
    def __init__(self) -> None:
        self.bodies: dict[UUID, JsonValue] = {}
        self.uploads = 0
        self.completion_reference: dict[str, JsonValue] | None = None

    async def upload_output(
        self, _lease_id: UUID, _fencing_token: int, execution_id: UUID, body: JsonValue
    ) -> dict[str, JsonValue]:
        content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        digest = hashlib.sha256(content).hexdigest()
        artifact_id = uuid5(execution_id, digest)
        self.bodies[artifact_id] = body
        self.uploads += 1
        return {
            REFERENCE_KEY: {
                "artifact_id": str(artifact_id),
                "execution_id": str(execution_id),
                "sha256": digest,
                "size_bytes": len(content),
            }
        }

    async def download_output(
        self, _lease_id: UUID, _fencing_token: int, _execution_id: UUID, artifact_id: UUID
    ) -> JsonValue:
        return self.bodies[artifact_id]

    async def complete(
        self,
        _lease_id: UUID,
        _fencing_token: int,
        _result: RunnerSingleExecutionResult | None = None,
        *,
        result_reference: dict[str, JsonValue] | None = None,
    ) -> None:
        self.completion_reference = result_reference


@pytest.mark.asyncio
async def test_runner_transfers_large_body_once_and_resumes_full_output() -> None:
    execution_id = uuid4()
    control = MemoryOutputControlPlane()
    store = RunnerWorkflowBodyStore(
        control,  # type: ignore[arg-type]
        lease_id=uuid4(),
        fencing_token=1,
        execution_id=execution_id,
        inline_limit_bytes=settings.inline_body_limit_bytes,
    )
    body = {"ticket": "large", "padding": "x" * (5 * 1024 * 1024)}
    output = {"status_code": 200, "headers": {}, "body": body, "size_bytes": 5 * 1024 * 1024}
    result = NodeResult.passed(output)
    now = datetime.now(UTC)
    checkpoint = RunnerCheckpointRequest(
        execution_id=execution_id,
        node_id="request",
        node_type=NodeType.API,
        name="Request",
        status=NodeStatus.PASSED,
        attempts=1,
        output=output,
        result=result,
        started_at=now,
        finished_at=now,
        input_hash="0" * 64,
        fencing_token=1,
    )
    compacted_checkpoint = await _compact_checkpoint(checkpoint, store)
    assert len(compacted_checkpoint.model_dump_json()) < settings.runner_result_limit_bytes
    assert control.uploads == 1
    resume = RunnerCheckpointResume(
        node_id="request",
        node_type=NodeType.API,
        name="Request",
        status=NodeStatus.PASSED,
        attempts=1,
        output=compacted_checkpoint.output,
        result=compacted_checkpoint.result,
        started_at=now,
        completed_at=now,
        input_hash="0" * 64,
    )
    restored = await _restore_resume_checkpoints({str(execution_id): [resume]}, lambda _: store)
    assert restored[str(execution_id)][0].output == output

    raw = RunnerSingleExecutionResult(
        execution_id=execution_id,
        result=RunnerWorkflowResult.from_domain(
            WorkflowRunResult(
                status=WorkflowRunStatus.PASSED,
                records=(
                    NodeRunRecord(
                        node_id="request",
                        node_type=NodeType.API,
                        name="Request",
                        status=NodeStatus.PASSED,
                        attempts=1,
                        output=output,
                        result=result,
                        error_code=None,
                        error_message=None,
                        started_at=now,
                        completed_at=now,
                    ),
                ),
                context={"outputs": {"request": output}},
            )
        ),
    )
    assert len(raw.model_dump_json()) > settings.runner_result_limit_bytes
    compacted = await _compact_result(raw, lambda _: store)
    assert isinstance(compacted, RunnerSingleExecutionResult)
    assert len(compacted.model_dump_json()) < settings.runner_result_limit_bytes
    assert control.uploads == 1
    assert compacted.result.records[0].output == compacted_checkpoint.output

    large_summary = RunnerSingleExecutionResult(
        execution_id=execution_id,
        result=RunnerWorkflowResult(
            status=WorkflowRunStatus.PASSED,
            records=(),
            context={"summary": "x" * 5000},
        ),
    )
    lease = RunnerLeaseResponse(
        lease_id=uuid4(),
        runner_id=uuid4(),
        acquired_at=now,
        expires_at=now,
        task=RunnerLeaseTaskResponse(
            task_id=uuid4(),
            execution_id=execution_id,
            attempt=1,
            fencing_token=1,
            plan="test-plan",
            plan_sha256="0" * 64,
            allowed_hosts=[],
            allowed_private_cidrs=[],
            runner_result_limit_bytes=1024,
        ),
    )
    await _submit_completion(control, lease, large_summary, lambda _: store)  # type: ignore[arg-type]
    assert control.completion_reference is not None
    assert control.uploads == 2
    marker = control.completion_reference[REFERENCE_KEY]
    assert isinstance(marker, dict)
    assert control.bodies[UUID(str(marker["artifact_id"]))]["kind"] == "run"


@pytest.mark.asyncio
async def test_runner_batch_uploads_each_child_body_under_its_execution() -> None:
    control = MemoryOutputControlPlane()
    stores = RunnerLeaseOutputStores(
        control,  # type: ignore[arg-type]
        lease_id=uuid4(),
        fencing_token=1,
        inline_limit_bytes=settings.inline_body_limit_bytes,
    )
    children = []
    for ticket in ("first", "second"):
        execution_id = uuid4()
        output = {
            "status_code": 200,
            "headers": {},
            "body": {"ticket": ticket, "padding": "x" * (3 * 1024 * 1024)},
            "size_bytes": 3 * 1024 * 1024,
        }
        children.append(
            RunnerBatchChildResult(
                execution_id=execution_id,
                result=RunnerWorkflowResult(
                    status=WorkflowRunStatus.PASSED,
                    records=(),
                    context={"last": output},
                ),
            )
        )
    batch = RunnerBatchExecutionResult(execution_id=uuid4(), children=tuple(children))
    compacted = await _compact_result(batch, stores.get)
    assert isinstance(compacted, RunnerBatchExecutionResult)
    assert control.uploads == 2
    assert len(compacted.model_dump_json()) < settings.runner_result_limit_bytes
    for child in compacted.children:
        output = child.result.context["last"]
        assert isinstance(output, dict)
        reference = output["body"]
        assert isinstance(reference, dict)
        marker = reference[REFERENCE_KEY]
        assert isinstance(marker, dict)
        assert marker["execution_id"] == str(child.execution_id)
