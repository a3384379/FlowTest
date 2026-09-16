import json
from collections.abc import Mapping
from dataclasses import replace

import yaml

from app.core.redaction import (
    RedactionMode,
    RedactionPolicy,
    get_redaction_policy,
    reset_redaction_policy,
    set_redaction_policy,
)
from app.importers.contracts import ImportedOperation, ImportSourceType, sanitize_imported_json
from app.importers.excel import ExcelImportError, parse_excel
from app.importers.http_formats import HttpFormatError, parse_bruno, parse_curl, parse_har
from app.importers.openapi import parse_openapi
from app.importers.openapi_dialects import OpenAPIVersionError, source_dialect
from app.importers.openapi_normalization import OpenAPIResourceError
from app.importers.postman import parse_postman


class ImportDocumentError(ValueError):
    """Raised when an imported document is unsupported or malformed."""


def parse_import_document(
    content: bytes,
    requested_type: ImportSourceType = ImportSourceType.AUTO,
    *,
    policy: RedactionPolicy | None = None,
    document_url: str | None = None,
) -> tuple[ImportSourceType, tuple[ImportedOperation, ...]]:
    policy = policy or get_redaction_policy()
    token = set_redaction_policy(policy)
    try:
        return _parse_import_document(content, requested_type, policy, document_url)
    finally:
        reset_redaction_policy(token)


def _parse_import_document(
    content: bytes,
    requested_type: ImportSourceType,
    policy: RedactionPolicy,
    document_url: str | None,
) -> tuple[ImportSourceType, tuple[ImportedOperation, ...]]:
    if requested_type is ImportSourceType.EXCEL or (
        requested_type is ImportSourceType.AUTO and content.startswith(b"PK")
    ):
        return ImportSourceType.EXCEL, _parse_excel_document(content, policy)
    if requested_type is ImportSourceType.CURL or (
        requested_type is ImportSourceType.AUTO and content.lstrip().lower().startswith(b"curl ")
    ):
        return ImportSourceType.CURL, _parse_curl_document(content, policy)
    document = _load_document_or_none(content, requested_type)
    source_type = (
        _detect_source_type(document) if requested_type is ImportSourceType.AUTO else requested_type
    )
    _validate_openapi_format(document, source_type)
    return source_type, _non_empty(
        _parse_mapping_operations(source_type, content, document, document_url), policy
    )


def _parse_excel_document(content: bytes, policy: RedactionPolicy) -> tuple[ImportedOperation, ...]:
    try:
        return _non_empty(parse_excel(content), policy)
    except ExcelImportError as error:
        raise ImportDocumentError(str(error)) from error


def _parse_curl_document(content: bytes, policy: RedactionPolicy) -> tuple[ImportedOperation, ...]:
    try:
        return _non_empty(parse_curl(content), policy)
    except HttpFormatError as error:
        raise ImportDocumentError(str(error)) from error


def _parse_mapping_operations(
    source_type: ImportSourceType,
    content: bytes,
    document: Mapping[str, object],
    document_url: str | None = None,
) -> tuple[ImportedOperation, ...]:
    if source_type in {ImportSourceType.OPENAPI3, ImportSourceType.SWAGGER2}:
        try:
            return parse_openapi(document, source_type, document_url=document_url)
        except OpenAPIResourceError as error:
            raise ImportDocumentError(str(error)) from error
    if source_type is ImportSourceType.POSTMAN:
        return parse_postman(document)
    try:
        if source_type is ImportSourceType.HAR:
            return parse_har(document)
        if source_type is ImportSourceType.BRUNO:
            return parse_bruno(content, document)
    except HttpFormatError as error:
        raise ImportDocumentError(str(error)) from error
    raise ImportDocumentError("不支持的导入格式")


def _non_empty(
    operations: tuple[ImportedOperation, ...], policy: RedactionPolicy
) -> tuple[ImportedOperation, ...]:
    if not operations:
        raise ImportDocumentError("文档中没有可导入的 HTTP 接口")
    if policy.mode is RedactionMode.OFF:
        return operations
    return tuple(
        replace(
            operation,
            request=replace(
                operation.request,
                body=sanitize_imported_json(operation.request.body),
            ),
        )
        for operation in operations
    )


def _load_document_or_none(
    content: bytes, requested_type: ImportSourceType
) -> Mapping[str, object]:
    if requested_type is ImportSourceType.BRUNO:
        try:
            return _load_document(content)
        except ImportDocumentError:
            return {}
    return _load_document(content)


def _load_document(content: bytes) -> Mapping[str, object]:
    if len(content) > 32 * 1024 * 1024:
        raise ImportDocumentError("文档超过 32 MiB 解析预算")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ImportDocumentError("导入文件必须使用 UTF-8 编码") from error
    try:
        loaded = json.loads(text)
    except RecursionError as error:
        raise ImportDocumentError("文档超过解析深度预算") from error
    except json.JSONDecodeError:
        try:
            loaded = yaml.safe_load(text)
        except (yaml.YAMLError, RecursionError) as error:
            raise ImportDocumentError("导入文件不是有效的 JSON 或 YAML") from error
    if not isinstance(loaded, Mapping):
        raise ImportDocumentError("导入文档根节点必须是对象")
    _check_source_budget(loaded)
    return _string_key_mapping(loaded)


def _detect_source_type(document: Mapping[str, object]) -> ImportSourceType:
    if any(key in document for key in ("openapi", "swagger", "swaggerVersion")):
        return _openapi_format(document)
    info = document.get("info")
    if isinstance(info, Mapping) and "schema" in info and "item" in document:
        return ImportSourceType.POSTMAN
    log = document.get("log")
    if isinstance(log, Mapping) and "entries" in log:
        return ImportSourceType.HAR
    if document.get("bruno") or (document.get("version") == "1" and "items" in document):
        return ImportSourceType.BRUNO
    raise ImportDocumentError(
        "无法识别导入格式, 请选择 OpenAPI、Swagger、Postman、HAR、cURL、Bruno 或 Excel"
    )


def _string_key_mapping(value: Mapping[object, object]) -> Mapping[str, object]:
    if not all(isinstance(key, str) for key in value):
        raise ImportDocumentError("导入文档对象键必须是字符串")
    return {str(key): item for key, item in value.items()}


def _check_source_budget(value: object) -> None:
    pending: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > 200_000 or depth > 96:
            raise ImportDocumentError("文档超过 200000 节点或 96 层嵌套预算 (包括 YAML 循环别名)")
        if isinstance(current, dict):
            pending.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            pending.extend((child, depth + 1) for child in current)


def _openapi_format(document: Mapping[str, object]) -> ImportSourceType:
    try:
        dialect = source_dialect(document)
    except OpenAPIVersionError as error:
        raise ImportDocumentError(str(error)) from error
    return ImportSourceType.SWAGGER2 if dialect == "SWAGGER_2_0" else ImportSourceType.OPENAPI3


def _validate_openapi_format(document: Mapping[str, object], selected: ImportSourceType) -> None:
    is_openapi = selected in {ImportSourceType.SWAGGER2, ImportSourceType.OPENAPI3} or any(
        key in document for key in ("swagger", "swaggerVersion", "openapi")
    )
    if is_openapi and _openapi_format(document) != selected:
        raise ImportDocumentError("选择的导入格式与文档规范版本不一致")
