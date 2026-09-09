import base64
import binascii
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import EncryptedValue, SecretBox, secret_box
from app.core.errors import AppError
from app.domain.api_assets import APIVersionSpec
from app.domain.canonical_schemas import CanonicalSchemaValidationError
from app.domain.test_engineering import OperationContract, fingerprint_contract
from app.importers.contracts import (
    ImportChange,
    ImportedOperation,
    ImportSourceKind,
    ImportSourceType,
)
from app.importers.document import ImportDocumentError, parse_import_document
from app.importers.sources import ImportDocumentFetcher, ImportUrlDiscovery
from app.models.access import User
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.imports import ImportRun
from app.models.service_targets import ServiceEndpoint
from app.repositories.api_assets import APIAssetRepository
from app.repositories.imports import ImportRepository
from app.repositories.service_targets import ServiceTargetRepository
from app.services.audit import AuditService
from app.services.encryption_keys import active_key_reference_for_project
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
    server_url: str | None = None

    def as_json(self) -> dict[str, str | int | None]:
        result = {
            "import_key": self.import_key,
            "name": self.name,
            "method": self.method,
            "path": self.path,
            "change": self.change.value,
            "definition_id": str(self.definition_id) if self.definition_id else None,
            "version": self.version,
        }
        if self.server_url is not None:
            result["server_url"] = self.server_url
        return result


@dataclass(frozen=True, slots=True)
class ImportSourceIdentity:
    kind: ImportSourceKind
    key: str
    name: str
    url: str | None
    document_url: str | None


@dataclass(frozen=True, slots=True)
class ImportPreviewSummary:
    source: ImportSourceIdentity
    source_type: ImportSourceType
    source_sha256: str
    results: tuple[ImportItemResult, ...]


