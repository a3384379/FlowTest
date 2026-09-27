"""Lease-scoped transfer of large workflow HTTP bodies."""

import hashlib
import json
from uuid import UUID, uuid5

from pydantic import JsonValue

from app.domain.workflow_output_refs import (
    REFERENCE_KEY,
    compact_response_bodies,
    restore_response_bodies,
)
from app.runner.client import RunnerControlPlaneClient


class RunnerWorkflowBodyStore:
    def __init__(
        self,
        control_plane: RunnerControlPlaneClient,
        *,
        lease_id: UUID,
        fencing_token: int,
        execution_id: UUID,
        inline_limit_bytes: int,
    ) -> None:
        self._control_plane = control_plane
        self._lease_id = lease_id
        self._fencing_token = fencing_token
        self._execution_id = execution_id
        self._inline_limit_bytes = inline_limit_bytes
        self._stored: dict[str, dict[str, JsonValue]] = {}
        self._loaded: dict[UUID, JsonValue] = {}

    async def compact(self, value: JsonValue) -> JsonValue:
        return await compact_response_bodies(
            value, store=self, inline_limit_bytes=self._inline_limit_bytes
        )

    async def restore(self, value: JsonValue) -> JsonValue:
        return await restore_response_bodies(value, store=self)

    async def store(self, body: JsonValue) -> dict[str, JsonValue]:
        content = _encode_body(body)
        digest = hashlib.sha256(content).hexdigest()
        if digest in self._stored:
            return self._stored[digest]
        reference = await self._control_plane.upload_output(
            self._lease_id, self._fencing_token, self._execution_id, body
        )
        artifact_id, origin_id, reported_digest, size = _reference_metadata(reference)
        if (
            origin_id != self._execution_id
            or artifact_id != uuid5(self._execution_id, digest)
            or reported_digest != digest
            or size != len(content)
        ):
            raise ValueError("Runner output upload returned an invalid reference")
        self._stored[digest] = reference
        return reference

    async def load(self, reference: dict[str, JsonValue]) -> JsonValue:
        artifact_id, origin_id, digest, size = _reference_metadata(reference)
        if artifact_id in self._loaded:
            return self._loaded[artifact_id]
        body = await self._control_plane.download_output(
            self._lease_id, self._fencing_token, origin_id, artifact_id
        )
        content = _encode_body(body)
        if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Runner output download failed integrity validation")
        self._loaded[artifact_id] = body
        return body


def _reference_metadata(reference: dict[str, JsonValue]) -> tuple[UUID, UUID, str, int]:
    metadata = reference.get(REFERENCE_KEY)
    if not isinstance(metadata, dict):
        raise ValueError("Runner output reference is invalid")
    raw_id = metadata.get("artifact_id")
    raw_origin = metadata.get("execution_id")
    digest = metadata.get("sha256")
    size = metadata.get("size_bytes")
    if (
        not isinstance(raw_id, str)
        or not isinstance(raw_origin, str)
        or not isinstance(digest, str)
        or len(digest) != 64
        or type(size) is not int
        or size < 0
    ):
        raise ValueError("Runner output reference is invalid")
    artifact_id = UUID(raw_id)
    origin_id = UUID(raw_origin)
    if artifact_id != uuid5(origin_id, digest):
        raise ValueError("Runner output reference is invalid")
    return artifact_id, origin_id, digest, size


def _encode_body(body: JsonValue) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


class RunnerLeaseOutputStores:
    def __init__(
        self,
        control_plane: RunnerControlPlaneClient,
        *,
        lease_id: UUID,
        fencing_token: int,
        inline_limit_bytes: int,
    ) -> None:
        self._control_plane = control_plane
        self._lease_id = lease_id
        self._fencing_token = fencing_token
        self._inline_limit_bytes = inline_limit_bytes
        self._stores: dict[UUID, RunnerWorkflowBodyStore] = {}

    def get(self, execution_id: UUID) -> RunnerWorkflowBodyStore:
        if execution_id not in self._stores:
            self._stores[execution_id] = RunnerWorkflowBodyStore(
                self._control_plane,
                lease_id=self._lease_id,
                fencing_token=self._fencing_token,
                execution_id=execution_id,
                inline_limit_bytes=self._inline_limit_bytes,
            )
        return self._stores[execution_id]
