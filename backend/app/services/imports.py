import base64
import binascii
import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import EncryptedValue, SecretBox, secret_box
from app.core.errors import AppError
from app.domain.api_assets import APIVersionSpec
from app.importers.contracts import ImportChange, ImportedOperation, ImportSourceType
from app.importers.document import ImportDocumentError, parse_import_document
from app.models.access import User
from app.models.api_assets import APIDefinition, APIVersion
from app.models.imports import ImportRun
from app.repositories.api_assets import APIAssetRepository
from app.repositories.imports import ImportRepository
from app.services.audit import AuditService
from app.services.projects import ProjectService


@dataclass(frozen=True, slots=True)
class ImportItemResult:
    import_key: str
    name: str
    method: str
    path: str
    change: ImportChange
    definition_id: UUID | None
    version: int

    def as_json(self) -> dict[str, str | int | None]:
        return {
            "import_key": self.import_key,
            "name": self.name,
            "method": self.method,
            "path": self.path,
            "change": self.change.value,
            "definition_id": str(self.definition_id) if self.definition_id else None,
            "version": self.version,
        }


class ImportService:
    def __init__(self, session: AsyncSession, *, secrets: SecretBox = secret_box) -> None:
        self._session = session
        self._assets = APIAssetRepository(session)
        self._imports = ImportRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)
        self._secrets = secrets

    async def import_document(
        self,
        *,
        actor: User,
        project_id: UUID,
        source_name: str,
        source_type: ImportSourceType,
        content: bytes,
    ) -> ImportRun:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        try:
            detected_type, operations = parse_import_document(content, source_type)
        except ImportDocumentError as error:
            raise AppError(code="IMPORT_INVALID", message=str(error), status_code=422) from error
        _ensure_unique_operations(operations)
        normalized_source = _normalize_source_name(source_name)
        results = await self._apply_operations(
            actor=actor,
            project_id=project_id,
            source_name=normalized_source,
            operations=operations,
        )
        results.extend(
            await self._deleted_results(
                project_id=project_id,
                source_name=normalized_source,
                imported_keys={operation.import_key for operation in operations},
            )
        )
        counts = Counter(item.change for item in results)
        run = ImportRun(
            project_id=project_id,
            source_type=detected_type.value,
            source_name=normalized_source,
            source_sha256=hashlib.sha256(content).hexdigest(),
            added=counts[ImportChange.ADDED],
            changed=counts[ImportChange.CHANGED],
            deleted=counts[ImportChange.DELETED],
            unchanged=counts[ImportChange.UNCHANGED],
            results=[item.as_json() for item in results],
            status="applied",
            applied_keys=[
                item.import_key
                for item in results
                if item.change in {ImportChange.ADDED, ImportChange.CHANGED}
            ],
            payload_ciphertext=None,
            payload_nonce=None,
            applied_at=datetime.now(UTC),
            created_by_id=actor.id,
        )
        self._imports.add(run)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="api.imported",
            resource_type="import_run",
            resource_id=run.id,
            details={
                "source_type": detected_type.value,
                "source_name": normalized_source,
                "added": run.added,
                "changed": run.changed,
                "deleted": run.deleted,
                "unchanged": run.unchanged,
            },
        )
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def preview_document(
        self,
        *,
        actor: User,
        project_id: UUID,
        source_name: str,
        source_type: ImportSourceType,
        content: bytes,
    ) -> ImportRun:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        try:
            detected_type, operations = parse_import_document(content, source_type)
        except ImportDocumentError as error:
            raise AppError(code="IMPORT_INVALID", message=str(error), status_code=422) from error
        _ensure_unique_operations(operations)
        normalized_source = _normalize_source_name(source_name)
        results = await self._preview_operations(
            project_id=project_id,
            source_name=normalized_source,
            operations=operations,
        )
        counts = Counter(item.change for item in results)
        run_id = uuid4()
        encrypted = self._secrets.encrypt(
            base64.b64encode(content).decode(),
            associated_data=_preview_associated_data(run_id),
        )
        run = ImportRun(
            id=run_id,
            project_id=project_id,
            source_type=detected_type.value,
            source_name=normalized_source,
            source_sha256=hashlib.sha256(content).hexdigest(),
            added=counts[ImportChange.ADDED],
            changed=counts[ImportChange.CHANGED],
            deleted=counts[ImportChange.DELETED],
            unchanged=counts[ImportChange.UNCHANGED],
            results=[item.as_json() for item in results],
            status="preview",
            applied_keys=[],
            payload_ciphertext=encrypted.ciphertext,
            payload_nonce=encrypted.nonce,
            applied_at=None,
            created_by_id=actor.id,
        )
        self._imports.add(run)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="api.import_previewed",
            resource_type="import_run",
            resource_id=run.id,
            details={
                "source_name": normalized_source,
                "added": run.added,
                "changed": run.changed,
                "deleted": run.deleted,
                "unchanged": run.unchanged,
            },
        )
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def merge_preview(
        self,
        *,
        actor: User,
        project_id: UUID,
        run_id: UUID,
        selected_keys: set[str],
    ) -> ImportRun:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        run = await self._imports.get(run_id)
        if run is None or run.project_id != project_id:
            raise AppError(code="IMPORT_NOT_FOUND", message="导入预览不存在", status_code=404)
        if run.status != "preview":
            if set(run.applied_keys) == selected_keys:
                return run
            raise AppError(
                code="IMPORT_ALREADY_APPLIED", message="导入预览已经合并", status_code=409
            )
        content = self._load_preview(run)
        _, operations = parse_import_document(content, ImportSourceType(run.source_type))
        current = await self._preview_operations(
            project_id=project_id,
            source_name=run.source_name,
            operations=operations,
        )
        if [item.as_json() for item in current] != run.results:
            raise AppError(
                code="IMPORT_PREVIEW_STALE",
                message="接口定义已变化, 请重新生成导入预览",
                status_code=409,
            )
        selectable = {
            item.import_key for item in current if item.change is not ImportChange.UNCHANGED
        }
        if not selected_keys <= selectable:
            raise AppError(
                code="IMPORT_SELECTION_INVALID",
                message="合并选择包含无效或未变化的接口",
                status_code=422,
            )
        selected_operations = tuple(
            operation for operation in operations if operation.import_key in selected_keys
        )
        await self._apply_operations(
            actor=actor,
            project_id=project_id,
            source_name=run.source_name,
            operations=selected_operations,
        )
        await self._deactivate_deleted(
            project_id=project_id,
            source_name=run.source_name,
            deleted_keys={
                item.import_key
                for item in current
                if item.change is ImportChange.DELETED and item.import_key in selected_keys
            },
        )
        run.status = "applied"
        run.applied_keys = sorted(selected_keys)
        run.applied_at = datetime.now(UTC)
        run.payload_ciphertext = None
        run.payload_nonce = None
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="api.import_merged",
            resource_type="import_run",
            resource_id=run.id,
            details={"applied_keys": run.applied_keys},
        )
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def list_runs(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[ImportRun], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._imports.list_for_project(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def _preview_operations(
        self,
        *,
        project_id: UUID,
        source_name: str,
        operations: tuple[ImportedOperation, ...],
    ) -> list[ImportItemResult]:
        results: list[ImportItemResult] = []
        for operation in operations:
            existing = await self._assets.find_imported_definition(
                project_id=project_id,
                import_key=operation.import_key,
            )
            if existing is None:
                results.append(
                    ImportItemResult(
                        import_key=operation.import_key,
                        name=operation.name,
                        method=operation.request.method.value,
                        path=operation.request.path,
                        change=ImportChange.ADDED,
                        definition_id=None,
                        version=0,
                    )
                )
                continue
            version = await self._current_version(existing)
            change = (
                ImportChange.UNCHANGED
                if existing.import_fingerprint == operation.content_fingerprint
                and existing.is_active
                else ImportChange.CHANGED
            )
            results.append(_result(operation, change, existing, version.version))
        results.extend(
            await self._deleted_results(
                project_id=project_id,
                source_name=source_name,
                imported_keys={operation.import_key for operation in operations},
            )
        )
        return results

    async def _apply_operations(
        self,
        *,
        actor: User,
        project_id: UUID,
        source_name: str,
        operations: tuple[ImportedOperation, ...],
    ) -> list[ImportItemResult]:
        results: list[ImportItemResult] = []
        for operation in operations:
            existing = await self._assets.find_imported_definition(
                project_id=project_id, import_key=operation.import_key
            )
            if existing is None:
                definition, version = await self._create_definition(
                    actor=actor,
                    project_id=project_id,
                    source_name=source_name,
                    operation=operation,
                )
                change = ImportChange.ADDED
            elif (
                existing.import_fingerprint == operation.content_fingerprint and existing.is_active
            ):
                definition = existing
                version = await self._current_version(existing)
                change = ImportChange.UNCHANGED
            else:
                definition, version = await self._update_definition(
                    actor=actor,
                    definition=existing,
                    source_name=source_name,
                    operation=operation,
                )
                change = ImportChange.CHANGED
            results.append(_result(operation, change, definition, version.version))
        return results

    async def _create_definition(
        self,
        *,
        actor: User,
        project_id: UUID,
        source_name: str,
        operation: ImportedOperation,
    ) -> tuple[APIDefinition, APIVersion]:
        definition = APIDefinition(
            project_id=project_id,
            folder_id=None,
            name=operation.name,
            description=operation.description,
            current_version=1,
            is_active=True,
            import_key=operation.import_key,
            import_fingerprint=operation.content_fingerprint,
            import_source=source_name,
            created_by_id=actor.id,
        )
        self._assets.add(definition)
        await self._session.flush()
        version = _version_model(definition.id, 1, actor.id, operation.request)
        self._assets.add(version)
        await self._session.flush()
        return definition, version

    async def _update_definition(
        self,
        *,
        actor: User,
        definition: APIDefinition,
        source_name: str,
        operation: ImportedOperation,
    ) -> tuple[APIDefinition, APIVersion]:
        definition.name = operation.name
        definition.description = operation.description
        definition.import_fingerprint = operation.content_fingerprint
        definition.import_source = source_name
        definition.is_active = True
        definition.current_version += 1
        version = _version_model(
            definition.id,
            definition.current_version,
            actor.id,
            operation.request,
        )
        self._assets.add(version)
        await self._session.flush()
        return definition, version

    async def _current_version(self, definition: APIDefinition) -> APIVersion:
        version = await self._assets.get_version(
            definition_id=definition.id, version=definition.current_version
        )
        if version is None:
            raise RuntimeError("Imported API current version is missing")
        return version

    async def _deleted_results(
        self,
        *,
        project_id: UUID,
        source_name: str,
        imported_keys: set[str],
    ) -> list[ImportItemResult]:
        previous = await self._assets.list_imported_definitions(
            project_id=project_id, import_source=source_name
        )
        results: list[ImportItemResult] = []
        for definition in previous:
            if (
                not definition.is_active
                or not definition.import_key
                or definition.import_key in imported_keys
            ):
                continue
            version = await self._current_version(definition)
            results.append(
                ImportItemResult(
                    import_key=definition.import_key,
                    name=definition.name,
                    method=version.method,
                    path=version.path,
                    change=ImportChange.DELETED,
                    definition_id=definition.id,
                    version=definition.current_version,
                )
            )
        return results

    async def _deactivate_deleted(
        self,
        *,
        project_id: UUID,
        source_name: str,
        deleted_keys: set[str],
    ) -> None:
        if not deleted_keys:
            return
        definitions = await self._assets.list_imported_definitions(
            project_id=project_id,
            import_source=source_name,
        )
        for definition in definitions:
            if definition.import_key in deleted_keys:
                definition.is_active = False

    def _load_preview(self, run: ImportRun) -> bytes:
        if run.payload_ciphertext is None or run.payload_nonce is None:
            raise AppError(
                code="IMPORT_PREVIEW_PAYLOAD_MISSING",
                message="导入预览内容不可用, 请重新生成预览",
                status_code=409,
            )
        encoded = self._secrets.decrypt(
            EncryptedValue(run.payload_ciphertext, run.payload_nonce),
            associated_data=_preview_associated_data(run.id),
        )
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise AppError(
                code="IMPORT_PREVIEW_PAYLOAD_INVALID",
                message="导入预览内容损坏",
                status_code=409,
            ) from error
        if hashlib.sha256(content).hexdigest() != run.source_sha256:
            raise AppError(
                code="IMPORT_PREVIEW_PAYLOAD_INVALID",
                message="导入预览内容校验失败",
                status_code=409,
            )
        return content


def _version_model(
    definition_id: UUID,
    version: int,
    actor_id: UUID,
    request: APIVersionSpec,
) -> APIVersion:
    return APIVersion(
        api_definition_id=definition_id,
        version=version,
        method=request.method.value,
        path=request.path,
        query_parameters=[
            {"name": item.name, "value": item.value, "enabled": item.enabled}
            for item in request.query_parameters
        ],
        headers=request.headers,
        body_kind=request.body_kind.value,
        body=request.body,
        auth_kind=request.auth_kind.value,
        auth_config=request.auth_config,
        created_by_id=actor_id,
    )


def _result(
    operation: ImportedOperation,
    change: ImportChange,
    definition: APIDefinition,
    version: int,
) -> ImportItemResult:
    return ImportItemResult(
        import_key=operation.import_key,
        name=operation.name,
        method=operation.request.method.value,
        path=operation.request.path,
        change=change,
        definition_id=definition.id,
        version=version,
    )


def _ensure_unique_operations(operations: tuple[ImportedOperation, ...]) -> None:
    keys = [operation.import_key for operation in operations]
    if len(keys) != len(set(keys)):
        raise AppError(
            code="IMPORT_DUPLICATE_OPERATION",
            message="导入文档中包含重复的请求方法和路径",
            status_code=422,
        )


def _normalize_source_name(source_name: str) -> str:
    normalized = source_name.strip().replace("\\", "/").rsplit("/", 1)[-1]
    return normalized[:255] or "import-document"


def _preview_associated_data(run_id: UUID) -> bytes:
    return f"flowtest:import-preview:{run_id}".encode()
