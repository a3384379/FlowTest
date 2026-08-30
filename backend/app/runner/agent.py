import asyncio
import hashlib
import logging
import os
import platform
from contextlib import suppress
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
from pydantic import JsonValue

from app.core.logging import redact
from app.domain.network import OutboundNetworkPolicy
from app.engine.contracts import NodeStatus
from app.engine.results import NodeResult
from app.engine.scheduler import CancellationToken, NodeStatusUpdate
from app.runner.client import RunnerControlPlaneClient
from app.runner.workflow import PreviewRuntimeBudgetExceeded, RemoteWorkflowExecutor
from app.schemas.runner_fabric import (
    RunnerAgentConfiguration,
    RunnerCheckpointRequest,
    RunnerLeaseResponse,
)
from app.services.workflow_plan_codec import decode_execution_plan

logger = logging.getLogger(__name__)


class RunnerAgent:
    def __init__(
        self,
        configuration: RunnerAgentConfiguration,
        *,
        control_plane: RunnerControlPlaneClient | None = None,
        executor: RemoteWorkflowExecutor | None = None,
    ) -> None:
        self._configuration = configuration
        self._control_plane = control_plane or RunnerControlPlaneClient(configuration)
        self._executor = executor or RemoteWorkflowExecutor()
        self._semaphore = asyncio.Semaphore(configuration.max_concurrency)
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        try:
            if not await self._connect():
                return
            while not self._stopping.is_set():
                try:
                    await self._poll()
                except httpx.HTTPError as error:
                    if not _retryable_control_plane_error(error):
                        raise
                    _log_transient_control_plane_error(error)
                    await self._wait_for_poll()
        finally:
            await self._shutdown_tasks()
            await self._control_plane.close()

    async def _connect(self) -> bool:
        while not self._stopping.is_set():
            try:
                await self._control_plane.connect()
                return True
            except httpx.HTTPError as error:
                if not _retryable_control_plane_error(error):
                    raise
                _log_transient_control_plane_error(error)
                await self._wait_for_poll()
        return False

    async def _poll(self) -> None:
        await self._reap_tasks()
        if len(self._tasks) >= self._configuration.max_concurrency:
            await self._wait_for_poll()
            return
        lease = await self._control_plane.claim()
        if lease is None:
            await self._control_plane.heartbeat(len(self._tasks))
            await self._wait_for_poll()
            return
        task = asyncio.create_task(self._execute(lease), name=f"runner-lease-{lease.lease_id}")
        self._tasks.add(task)

    def stop(self) -> None:
        self._stopping.set()

    async def _execute(self, lease: RunnerLeaseResponse) -> None:
        async with self._semaphore:
            cancellation = CancellationToken()
            renewer = asyncio.create_task(
                self._renew_until_done(lease, cancellation),
                name=f"runner-renew-{lease.lease_id}",
            )
            try:
                if _sha256(lease.task.plan) != lease.task.plan_sha256:
                    raise ValueError("Runner plan digest mismatch")
                plan = decode_execution_plan(lease.task.plan)

                async def progress(execution_id: UUID, update: NodeStatusUpdate) -> None:
                    acknowledgment = await self._control_plane.progress(
                        lease.lease_id,
                        lease.task.fencing_token,
                        _progress_percent(update),
                        f"节点 {update.name}: {update.status.value}",
                    )
                    should_checkpoint = (
                        update.status.is_terminal and update.result is not None
                    ) or (
                        update.status is NodeStatus.RUNNING
                        and update.attempts > 0
                        and update.request_reserved
                    )
                    if should_checkpoint and hasattr(self._control_plane, "checkpoint"):
                        checkpoint = _checkpoint_payload(
                            lease,
                            update,
                            execution_id=execution_id,
                        )
                        acknowledgment = await self._control_plane.checkpoint(
                            lease.lease_id, checkpoint
                        )
                    if acknowledgment.cancel_requested:
                        cancellation.cancel(
                            force=bool(getattr(acknowledgment, "force_cancel_requested", False))
                        )

                result = await self._executor.execute(
                    plan,
                    network_policy=OutboundNetworkPolicy(
                        allowed_hosts=tuple(lease.task.allowed_hosts),
                        allowed_private_cidrs=tuple(lease.task.allowed_private_cidrs),
                        enabled=lease.task.outbound_policy_enabled,
                    ),
                    cancellation=cancellation,
                    on_progress=progress,
                    resume_checkpoints=lease.task.resume_checkpoints,
                    reset_retry_budget=lease.task.reset_retry_budget,
                )
                await self._control_plane.complete(lease.lease_id, lease.task.fencing_token, result)
            except PreviewRuntimeBudgetExceeded:
                with suppress(httpx.HTTPError):
                    await self._control_plane.fail(
                        lease.lease_id,
                        lease.task.fencing_token,
                        error_code="PREVIEW_RUNTIME_BUDGET_EXCEEDED",
                        error_message="Sandbox Preview 数据集已达到整批运行时预算",
                        retryable=False,
                    )
            except httpx.HTTPStatusError as error:
                if error.response.status_code != 409:
                    logger.warning(
                        "Runner control plane rejected execution",
                        extra={
                            "lease_id": str(lease.lease_id),
                            "status": error.response.status_code,
                        },
                    )
            except Exception:
                logger.exception("Runner execution failed", extra={"lease_id": str(lease.lease_id)})
                with suppress(httpx.HTTPError):
                    await self._control_plane.fail(
                        lease.lease_id,
                        lease.task.fencing_token,
                        error_code="RUNNER_EXECUTION_ERROR",
                        error_message="Runner 执行发生内部错误",
                        retryable=True,
                    )
            finally:
                renewer.cancel()
                await asyncio.gather(renewer, return_exceptions=True)

    async def _renew_until_done(
        self, lease: RunnerLeaseResponse, cancellation: CancellationToken
    ) -> None:
        interval = max(
            1.0,
            (lease.expires_at - lease.acquired_at).total_seconds() / 3,
        )
        while True:
            await asyncio.sleep(interval)
            acknowledgment = await self._control_plane.renew(
                lease.lease_id, lease.task.fencing_token
            )
            if acknowledgment.cancel_requested:
                cancellation.cancel(
                    force=bool(getattr(acknowledgment, "force_cancel_requested", False))
                )

    async def _reap_tasks(self) -> None:
        completed = {task for task in self._tasks if task.done()}
        if completed:
            await asyncio.gather(*completed, return_exceptions=True)
            self._tasks.difference_update(completed)

    async def _shutdown_tasks(self) -> None:
        if not self._tasks:
            return
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _wait_for_poll(self) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=self._configuration.poll_seconds)


