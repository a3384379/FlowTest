import hashlib
from dataclasses import dataclass
from pathlib import PurePath
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.storage import ObjectStorage, object_storage
from app.models.access import User
from app.models.artifacts import Artifact
from app.repositories.artifacts import ArtifactRepository
from app.services.audit import AuditService
from app.services.projects import ProjectService


@dataclass(frozen=True, slots=True)
class ArtifactContent:
    artifact: Artifact
    content: bytes


class ArtifactService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        storage: ObjectStorage | None = None,
    ) -> None:
        self._session = session
        self._repository = ArtifactRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)
        self._storage = storage or object_storage

    async def upload(
        self,
        *,
        actor: User,
        project_id: UUID,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> Artifact:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        artifact = await self._store(
            actor=actor,
            project_id=project_id,
            filename=filename,
            content_type=content_type,
            content=content,
            purpose="upload",
        )
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="artifact.uploaded",
            resource_type="artifact",
            resource_id=artifact.id,
            details={"filename": artifact.filename, "size_bytes": artifact.size_bytes},
        )
        await self._session.commit()
        await self._session.refresh(artifact)
        return artifact

    async def store_response(
        self,
        *,
        actor: User,
        project_id: UUID,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> Artifact:
        return await self._store(
            actor=actor,
            project_id=project_id,
            filename=filename,
            content_type=content_type,
            content=content,
            purpose="response",
        )

    async def list_artifacts(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[Artifact], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_for_project(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def download(
        self, *, actor: User, project_id: UUID, artifact_id: UUID
    ) -> ArtifactContent:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self.load(project_id=project_id, artifact_id=artifact_id)

    async def load(self, *, project_id: UUID, artifact_id: UUID) -> ArtifactContent:
        artifact = await self._repository.get(artifact_id)
        if artifact is None or artifact.project_id != project_id:
            raise AppError(code="ARTIFACT_NOT_FOUND", message="文件不存在", status_code=404)
        stored = await self._storage.get(key=artifact.object_key)
        if hashlib.sha256(stored.content).hexdigest() != artifact.sha256:
            raise AppError(code="ARTIFACT_CORRUPTED", message="文件完整性校验失败", status_code=500)
        return ArtifactContent(artifact=artifact, content=stored.content)

    async def _store(
        self,
        *,
        actor: User,
        project_id: UUID,
        filename: str,
        content_type: str,
        content: bytes,
        purpose: str,
    ) -> Artifact:
        if len(content) > settings.artifact_limit_bytes:
            raise AppError(
                code="ARTIFACT_TOO_LARGE",
                message="文件超过 50 MB 上限",
                status_code=413,
            )
        safe_filename = _safe_filename(filename)
        artifact_id = uuid4()
        object_key = f"projects/{project_id}/artifacts/{artifact_id}"
        normalized_content_type = content_type.strip() or "application/octet-stream"
        await self._storage.put(
            key=object_key,
            content=content,
            content_type=normalized_content_type,
        )
        artifact = Artifact(
            id=artifact_id,
            project_id=project_id,
            object_key=object_key,
            filename=safe_filename,
            content_type=normalized_content_type,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            purpose=purpose,
            created_by_id=actor.id,
        )
        self._repository.add(artifact)
        await self._session.flush()
        return artifact


def _safe_filename(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    safe = PurePath(normalized).name.replace("\x00", "").strip()
    if not safe or safe in {".", ".."}:
        raise AppError(code="INVALID_FILENAME", message="文件名无效", status_code=422)
    return safe[:255]
