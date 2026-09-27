import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast
from uuid import UUID

import httpx
from pydantic import JsonValue

from app.engine.scheduler import NodeExecutionError
from app.runner.results import RunnerExecutionResult
from app.schemas.runner_fabric import (
    RunnerAcquirePermitResponse,
    RunnerAgentConfiguration,
    RunnerCheckpointRequest,
    RunnerLeaseAckResponse,
    RunnerLeaseResponse,
    RunnerRegisterResponse,
)


class RunnerControlPlaneClient:
    def __init__(
        self,
        configuration: RunnerAgentConfiguration,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._configuration = configuration
        self._client = client or httpx.AsyncClient(
            base_url=configuration.control_plane_url,
            follow_redirects=False,
            timeout=30,
        )
        self._owns_client = client is None
        self._runner_token = configuration.runner_token

    async def connect(self) -> RunnerRegisterResponse | None:
        if self._runner_token:
            await self.heartbeat(0)
            return None
        response = await self._client.post(
            "/api/v1/runner-control/register",
            headers=_authorization(self._configuration.registration_token),
            json={
                "name": self._configuration.name,
                "instance_id": self._configuration.instance_id,
                "runtime": self._configuration.runtime,
                "agent_version": self._configuration.agent_version,
                "architecture": self._configuration.architecture,
                "labels": self._configuration.labels,
                "capabilities": self._configuration.capabilities,
                "max_concurrency": self._configuration.max_concurrency,
            },
        )
        response.raise_for_status()
        registration = RunnerRegisterResponse.model_validate(response.json())
        self._runner_token = registration.token
        if self._configuration.runner_token_file:
            _persist_token(self._configuration.runner_token_file, registration.token)
        return registration

    async def heartbeat(self, current_load: int) -> None:
        response = await self._client.post(
            "/api/v1/runner-control/heartbeat",
            headers=self._headers(),
            json={"current_load": current_load},
        )
        response.raise_for_status()

    async def claim(self) -> RunnerLeaseResponse | None:
        response = await self._client.post(
            "/api/v1/runner-control/leases/claim", headers=self._headers()
        )
        response.raise_for_status()
        if response.json() is None:
            return None
        return RunnerLeaseResponse.model_validate(response.json())

    async def renew(self, lease_id: UUID, fencing_token: int) -> RunnerLeaseAckResponse:
        response = await self._client.post(
            f"/api/v1/runner-control/leases/{lease_id}/renew",
            headers=self._headers(),
            json={"fencing_token": fencing_token},
        )
        response.raise_for_status()
        return RunnerLeaseAckResponse.model_validate(response.json())

    async def acquire_outbound_permit(
        self, lease_id: UUID, fencing_token: int, timeout_seconds: float
    ) -> RunnerAcquirePermitResponse:
        response = await self._client.post(
            f"/api/v1/runner-control/leases/{lease_id}/outbound-permits/acquire",
            headers=self._headers(),
            json={"fencing_token": fencing_token, "timeout_seconds": timeout_seconds},
        )
        response.raise_for_status()
        return RunnerAcquirePermitResponse.model_validate(response.json())

    async def release_outbound_permit(
        self, lease_id: UUID, fencing_token: int, permit_id: UUID
    ) -> None:
        response = await self._client.post(
            f"/api/v1/runner-control/leases/{lease_id}/outbound-permits/release",
            headers=self._headers(),
            json={"fencing_token": fencing_token, "permit_id": str(permit_id)},
        )
        response.raise_for_status()

    async def progress(
        self,
        lease_id: UUID,
        fencing_token: int,
        progress_percent: float,
        message: str,
    ) -> RunnerLeaseAckResponse:
        response = await self._client.post(
            f"/api/v1/runner-control/leases/{lease_id}/progress",
            headers=self._headers(),
            json={
                "fencing_token": fencing_token,
                "progress_percent": progress_percent,
                "message": message,
            },
        )
        response.raise_for_status()
        return RunnerLeaseAckResponse.model_validate(response.json())

    async def checkpoint(
        self, lease_id: UUID, payload: RunnerCheckpointRequest
    ) -> RunnerLeaseAckResponse:
        response = await self._client.post(
            f"/api/v1/runner-control/leases/{lease_id}/checkpoints",
            headers=self._headers(),
            json=payload.model_dump(mode="json"),
        )
        response.raise_for_status()
        return RunnerLeaseAckResponse.model_validate(response.json())

    async def upload_output(
        self, lease_id: UUID, fencing_token: int, execution_id: UUID, body: JsonValue
    ) -> dict[str, JsonValue]:
        response = await self._client.post(
            f"/api/v1/runner-control/leases/{lease_id}/outputs/{execution_id}",
            headers={**self._headers(), "Content-Type": "application/json"},
            params={"fencing_token": fencing_token},
            content=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(),
            timeout=120,
        )
        response.raise_for_status()
        reference = response.json()
        if not isinstance(reference, dict):
            raise ValueError("Runner output reference response is invalid")
        return reference

    async def download_output(
        self, lease_id: UUID, fencing_token: int, execution_id: UUID, artifact_id: UUID
    ) -> JsonValue:
        response = await self._client.get(
            f"/api/v1/runner-control/leases/{lease_id}/outputs/{execution_id}/{artifact_id}",
            headers=self._headers(),
            params={"fencing_token": fencing_token},
            timeout=120,
        )
        response.raise_for_status()
        return cast(JsonValue, response.json())

    async def complete(
        self,
        lease_id: UUID,
        fencing_token: int,
        result: RunnerExecutionResult | None = None,
        *,
        result_reference: dict[str, JsonValue] | None = None,
    ) -> RunnerLeaseAckResponse:
        if (result is None) == (result_reference is None):
            raise ValueError("Runner completion requires one result source")
        body: dict[str, object] = {"fencing_token": fencing_token}
        if result is not None:
            body["result"] = _result_payload(result)
        else:
            body["result_reference"] = result_reference
        response = await self._client.post(
            f"/api/v1/runner-control/leases/{lease_id}/complete",
            headers=self._headers(),
            json=body,
        )
        response.raise_for_status()
        return RunnerLeaseAckResponse.model_validate(response.json())

    async def fail(
        self,
        lease_id: UUID,
        fencing_token: int,
        *,
        error_code: str,
        error_message: str,
        retryable: bool,
    ) -> RunnerLeaseAckResponse:
        response = await self._client.post(
            f"/api/v1/runner-control/leases/{lease_id}/fail",
            headers=self._headers(),
            json={
                "fencing_token": fencing_token,
                "error_code": error_code,
                "error_message": error_message,
                "retryable": retryable,
            },
        )
        response.raise_for_status()
        return RunnerLeaseAckResponse.model_validate(response.json())

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return _authorization(self._runner_token)


class RemoteOutboundAdmission:
    def __init__(
        self, control_plane: RunnerControlPlaneClient, lease_id: UUID, fencing_token: int
    ) -> None:
        self._control_plane = control_plane
        self._lease_id = lease_id
        self._fencing_token = fencing_token

    @asynccontextmanager
    async def window(self, timeout_seconds: float) -> AsyncIterator[None]:
        try:
            while True:
                decision = await self._control_plane.acquire_outbound_permit(
                    self._lease_id, self._fencing_token, timeout_seconds
                )
                if decision.granted:
                    break
                await asyncio.sleep(min(0.5, decision.retry_after_seconds))
        except httpx.HTTPError as error:
            raise NodeExecutionError(
                code="OUTBOUND_LIMITER_UNAVAILABLE",
                message="出站请求限额服务不可用。请求尚未发送",
            ) from error
        try:
            yield
        finally:
            if decision.permit_id is not None:
                try:
                    await self._control_plane.release_outbound_permit(
                        self._lease_id, self._fencing_token, decision.permit_id
                    )
                except httpx.HTTPError as error:
                    raise NodeExecutionError(
                        code="OUTBOUND_LIMITER_RELEASE_FAILED",
                        message="请求可能已完成。出站许可未能回收。不会自动重试",
                    ) from error


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _result_payload(result: RunnerExecutionResult) -> object:
    return result.model_dump(mode="json")


def _persist_token(filename: str, token: str) -> None:
    path = Path(filename)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(token)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
