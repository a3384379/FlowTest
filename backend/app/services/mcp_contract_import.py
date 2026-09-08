# ruff: noqa: RUF001

"""MCP adapter for the governed S61C contract import lifecycle."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.context import get_tenant_context, get_trace_id
from app.core.errors import AppError
from app.importers.contracts import ImportChange, ImportSourceType, is_sensitive_import_name
from app.importers.sources import ImportDocumentFetcher
from app.models.access import User
from app.models.imports import ImportRun
from app.models.organizations import ServiceAccount
from app.schemas.mcp_contract_import import (
    MCP_CONTRACT_IMPORT_SCOPE,
    MCPCommitContractImportRequest,
    MCPCommitContractImportResponse,
    MCPContractImportItem,
    MCPContractOperation,
    MCPPreviewContractImportRequest,
    MCPPreviewContractImportResponse,
)
from app.services.idempotency import IdempotencyService
from app.services.imports import (
    ImportItemResult,
    ImportPreviewSummary,
    ImportPreviewTarget,
    ImportService,
)
from app.services.projects import ProjectService

MAX_OPERATIONS = 100
MAX_RESPONSE_ITEMS = 200
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
_COMMIT_OPERATION = "mcp.commit_contract_import"


class MCPContractImportService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        document_fetcher: ImportDocumentFetcher | None = None,
    ) -> None:
        self._session = session
        self._fetcher = document_fetcher

    async def preview(
        self,
        *,
        actor: User,
        account: ServiceAccount,
        payload: MCPPreviewContractImportRequest,
    ) -> MCPPreviewContractImportResponse:
        organization_id = _require_scope(account)
        importer = ImportService(self._session, document_fetcher=self._fetcher)
        target = (
            ImportPreviewTarget(
                service_id=payload.service_id,
                environment_id=payload.environment_id,
                endpoint_variant=payload.endpoint_variant,
            )
            if payload.persist
            else None
        )
        if payload.source_kind == "url":
            if payload.source_url is None:
                raise AppError(code="IMPORT_INVALID", message="契约地址不能为空", status_code=422)
            source_url = str(payload.source_url)
            try:
                summary = (
                    await importer.preview_url(
                        actor=actor,
                        project_id=payload.project_id,
                        url=source_url,
                        source_type=payload.source_type,
                        maximum_bytes=min(settings.artifact_limit_bytes, MAX_DOCUMENT_BYTES),
                        document_id=payload.document_id,
                        target=target,
                        max_results=MAX_RESPONSE_ITEMS,
                    )
                    if payload.persist
                    else await importer.preview_url_dry_run(
                        actor=actor,
                        project_id=payload.project_id,
                        url=source_url,
                        source_type=payload.source_type,
                        maximum_bytes=min(settings.artifact_limit_bytes, MAX_DOCUMENT_BYTES),
                        document_id=payload.document_id,
                        max_results=MAX_RESPONSE_ITEMS,
                    )
                )
            except AppError as error:
                raise _network_approval_error(error) from error
            return _preview_response(
                organization_id=organization_id,
                project_id=payload.project_id,
                summary=summary,
                persisted=payload.persist,
                preview_id=summary.id if hasattr(summary, "id") else None,
                target_service_id=payload.service_id,
                target_environment_id=payload.environment_id,
            )

        if payload.source_kind == "document":
            if payload.document_content is None:
                raise AppError(code="IMPORT_INVALID", message="契约文档不能为空", status_code=422)
            content = payload.document_content.encode("utf-8")
            if len(content) > MAX_DOCUMENT_BYTES:
                raise AppError(
                    code="IMPORT_TOO_LARGE", message="契约文档超过大小上限", status_code=413
                )
            source_name = payload.document_name or "contract-document"
            summary = (
                await importer.preview_document(
                    actor=actor,
                    project_id=payload.project_id,
                    source_name=source_name,
                    source_type=payload.source_type,
                    content=content,
                    target=target,
                    max_results=MAX_RESPONSE_ITEMS,
                )
                if payload.persist
                else await importer.preview_document_dry_run(
                    actor=actor,
                    project_id=payload.project_id,
                    source_name=source_name,
                    source_type=payload.source_type,
                    content=content,
                    max_results=MAX_RESPONSE_ITEMS,
                )
            )
            return _preview_response(
                organization_id=organization_id,
                project_id=payload.project_id,
                summary=summary,
                persisted=payload.persist,
                preview_id=summary.id if hasattr(summary, "id") else None,
                target_service_id=payload.service_id,
                target_environment_id=payload.environment_id,
            )

        content = _operations_document(payload.operations)
        summary = (
            await importer.preview_document(
                actor=actor,
                project_id=payload.project_id,
                source_name="source-derived/inferred.json",
                source_type=ImportSourceType.OPENAPI3,
                content=content,
                target=target,
                max_results=MAX_RESPONSE_ITEMS,
            )
            if payload.persist
            else await importer.preview_document_dry_run(
                actor=actor,
                project_id=payload.project_id,
                source_name="source-derived/inferred.json",
                source_type=ImportSourceType.OPENAPI3,
                content=content,
                max_results=MAX_RESPONSE_ITEMS,
            )
        )
        return _preview_response(
            organization_id=organization_id,
            project_id=payload.project_id,
            summary=summary,
            persisted=payload.persist,
            preview_id=summary.id if hasattr(summary, "id") else None,
            target_service_id=payload.service_id,
            target_environment_id=payload.environment_id,
        )

    async def commit(
        self,
        *,
        actor: User,
        account: ServiceAccount,
        payload: MCPCommitContractImportRequest,
        idempotency_key: str,
    ) -> MCPCommitContractImportResponse:
        organization_id = _require_scope(account)
        await ProjectService(self._session).authorize(
            actor=actor,
            project_id=payload.project_id,
            editing=True,
        )
        request_payload = payload.model_dump(mode="json")

        async def action() -> MCPCommitContractImportResponse:
            run = await ImportService(self._session).merge_preview(
                actor=actor,
                project_id=payload.project_id,
                run_id=payload.preview_id,
                selected_keys=set(payload.selected_operations),
                service_id=payload.service_id,
                environment_id=payload.environment_id,
                endpoint_variant=payload.endpoint_variant,
                expected_source_sha256=payload.preview_sha256.lower(),
                expected_current_versions=payload.expected_current_versions,
                confirm_existing_changes=payload.confirm_existing_changes,
            )
            return _commit_response(
                organization_id=organization_id,
                run=run,
            )

        result = await IdempotencyService(self._session).run(
            key=idempotency_key,
            project_id=payload.project_id,
            actor_key=f"service-account:{account.id}",
            operation=_COMMIT_OPERATION,
            request_payload=request_payload,
            action=action,
        )
        return MCPCommitContractImportResponse.model_validate(result)


def _require_scope(account: ServiceAccount) -> UUID:
    context = get_tenant_context()
    if (
        context is None
        or context.service_account_id != account.id
        or context.organization_id != account.organization_id
    ):
        raise AppError(
            code="MCP_AUTHENTICATION_REQUIRED", message="MCP 需要有效服务账号", status_code=401
        )
    if MCP_CONTRACT_IMPORT_SCOPE not in context.scopes:
        raise AppError(
            code="MCP_SCOPE_REQUIRED", message="服务账号缺少契约导入权限范围", status_code=403
        )
    return context.organization_id


def _preview_response(
    *,
    organization_id: UUID,
    project_id: UUID,
    summary: ImportPreviewSummary | Any,
    persisted: bool,
    preview_id: UUID | None,
    target_service_id: UUID | None,
    target_environment_id: UUID | None,
) -> MCPPreviewContractImportResponse:
    if isinstance(summary, ImportPreviewSummary):
        source_kind = summary.source.kind.value
        source_type = summary.source_type
        source_name = summary.source.name
        source_url = summary.source.url
        document_url = summary.source.document_url
        source_sha256 = summary.source_sha256
        results: list[MCPContractImportItem | ImportItemResult] = list(summary.results)
    else:
        source_kind = str(summary.source_kind)
        source_type = ImportSourceType(summary.source_type)
        source_name = summary.source_name
        source_url = summary.source_url
        document_url = summary.document_url
        source_sha256 = summary.source_sha256
        results = [_item_from_json(item) for item in summary.results]
    counts = {
        change: sum(_change_value(item.change) == change.value for item in results)
        for change in ImportChange
    }
    return MCPPreviewContractImportResponse(
        organization_id=organization_id,
        project_id=project_id,
        persisted=persisted,
        preview_id=preview_id,
        source_kind=source_kind,
        source_type=source_type,
        source_name=source_name,
        source_url=source_url,
        document_url=document_url,
        source_sha256=source_sha256,
        items=[
            _item_from_result(item) if isinstance(item, ImportItemResult) else item
            for item in results
        ],
        added=counts[ImportChange.ADDED],
        changed=counts[ImportChange.CHANGED],
        deleted=counts[ImportChange.DELETED],
        unchanged=counts[ImportChange.UNCHANGED],
        target_service_id=target_service_id,
        target_environment_id=target_environment_id,
        target_fingerprint=_target_fingerprint(results),
        warnings=["持久化预览会创建 ImportRun；提交时必须使用同一 preview_id 和 source_sha256。"]
        if persisted
        else ["这是纯 dry-run，未创建 ImportRun，也未修改接口资产。"],
        trace_id=get_trace_id(),
        next_action="commit"
        if any(_change_value(item.change) != ImportChange.UNCHANGED.value for item in results)
        else "none",
    )


def _item_from_result(item: ImportItemResult) -> MCPContractImportItem:
    return MCPContractImportItem(
        import_key=item.import_key,
        name=item.name,
        method=item.method,
        path=item.path,
        change=item.change.value,
        definition_id=item.definition_id,
        version=item.version,
        server_url=item.server_url,
    )


def _item_from_json(value: dict[str, Any]) -> MCPContractImportItem:
    return MCPContractImportItem.model_validate(value)


def _commit_response(
    *,
    organization_id: UUID,
    run: ImportRun,
) -> MCPCommitContractImportResponse:
    items = [_item_from_json(item) for item in run.results]
    return MCPCommitContractImportResponse(
        organization_id=organization_id,
        project_id=run.project_id,
        import_run_id=run.id,
        status="applied",
        applied_keys=list(run.applied_keys),
        created_definition_ids=[
            item.definition_id
            for item in items
            if item.definition_id is not None and item.change == ImportChange.ADDED.value
        ],
        changed_definition_ids=[
            item.definition_id
            for item in items
            if item.definition_id is not None and item.change == ImportChange.CHANGED.value
        ],
        deleted_definition_ids=[
            item.definition_id
            for item in items
            if item.definition_id is not None and item.change == ImportChange.DELETED.value
        ],
        source_sha256=run.source_sha256,
        results=items,
        trace_id=get_trace_id(),
    )


def _change_value(value: ImportChange | str) -> str:
    return value.value if isinstance(value, ImportChange) else value


def _target_fingerprint(items: list[MCPContractImportItem | ImportItemResult]) -> str:
    values = []
    for item in items:
        values.append(
            (
                item.import_key,
                str(item.definition_id) if item.definition_id is not None else None,
                item.version,
            )
        )
    return hashlib.sha256(json.dumps(sorted(values), separators=(",", ":")).encode()).hexdigest()


def _network_approval_error(error: AppError) -> AppError:
    if error.code != "OUTBOUND_REQUEST_BLOCKED":
        return error
    return AppError(
        code="NETWORK_APPROVAL_REQUIRED",
        message="目标地址尚未获得项目网络批准",
        status_code=403,
        details={"original_code": error.code},
    )


def _operations_document(operations: list[MCPContractOperation]) -> bytes:
    if not operations or len(operations) > MAX_OPERATIONS:
        raise AppError(code="IMPORT_INVALID", message="强类型接口数量超出范围", status_code=422)
    servers = _operation_servers(operations)
    if len(servers) > 1:
        raise AppError(
            code="IMPORT_TARGET_AMBIGUOUS", message="接口包含多个目标地址", status_code=422
        )
    paths: dict[str, dict[str, Any]] = {}
    operation_keys: set[tuple[str, str]] = set()
    for operation in operations:
        operation_key = (operation.method.value, operation.path)
        if operation_key in operation_keys:
            raise AppError(
                code="IMPORT_DUPLICATE_OPERATION",
                message="强类型接口中包含重复的方法和路径",
                status_code=422,
                details={"method": operation.method.value, "path": operation.path},
            )
        operation_keys.add(operation_key)
        method = operation.method.value.lower()
        paths.setdefault(operation.path, {})[method] = _operation_document_entry(operation)
    document: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {"title": "Source-derived contract", "version": "1"},
        "paths": paths,
    }
    if servers:
        document["servers"] = [{"url": next(iter(servers))}]
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _operation_servers(operations: list[MCPContractOperation]) -> set[str]:
    return {
        str(operation.target_base_url).rstrip("/")
        for operation in operations
        if operation.target_base_url is not None
    }


def _operation_document_entry(operation: MCPContractOperation) -> dict[str, Any]:
    for parameter in operation.parameters:
        if is_sensitive_import_name(parameter.name):
            raise AppError(
                code="IMPORT_SENSITIVE_INPUT",
                message="强类型接口不能携带认证或敏感参数值",
                status_code=422,
            )
        _validate_structural_schema(parameter.schema_)
    if operation.request_body is not None:
        _validate_structural_schema(operation.request_body.schema_)
    for response in operation.responses.values():
        if response.schema_ is not None:
            _validate_structural_schema(response.schema_)
    entry: dict[str, Any] = {
        "operationId": operation.name,
        "description": operation.description,
        "parameters": [
            {
                "name": parameter.name,
                "in": parameter.location,
                "required": parameter.required,
                "schema": parameter.schema_,
            }
            for parameter in operation.parameters
        ],
        "responses": _operation_responses(operation),
    }
    if operation.request_body is not None:
        entry["requestBody"] = {
            "required": operation.request_body.required,
            "content": {
                operation.request_body.content_type: {"schema": operation.request_body.schema_}
            },
        }
    return entry


def _operation_responses(operation: MCPContractOperation) -> dict[str, Any]:
    responses = {
        status: {
            "description": response.description or "Response",
            **(
                {
                    "content": {
                        response.content_type or "application/json": {
                            "schema": response.schema_ or {}
                        }
                    }
                }
                if response.content_type is not None or response.schema_ is not None
                else {}
            ),
        }
        for status, response in operation.responses.items()
    }
    return responses or {"200": {"description": "OK"}}


def _validate_structural_schema(value: object, *, depth: int = 0) -> None:
    if depth > 8:
        raise AppError(code="IMPORT_INVALID", message="接口 Schema 嵌套过深", status_code=422)
    if isinstance(value, dict):
        if len(value) > 80:
            raise AppError(code="IMPORT_TOO_LARGE", message="接口 Schema 字段过多", status_code=413)
        for key, item in value.items():
            if key.lower() in {"example", "examples", "default"}:
                raise AppError(
                    code="IMPORT_SENSITIVE_INPUT",
                    message="强类型接口不能携带请求或响应示例值",
                    status_code=422,
                )
            if (
                is_sensitive_import_name(key)
                and isinstance(item, str)
                and not item.startswith("secret://")
            ):
                raise AppError(
                    code="IMPORT_SENSITIVE_INPUT",
                    message="强类型接口不能携带敏感字段值",
                    status_code=422,
                )
            _validate_structural_schema(item, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 100:
            raise AppError(code="IMPORT_TOO_LARGE", message="接口 Schema 列表过长", status_code=413)
        for item in value:
            _validate_structural_schema(item, depth=depth + 1)