def configuration_from_environment() -> RunnerAgentConfiguration:
    runner_token_file = os.environ.get("FLOWTEST_RUNNER_TOKEN_FILE", "")
    return RunnerAgentConfiguration(
        control_plane_url=os.environ.get("FLOWTEST_RUNNER_CONTROL_PLANE_URL", ""),
        registration_token=os.environ.get("FLOWTEST_RUNNER_REGISTRATION_TOKEN", ""),
        runner_token=os.environ.get("FLOWTEST_RUNNER_TOKEN", "")
        or _read_runner_token(runner_token_file),
        runner_token_file=runner_token_file,
        name=os.environ.get("FLOWTEST_RUNNER_NAME", platform.node()),
        instance_id=os.environ.get("FLOWTEST_RUNNER_INSTANCE_ID", str(uuid4())),
        runtime=os.environ.get("FLOWTEST_RUNNER_RUNTIME", "docker"),
        agent_version=os.environ.get("FLOWTEST_RUNNER_AGENT_VERSION", "3.0.0-beta.3"),
        architecture=os.environ.get("FLOWTEST_RUNNER_ARCHITECTURE", platform.machine()),
        labels=_csv_environment("FLOWTEST_RUNNER_LABELS"),
        capabilities=_csv_environment("FLOWTEST_RUNNER_CAPABILITIES", default=["flow.workflow"]),
        max_concurrency=int(os.environ.get("FLOWTEST_RUNNER_MAX_CONCURRENCY", "1")),
        poll_seconds=float(os.environ.get("FLOWTEST_RUNNER_POLL_SECONDS", "1")),
        production=os.environ.get("FLOWTEST_ENVIRONMENT", "local") == "production",
    )


def _read_runner_token(filename: str) -> str:
    if not filename:
        return ""
    try:
        token = Path(filename).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    if len(token) > 512:
        raise ValueError("Runner identity token file is too large")
    return token


def _csv_environment(name: str, *, default: list[str] | None = None) -> list[str]:
    value = os.environ.get(name, "")
    if not value:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _progress_percent(update: NodeStatusUpdate) -> float:
    if update.status.is_terminal:
        return 50.0
    return 10.0


def _checkpoint_payload(
    lease: RunnerLeaseResponse,
    update: NodeStatusUpdate,
    *,
    execution_id: UUID | None = None,
) -> RunnerCheckpointRequest:
    result = update.result
    if update.status.is_terminal and result is None:
        raise ValueError("terminal Runner status requires a NodeResult")
    redacted_result = (
        None
        if result is None
        else NodeResult.model_validate(redact(result.model_dump(mode="json")))
    )
    snapshot = update.context_snapshot or {}
    extracted = snapshot.get("extracted_variables", {})
    if not isinstance(extracted, dict):
        extracted = {}
    input_hash = update.input_hash or _sha256(f"{update.node_id}:{snapshot!r}")
    return RunnerCheckpointRequest(
        execution_id=execution_id or lease.task.execution_id,
        node_id=update.node_id,
        node_type=update.node_type,
        name=update.name,
        status=update.status,
        attempts=update.attempts,
        output=redacted_result.output if redacted_result is not None else None,
        result=redacted_result,
        error_code=update.error_code,
        error_message=update.error_message,
        started_at=update.started_at,
        finished_at=update.occurred_at,
        input_hash=input_hash,
        extracted_variables=cast(dict[str, JsonValue], redact(extracted)),
        snapshot_revision=1,
        fencing_token=lease.task.fencing_token,
        phase=update.phase,
        best_effort=update.best_effort,
    )


def _retryable_control_plane_error(error: httpx.HTTPError) -> bool:
    if not isinstance(error, httpx.HTTPStatusError):
        return True
    return error.response.status_code in {408, 425, 429} or error.response.status_code >= 500


def _log_transient_control_plane_error(error: httpx.HTTPError) -> None:
    status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
    logger.warning("Runner control plane temporarily unavailable", extra={"status": status})


def main() -> None:
    logging.basicConfig(level=os.environ.get("FLOWTEST_LOG_LEVEL", "INFO"))
    asyncio.run(RunnerAgent(configuration_from_environment()).run())


if __name__ == "__main__":
    main()