@dataclass(frozen=True, slots=True)
class ImportPreviewTarget:
    """Target selection frozen with an MCP contract preview."""

    service_id: UUID | None
    environment_id: UUID | None
    endpoint_variant: str
    allowed_environment_classifications: frozenset[str] | None = None


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
        self._targets = ServiceTargetRepository(session)
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
        except CanonicalSchemaValidationError as error:
            raise _canonical_contract_error(error) from error
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
        target: ImportPreviewTarget | None = None,
        max_results: int | None = None,
    ) -> ImportRun:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        return await self._preview_content(
            actor=actor,
            project_id=project_id,
            source=_file_source(source_name),
            source_type=source_type,
            content=content,
            target=target,
            max_results=max_results,
        )

    async def preview_document_dry_run(
        self,
        *,
        actor: User,
        project_id: UUID,
        source_name: str,
        source_type: ImportSourceType,
        content: bytes,
        max_results: int | None = None,
    ) -> ImportPreviewSummary:
        """Preview an import without creating an ImportRun or changing assets."""

        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        return await self._preview_content_summary(
            project_id=project_id,
            source=_file_source(source_name),
            source_type=source_type,
            content=content,
            max_results=max_results,
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
        target: ImportPreviewTarget | None = None,
        max_results: int | None = None,
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
            target=target,
            max_results=max_results,
        )

    async def preview_url_dry_run(
        self,
        *,
        actor: User,
        project_id: UUID,
        url: str,
        source_type: ImportSourceType,
        maximum_bytes: int,
        document_id: str | None = None,
        max_results: int | None = None,
    ) -> ImportPreviewSummary:
        """Fetch and inspect a URL without persisting an ImportRun."""

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
        return await self._preview_content_summary(
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
            max_results=max_results,
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
        target: ImportPreviewTarget | None = None,
        max_results: int | None = None,
    ) -> ImportRun:
        summary = await self._preview_content_summary(
            project_id=project_id,
            source=source,
            source_type=source_type,
            content=content,
            max_results=max_results,
        )
        detected_type = summary.source_type
        results = list(summary.results)
        counts = Counter(item.change for item in results)
        run_id = uuid4()
        target_binding = await self._preview_target_binding(
            project_id=project_id,
            target=target,
            results=results,
        )
        encrypted = self._secrets.encrypt(
            _encode_preview_payload(content, target_binding),
            associated_data=_preview_associated_data(run_id),
            key_reference=await active_key_reference_for_project(self._session, project_id),
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

    async def _preview_content_summary(
        self,
        *,
        project_id: UUID,
        source: ImportSourceIdentity,
        source_type: ImportSourceType,
        content: bytes,
        max_results: int | None = None,
    ) -> ImportPreviewSummary:
        try:
            detected_type, operations = parse_import_document(content, source_type)
        except CanonicalSchemaValidationError as error:
            raise _canonical_contract_error(error) from error
        except ImportDocumentError as error:
            raise AppError(code="IMPORT_INVALID", message=str(error), status_code=422) from error
        _ensure_unique_operations(operations)
        if max_results is not None and len(operations) > max_results:
            raise AppError(
                code="IMPORT_TOO_LARGE",
                message="导入文档中的接口数量超过 MCP 返回上限",
                status_code=413,
                details={"max_results": max_results},
            )
        results = await self._preview_operations(
            project_id=project_id,
            source=source,
            operations=operations,
        )
        if max_results is not None and len(results) > max_results:
            raise AppError(
                code="IMPORT_TOO_LARGE",
                message="导入预览结果超过 MCP 返回上限",
                status_code=413,
                details={"max_results": max_results},
            )
        return ImportPreviewSummary(
            source=source,
            source_type=detected_type,
            source_sha256=hashlib.sha256(content).hexdigest(),
            results=tuple(results),
        )

    async def _preview_target_binding(
        self,
        *,
        project_id: UUID,
        target: ImportPreviewTarget | None,
        results: list[ImportItemResult],
    ) -> dict[str, object] | None:
        if target is None:
            return None
        await self._validate_target_identity(
            project_id=project_id,
            service_id=target.service_id,
            environment_id=target.environment_id,
            allowed_environment_classifications=target.allowed_environment_classifications,
        )
        endpoint = None
        if target.service_id is not None and target.environment_id is not None:
            endpoint = await self._targets.find_endpoint(
                environment_id=target.environment_id,
                service_id=target.service_id,
                variant=target.endpoint_variant,
            )
            if (
                endpoint is not None
                and target.allowed_environment_classifications is not None
                and not endpoint.enabled
            ):
                raise AppError(
                    code="ENDPOINT_DISABLED",
                    message="目标 Endpoint 已停用, 不能用于 MCP 契约导入",
                    status_code=409,
                )
        server_urls = sorted({item.server_url for item in results if item.server_url is not None})
        if len(server_urls) > 1:
            raise AppError(
                code="IMPORT_TARGET_AMBIGUOUS",
                message="OpenAPI 文档包含多个 Server, 无法自动映射为单一 Endpoint",
                status_code=422,
            )
        return _target_binding_json(
            service_id=target.service_id,
            environment_id=target.environment_id,
            endpoint_variant=target.endpoint_variant,
            endpoint_id=endpoint.id if endpoint is not None else None,
            endpoint_revision=endpoint.revision if endpoint is not None else None,
            endpoint_base_url=endpoint.base_url if endpoint is not None else None,
            server_url=server_urls[0] if server_urls else None,
        )

    async def _validate_frozen_target(
        self,
        *,
        project_id: UUID,
        target: ImportPreviewTarget,
        frozen_target: dict[str, object] | None,
        results: list[ImportItemResult],
    ) -> None:
        if frozen_target is None:
            return
        current = await self._preview_target_binding(
            project_id=project_id,
            target=target,
            results=results,
        )
        if current != frozen_target:
            raise AppError(
                code="IMPORT_PREVIEW_TARGET_STALE",
                message="导入预览的 Service、Environment 或 Endpoint 已变化, 请重新生成预览",
                status_code=409,
            )

    async def _validate_target_identity(
        self,
        *,
        project_id: UUID,
        service_id: UUID | None,
        environment_id: UUID | None,
        allowed_environment_classifications: frozenset[str] | None = None,
    ) -> None:
        if service_id is None:
            if environment_id is not None:
                raise AppError(
                    code="IMPORT_TARGET_INVALID",
                    message="指定环境 Endpoint 时必须同时指定 Service",
                    status_code=422,
                )
            return
        service = await self._targets.get_service(service_id)
        if service is None or service.project_id != project_id:
            raise AppError(code="SERVICE_NOT_FOUND", message="Service 不存在", status_code=404)
        if allowed_environment_classifications is not None and not service.enabled:
            raise AppError(
                code="SERVICE_DISABLED",
                message="目标 Service 已停用, 不能用于 MCP 契约导入",
                status_code=409,
            )
        if environment_id is None:
            return
        environment = await self._session.get(Environment, environment_id)
        if (
            environment is None
            or environment.project_id != project_id
            or environment.archived_at is not None
        ):
            raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)
        if (
            allowed_environment_classifications is not None
            and environment.classification not in allowed_environment_classifications
        ):
            raise AppError(
                code="ENVIRONMENT_NOT_ALLOWED",
                message="MCP 契约导入只能绑定 test 或 sandbox 环境",
                status_code=422,
            )

    async def merge_preview(
        self,
        *,
        actor: User,
        project_id: UUID,
        run_id: UUID,
        selected_keys: set[str],
        service_id: UUID | None = None,
        environment_id: UUID | None = None,
        endpoint_variant: str = "default",
        expected_source_sha256: str | None = None,
        expected_current_versions: dict[str, int] | None = None,
        confirm_existing_changes: bool | None = None,
        allowed_environment_classifications: frozenset[str] | None = None,
        enforce_review_only: bool = False,
        commit: bool = True,
    ) -> ImportRun:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        run = await self._imports.get(run_id)
        if run is None or run.project_id != project_id:
            raise AppError(code="IMPORT_NOT_FOUND", message="导入预览不存在", status_code=404)
        if expected_source_sha256 is not None and run.source_sha256 != expected_source_sha256:
            raise AppError(
                code="IMPORT_PREVIEW_STALE",
                message="导入预览摘要与服务器记录不一致, 请重新生成预览",
                status_code=409,
            )
        if run.status != "preview":
            if enforce_review_only:
                self._reject_mcp_replay_of_existing_changes(
                    results=run.results,
                    selected_keys=selected_keys,
                )
            if set(run.applied_keys) == selected_keys:
                return run
            raise AppError(
                code="IMPORT_ALREADY_APPLIED", message="导入预览已经合并", status_code=409
            )
        content, frozen_target = self._load_preview_payload(run)
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
        await self._validate_frozen_target(
            project_id=project_id,
            target=ImportPreviewTarget(
                service_id=service_id,
                environment_id=environment_id,
                endpoint_variant=endpoint_variant,
                allowed_environment_classifications=allowed_environment_classifications,
            ),
            frozen_target=frozen_target,
            results=current,
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
        self._validate_merge_requirements(
            current=current,
            selected_keys=selected_keys,
            expected_current_versions=expected_current_versions,
            confirm_existing_changes=confirm_existing_changes,
            allow_existing_changes=not enforce_review_only,
        )
        selected_operations = tuple(
            operation for operation in operations if operation.import_key in selected_keys
        )
        await self._validate_import_target(
            actor_id=actor.id,
            project_id=project_id,
            service_id=service_id,
            environment_id=environment_id,
            operations=selected_operations,
            endpoint_variant=endpoint_variant,
            allow_existing_change=(False if enforce_review_only else confirm_existing_changes),
            allowed_environment_classifications=allowed_environment_classifications,
        )
        applied_results = await self._apply_operations(
            actor=actor,
            project_id=project_id,
            source=source,
            operations=selected_operations,
            service_id=service_id,
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
        applied_by_key = {item.import_key: item for item in applied_results}
        run.results = [applied_by_key.get(item.import_key, item).as_json() for item in current]
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
        if commit:
            await self._session.commit()
            await self._session.refresh(run)
        else:
            await self._session.flush()
        return run

    @staticmethod
    def _validate_merge_requirements(
        *,
        current: list[ImportItemResult],
        selected_keys: set[str],
        expected_current_versions: dict[str, int] | None,
        confirm_existing_changes: bool | None,
        allow_existing_changes: bool,
    ) -> None:
        existing_changes = {
            item.import_key
            for item in current
            if item.import_key in selected_keys
            and item.change in {ImportChange.CHANGED, ImportChange.DELETED}
        }
        if existing_changes and (not allow_existing_changes or confirm_existing_changes is False):
            raise AppError(
                code="IMPORT_REVIEW_REQUIRED",
                message="更新或删除已有接口必须明确确认并核对精确 Diff",
                status_code=409,
                details={"operation_keys": sorted(existing_changes)},
            )
        if expected_current_versions is None:
            return
        for item in current:
            if item.import_key not in existing_changes:
                continue
            expected = expected_current_versions.get(item.import_key)
            if expected is None or expected != item.version:
                raise AppError(
                    code="IMPORT_TARGET_VERSION_CONFLICT",
                    message="接口当前版本已变化, 请重新读取并确认目标版本",
                    status_code=409,
                    details={
                        "operation_key": item.import_key,
                        "expected_version": expected,
                        "current_version": item.version,
                    },
                )

    @staticmethod
    def _reject_mcp_replay_of_existing_changes(
        *, results: list[dict[str, object]], selected_keys: set[str]
    ) -> None:
        existing_changes = sorted(
            str(item["import_key"])
            for item in results
            if item.get("import_key") in selected_keys
            and item.get("change") in {ImportChange.CHANGED.value, ImportChange.DELETED.value}
        )
        if existing_changes:
            raise AppError(
                code="IMPORT_REVIEW_REQUIRED",
                message="已有接口变更不能通过 MCP 重放, 必须转人工审核",
                status_code=409,
                details={"operation_keys": existing_changes},
            )

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
                        server_url=operation.target_base_url,
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
        service_id: UUID | None = None,
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
                    service_id=service_id,
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
                    service_id=service_id,
                )
                change = ImportChange.CHANGED
            results.append(_result(operation, change, definition, version.version))
        return results

    async def _validate_import_target(
        self,
        *,
        actor_id: UUID,
        project_id: UUID,
        service_id: UUID | None,
        environment_id: UUID | None,
        operations: tuple[ImportedOperation, ...],
        endpoint_variant: str,
        allow_existing_change: bool | None = None,
        allowed_environment_classifications: frozenset[str] | None = None,
    ) -> None:
        if service_id is None:
            if environment_id is not None:
                raise AppError(
                    code="IMPORT_TARGET_INVALID",
                    message="指定环境 Endpoint 时必须同时指定 Service",
                    status_code=422,
                )
            return
        await self._validate_target_identity(
            project_id=project_id,
            service_id=service_id,
            environment_id=environment_id,
            allowed_environment_classifications=allowed_environment_classifications,
        )
        if environment_id is None:
            return
        environment = await self._session.get(Environment, environment_id)
        if environment is None or environment.archived_at is not None:
            raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)
        server_urls = {
            operation.target_base_url
            for operation in operations
            if operation.target_base_url is not None
        }
        if len(server_urls) > 1:
            raise AppError(
                code="IMPORT_TARGET_AMBIGUOUS",
                message="OpenAPI 文档包含多个 Server, 无法自动映射为单一 Endpoint",
                status_code=422,
            )
        await self._ensure_import_endpoint(
            actor_id=actor_id,
            project_id=project_id,
            service_id=service_id,
            environment_id=environment_id,
            endpoint_variant=endpoint_variant,
            server_url=next(iter(server_urls), None),
            allow_existing_change=allow_existing_change,
            allowed_environment_classifications=allowed_environment_classifications,
        )

    async def _ensure_import_endpoint(
        self,
        *,
        actor_id: UUID,
        project_id: UUID,
        service_id: UUID,
        environment_id: UUID,
        endpoint_variant: str,
        server_url: str | None,
        allow_existing_change: bool | None,
        allowed_environment_classifications: frozenset[str] | None = None,
    ) -> None:
        if server_url is None:
            return
        _validate_server_url(server_url)
        endpoint = await self._targets.find_endpoint(
            environment_id=environment_id,
            service_id=service_id,
            variant=endpoint_variant,
        )
        if (
            endpoint is not None
            and allowed_environment_classifications is not None
            and not endpoint.enabled
        ):
            raise AppError(
                code="ENDPOINT_DISABLED",
                message="目标 Endpoint 已停用, 不能用于 MCP 契约导入",
                status_code=409,
            )
        if endpoint is None:
            self._targets.add(
                ServiceEndpoint(
                    project_id=project_id,
                    environment_id=environment_id,
                    service_id=service_id,
                    variant=endpoint_variant,
                    base_url=server_url.rstrip("/"),
                    created_by_id=actor_id,
                )
            )
        elif endpoint.base_url != server_url.rstrip("/"):
            if allow_existing_change is False:
                raise AppError(
                    code="IMPORT_REVIEW_REQUIRED",
                    message="Endpoint 地址变化必须明确确认并核对精确 Diff",
                    status_code=409,
                    details={"endpoint_id": str(endpoint.id)},
                )
            endpoint.base_url = server_url.rstrip("/")
            endpoint.revision += 1
        await self._session.flush()

    async def _create_definition(
        self,
        *,
        actor: User,
        project_id: UUID,
        source: ImportSourceIdentity,
        operation: ImportedOperation,
        service_id: UUID | None,
    ) -> tuple[APIDefinition, APIVersion]:
        definition = APIDefinition(
            project_id=project_id,
            folder_id=None,
            service_id=service_id,
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
        version = _version_model(
            definition.id,
            definition.service_id,
            1,
            actor.id,
            operation.request,
            operation.canonical_contract,
        )
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
        service_id: UUID | None,
    ) -> tuple[APIDefinition, APIVersion]:
        definition.name = operation.name
        definition.description = operation.description
        if service_id is not None:
            definition.service_id = service_id
        definition.import_fingerprint = operation.content_fingerprint
        definition.import_source = source.name
        definition.import_source_key = source.key
        definition.is_active = True
        definition.current_version += 1
        version = _version_model(
            definition.id,
            definition.service_id,
            definition.current_version,
            actor.id,
            operation.request,
            operation.canonical_contract,
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

    def _load_preview_payload(self, run: ImportRun) -> tuple[bytes, dict[str, object] | None]:
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
        binding: dict[str, object] | None = None
        if encoded.startswith("{"):
            try:
                envelope = json.loads(encoded)
            except json.JSONDecodeError as error:
                raise AppError(
                    code="IMPORT_PREVIEW_PAYLOAD_INVALID",
                    message="导入预览内容损坏",
                    status_code=409,
                ) from error
            if not isinstance(envelope, dict) or envelope.get("format") != "s61c-v1":
                raise AppError(
                    code="IMPORT_PREVIEW_PAYLOAD_INVALID",
                    message="导入预览内容损坏",
                    status_code=409,
                )
            encoded_content = envelope.get("content")
            raw_binding = envelope.get("target")
            if not isinstance(encoded_content, str):
                raise AppError(
                    code="IMPORT_PREVIEW_PAYLOAD_INVALID",
                    message="导入预览内容损坏",
                    status_code=409,
                )
            if raw_binding is not None and not isinstance(raw_binding, dict):
                raise AppError(
                    code="IMPORT_PREVIEW_PAYLOAD_INVALID",
                    message="导入预览目标绑定损坏",
                    status_code=409,
                )
            binding = raw_binding
            encoded = encoded_content
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
        return content, binding

    def _load_preview(self, run: ImportRun) -> bytes:
        """Load a legacy or current preview payload for REST compatibility."""

        content, _ = self._load_preview_payload(run)
        return content


def _version_model(
    definition_id: UUID,
    service_id: UUID | None,
    version: int,
    actor_id: UUID,
    request: APIVersionSpec,
    contract: OperationContract | None,
) -> APIVersion:
    contract_payload = (
        contract.model_dump(mode="json", by_alias=True) if contract is not None else {}
    )
    return APIVersion(
        api_definition_id=definition_id,
        service_id=service_id,
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
        canonical_contract=contract_payload,
        contract_fingerprint=fingerprint_contract(contract) if contract is not None else None,
        contract_completeness=contract.completeness if contract is not None else "partial",
        variables=request.variables,
        created_by_id=actor_id,
    )


def _canonical_contract_error(error: CanonicalSchemaValidationError) -> AppError:
    return AppError(
        code="CANONICAL_CONTRACT_INVALID",
        message="Canonical Contract 包含非法 Schema Keyword Value",
        status_code=422,
        details={"issues": [issue.as_json() for issue in error.issues]},
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
        server_url=operation.target_base_url,
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


def _validate_server_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise AppError(
            code="IMPORT_SERVER_INVALID",
            message="OpenAPI Server 必须是无凭据的 HTTP/HTTPS 地址",
            status_code=422,
        )


def _target_binding_json(
    *,
    service_id: UUID | None,
    environment_id: UUID | None,
    endpoint_variant: str,
    endpoint_id: UUID | None,
    endpoint_revision: int | None,
    endpoint_base_url: str | None,
    server_url: str | None,
) -> dict[str, object]:
    return {
        "service_id": str(service_id) if service_id is not None else None,
        "environment_id": str(environment_id) if environment_id is not None else None,
        "endpoint_variant": endpoint_variant,
        "endpoint_id": str(endpoint_id) if endpoint_id is not None else None,
        "endpoint_revision": endpoint_revision,
        "endpoint_base_url": endpoint_base_url,
        "server_url": server_url,
    }


def _encode_preview_payload(
    content: bytes,
    target_binding: dict[str, object] | None,
) -> str:
    return json.dumps(
        {
            "format": "s61c-v1",
            "content": base64.b64encode(content).decode(),
            "target": target_binding,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _preview_associated_data(run_id: UUID) -> bytes:
    return f"flowtest:import-preview:{run_id}".encode()
