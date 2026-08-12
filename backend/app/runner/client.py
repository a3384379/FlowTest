import os
from pathlib import Path
from uuid import UUID

import httpx

from app.runner.results import RunnerExecutionResult
from app.schemas.runner_fabric import (
    RunnerAgentConfiguration,
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

    async def complete(
        self, lease_id: UUID, fencing_token: int, result: RunnerExecutionResult
    ) -> RunnerLeaseAckResponse:
        response = await self._client.post(
            f"/api/v1/runner-control/leases/{lease_id}/complete",
            headers=self._headers(),
            json={"fencing_token": fencing_token, "result": _result_payload(result)},
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
