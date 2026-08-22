import base64
import binascii
import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import EncryptedValue, SecretBox, secret_box
from app.core.errors import AppError
from app.domain.api_assets import APIVersionSpec
from app.importers.contracts import (
    ImportChange,
    ImportedOperation,
    ImportSourceKind,
    ImportSourceType,
)
from app.importers.document import ImportDocumentError, parse_import_document
from app.importers.sources import ImportDocumentFetcher, ImportUrlDiscovery
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


@dataclass(frozen=True, slots=True)
class ImportSourceIdentity:
    kind: ImportSourceKind
    key: str
    name: str
    url: str | None
    document_url: str | None


class ImportService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        secrets: SecretBox = secret_box,
        document_fetcher: ImportDocumentFetcher | None = None,
    ) -> None:
        self._session = session
        self._assets = APIAssetRepository(session)
        self._imports = ImportRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)
        self._secrets = secrets
        self._document_fetcher = document_fetcher

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
        source = _file_source(source_name)
        try:
            detected_type, operations = parse_import_document(content, source_type)
        except ImportDocumentError as error:
            raise AppError(code="IMPORT_INVALID", message=str(error), status_code=422) from error
        _ensure_unique_operations(operations)
        results = await self._apply_operations(
            actor=actor,
            project_id=project_id,
            source=source,
            operations=operations,
        )
        results.extend(
            await self._deleted_results(
                project_id=project_id,
                source=source,
                imported_keys={operation.import_key for operation in operations},
            )
        )
        counts = Counter(item.change for item in results)
        run = ImportRun(
            project_id=project_id,
            source_kind=source.kind.value,
            source_key=source.key,
            source_type=detected_type.value,
            source_name=source.name,
            source_url=source.url,
            document_url=source.document_url,
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
                "source_kind": source.kind.value,
                "source_name": source.name,
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
        return await self._preview_content(
            actor=actor,
            project_id=project_id,
            source=_file_source(source_name),
            source_type=source_type,
            content=content,
        )

    async def preview_url(
        self,
        *,
        actor: User,
        project_id: UUID,
        url: str,
        source_type: ImportSourceType,
        maximum_bytes: int,
        document_id: str | None = None,
    ) -> ImportRun:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        if self._document_fetcher is None:
            raise RuntimeError("URL import document fetcher is not configured")
        policy = await self._projects.load_runtime_security_policy(project_id)
        fetched = await self._document_fetcher.fetch(
            url=url,
            network_policy=policy,
            maximum_bytes=maximum_bytes,
            document_id=document_id,
        )
        return await self._preview_content(
            actor=actor,
            project_id=project_id,
            source=_url_source(
                requested_url=url,
                source_page_url=fetched.source_page_url,
                resolved_url=fetched.resolved_url,
                source_name=fetched.source_name,
                document_id=fetched.document_id,
                discovered_from_page=fetched.discovered_from_page,
            ),
            source_type=source_type,
            content=fetched.content,
        )

    async def discover_url(
        self,
        *,
        actor: User,
        project_id: UUID,
        url: str,
        maximum_bytes: int,
    ) -> ImportUrlDiscovery:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        if self._document_fetcher is None:
            raise RuntimeError("URL import document fetcher is not configured")
        policy = await self._projects.load_runtime_security_policy(project_id)
        return await self._document_fetcher.discover(
            url=url,
            network_policy=policy,
            maximum_bytes=maximum_bytes,
        )

    async def _preview_content(
        self,
        *,
        actor: User,
        project_id: UUID,
        source: ImportSourceIdentity,
        source_type: ImportSourceType,
        content: bytes,
    ) -> ImportRun:
        try:
            detected_type, operations = parse_import_document(content, source_type)
        except ImportDocumentError as error:
            raise AppError(code="IMPORT_INVALID", message=str(error), status_code=422) from error
        _ensure_unique_operations(operations)
        results = await self._preview_operations(
            project_id=project_id,
            source=source,
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
            source_kind=source.kind.value,
            source_key=source.key,
            source_type=detected_type.value,
            source_name=source.name,
            source_url=source.url,
            document_url=source.document_url,
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
                "source_kind": source.kind.value,
                "source_name": source.name,
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
        source = ImportSourceIdentity(
            kind=ImportSourceKind(run.source_kind),
            key=run.source_key,
            name=run.source_name,
            url=run.source_url,
            document_url=run.document_url,
        )
        current = await self._preview_operations(
            project_id=project_id,
            source=source,
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
            source=source,
            operations=selected_operations,
        )
        await self._deactivate_deleted(
            project_id=project_id,
            source=source,
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
        source: ImportSourceIdentity,
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
                source=source,
                imported_keys={operation.import_key for operation in operations},
            )
        )
        return results

    async def _apply_operations(
        self,
        *,
        actor: User,
        project_id: UUID,
        source: ImportSourceIdentity,
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
                    source=source,
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
                    source=source,
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
        source: ImportSourceIdentity,
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
            import_source=source.name,
            import_source_key=source.key,
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
        source: ImportSourceIdentity,
        operation: ImportedOperation,
    ) -> tuple[APIDefinition, APIVersion]:
        definition.name = operation.name
        definition.description = operation.description
        definition.import_fingerprint = operation.content_fingerprint
        definition.import_source = source.name
        definition.import_source_key = source.key
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
        source: ImportSourceIdentity,
        imported_keys: set[str],
    ) -> list[ImportItemResult]:
        previous = await self._assets.list_imported_definitions(
            project_id=project_id, import_source_key=source.key
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
        source: ImportSourceIdentity,
        deleted_keys: set[str],
    ) -> None:
        if not deleted_keys:
            return
        definitions = await self._assets.list_imported_definitions(
            project_id=project_id,
            import_source_key=source.key,
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
        extraction_rules=[],
        assertions=[],
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


def _file_source(source_name: str) -> ImportSourceIdentity:
    normalized = _normalize_source_name(source_name)
    return ImportSourceIdentity(
        kind=ImportSourceKind.FILE,
        key=f"file:{normalized}",
        name=normalized,
        url=None,
        document_url=None,
    )


def _url_source(
    *,
    requested_url: str,
    source_page_url: str,
    resolved_url: str,
    source_name: str,
    document_id: str,
    discovered_from_page: bool,
) -> ImportSourceIdentity:
    canonical = _canonical_url(requested_url)
    if discovered_from_page:
        canonical = f"{canonical}#{document_id}"
    name = source_name.strip()[:255] or "remote/openapi-document"
    return ImportSourceIdentity(
        kind=ImportSourceKind.URL,
        key=f"url:{hashlib.sha256(canonical.encode()).hexdigest()}",
        name=name,
        url=_sanitized_url(source_page_url),
        document_url=_sanitized_url(resolved_url),
    )


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    default_port = 443 if scheme == "https" else 80
    port = f":{parsed.port}" if parsed.port is not None and parsed.port != default_port else ""
    path = parsed.path or "/"
    return urlunsplit((scheme, f"{hostname}{port}", path, parsed.query, ""))


def _sanitized_url(url: str) -> str:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme.lower(), f"{hostname}{port}", parsed.path, "", ""))[:2048]


def _preview_associated_data(run_id: UUID) -> bytes:
    return f"flowtest:import-preview:{run_id}".encode()
