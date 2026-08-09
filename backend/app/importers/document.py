import json
from collections.abc import Mapping
from dataclasses import replace

import yaml

from app.importers.contracts import ImportedOperation, ImportSourceType, sanitize_imported_json
from app.importers.excel import ExcelImportError, parse_excel
from app.importers.http_formats import HttpFormatError, parse_bruno, parse_curl, parse_har
from app.importers.openapi import parse_openapi
from app.importers.postman import parse_postman


class ImportDocumentError(ValueError):
    """Raised when an imported document is unsupported or malformed."""


def parse_import_document(
    content: bytes,
    requested_type: ImportSourceType = ImportSourceType.AUTO,
) -> tuple[ImportSourceType, tuple[ImportedOperation, ...]]:
    if requested_type is ImportSourceType.EXCEL or (
        requested_type is ImportSourceType.AUTO and content.startswith(b"PK")
    ):
        return ImportSourceType.EXCEL, _parse_excel_document(content)
    if requested_type is ImportSourceType.CURL or (
        requested_type is ImportSourceType.AUTO and content.lstrip().lower().startswith(b"curl ")
    ):
        return ImportSourceType.CURL, _parse_curl_document(content)
    document = _load_document_or_none(content, requested_type)
    source_type = (
        _detect_source_type(document) if requested_type is ImportSourceType.AUTO else requested_type
    )
    return source_type, _non_empty(_parse_mapping_operations(source_type, content, document))


def _parse_excel_document(content: bytes) -> tuple[ImportedOperation, ...]:
    try:
        return _non_empty(parse_excel(content))
    except ExcelImportError as error:
        raise ImportDocumentError(str(error)) from error


def _parse_curl_document(content: bytes) -> tuple[ImportedOperation, ...]:
    try:
        return _non_empty(parse_curl(content))
    except HttpFormatError as error:
        raise ImportDocumentError(str(error)) from error


def _parse_mapping_operations(
    source_type: ImportSourceType,
    content: bytes,
    document: Mapping[str, object],
) -> tuple[ImportedOperation, ...]:
    if source_type in {ImportSourceType.OPENAPI3, ImportSourceType.SWAGGER2}:
        return parse_openapi(document, source_type)
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


def _non_empty(operations: tuple[ImportedOperation, ...]) -> tuple[ImportedOperation, ...]:
    if not operations:
        raise ImportDocumentError("文档中没有可导入的 HTTP 接口")
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
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ImportDocumentError("导入文件必须使用 UTF-8 编码") from error
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise ImportDocumentError("导入文件不是有效的 JSON 或 YAML") from error
    if not isinstance(loaded, Mapping):
        raise ImportDocumentError("导入文档根节点必须是对象")
    return _string_key_mapping(loaded)


def _detect_source_type(document: Mapping[str, object]) -> ImportSourceType:
    openapi = document.get("openapi")
    if isinstance(openapi, str) and openapi.startswith("3."):
        return ImportSourceType.OPENAPI3
    if document.get("swagger") == "2.0":
        return ImportSourceType.SWAGGER2
    info = document.get("info")
    if isinstance(info, Mapping) and "schema" in info and "item" in document:
        return ImportSourceType.POSTMAN
    log = document.get("log")
    if isinstance(log, Mapping) and "entries" in log:
        return ImportSourceType.HAR
    if document.get("bruno"):
        return ImportSourceType.BRUNO
    raise ImportDocumentError(
        "无法识别导入格式, 请选择 OpenAPI、Swagger、Postman、HAR、cURL、Bruno 或 Excel"
    )


def _string_key_mapping(value: Mapping[object, object]) -> Mapping[str, object]:
    if not all(isinstance(key, str) for key in value):
        raise ImportDocumentError("导入文档对象键必须是字符串")
    return {str(key): item for key, item in value.items()}
