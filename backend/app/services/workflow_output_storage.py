"""Artifact-backed storage for large workflow response bodies."""

import hashlib
import json
from typing import cast
from uuid import UUID, uuid5

from botocore.exceptions import ClientError
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.domain.workflow_output_refs import (
    REFERENCE_KEY,
    compact_response_bodies,
    restore_response_bodies,
)
from app.services.artifacts import ArtifactContent, ArtifactService


class WorkflowOutputStorage:
    def __init__(
        self,
        session: AsyncSession,
        *,
        project_id: UUID,
        execution_id: UUID,
        created_by_id: UUID,
    ) -> None:
        self._artifacts = ArtifactService(session)
        self._project_id = project_id
        self._execution_id = execution_id
        self._created_by_id = created_by_id
        self._loaded: dict[UUID, JsonValue] = {}

    async def compact(self, value: JsonValue) -> JsonValue:
        return await compact_response_bodies(
            value, store=self, inline_limit_bytes=settings.inline_body_limit_bytes
        )

    async def restore(self, value: JsonValue) -> JsonValue:
        return await restore_response_bodies(value, store=self)

    async def download(self, artifact_id: UUID) -> bytes:
        loaded = await self._load_artifact(artifact_id)
        if loaded.artifact.purpose != "workflow_output" or artifact_id != uuid5(
            self._execution_id, loaded.artifact.sha256
        ):
            raise _invalid_reference()
        return loaded.content

    async def store(self, body: JsonValue) -> dict[str, JsonValue]:
        content = _encode_body(body)
        artifact = await self._artifacts.store_workflow_output(
            project_id=self._project_id,
            execution_id=self._execution_id,
            created_by_id=self._created_by_id,
            content=content,
        )
        return {
            REFERENCE_KEY: {
                "artifact_id": str(artifact.id),
                "execution_id": str(self._execution_id),
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
            }
        }

    async def load(self, reference: dict[str, JsonValue]) -> JsonValue:
        metadata = reference.get(REFERENCE_KEY)
        if not isinstance(metadata, dict) or set(metadata) != {
            "artifact_id",
            "execution_id",
            "sha256",
            "size_bytes",
        }:
            raise _invalid_reference()
        try:
            artifact_id = UUID(cast(str, metadata["artifact_id"]))
            execution_id = UUID(cast(str, metadata["execution_id"]))
        except (ValueError, TypeError, AttributeError) as error:
            raise _invalid_reference() from error
        digest = metadata["sha256"]
        size = metadata["size_bytes"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or type(size) is not int
            or size < 0
            or artifact_id != uuid5(execution_id, digest)
        ):
            raise _invalid_reference()
        if artifact_id in self._loaded:
            return self._loaded[artifact_id]
        loaded = await self._load_artifact(artifact_id)
        if (
            loaded.artifact.purpose != "workflow_output"
            or loaded.artifact.sha256 != digest
            or loaded.artifact.size_bytes != size
            or hashlib.sha256(loaded.content).hexdigest() != digest
        ):
            raise _invalid_reference()
        try:
            body = cast(JsonValue, json.loads(loaded.content))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _invalid_reference() from error
        self._loaded[artifact_id] = body
        return body

    async def _load_artifact(self, artifact_id: UUID) -> ArtifactContent:
        try:
            return await self._artifacts.load(project_id=self._project_id, artifact_id=artifact_id)
        except AppError as error:
            if error.code == "ARTIFACT_NOT_FOUND":
                raise _unavailable_reference() from error
            raise
        except FileNotFoundError as error:
            raise _unavailable_reference() from error
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
                raise _unavailable_reference() from error
            raise


def _encode_body(body: JsonValue) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


def _invalid_reference() -> AppError:
    return AppError(
        code="WORKFLOW_OUTPUT_REFERENCE_INVALID",
        message="工作流输出引用无效或已损坏",
        status_code=409,
    )


def _unavailable_reference() -> AppError:
    return AppError(
        code="WORKFLOW_OUTPUT_REFERENCE_UNAVAILABLE",
        message="工作流输出引用对应的响应体已过保留期或不可用",
        status_code=410,
    )
