import json
from collections.abc import Mapping

import yaml

from app.importers.contracts import ImportedOperation, ImportSourceType
from app.importers.openapi import parse_openapi
from app.importers.postman import parse_postman


class ImportDocumentError(ValueError):
    """Raised when an imported document is unsupported or malformed."""


def parse_import_document(
    content: bytes,
    requested_type: ImportSourceType = ImportSourceType.AUTO,
) -> tuple[ImportSourceType, tuple[ImportedOperation, ...]]:
    document = _load_document(content)
    source_type = (
        _detect_source_type(document) if requested_type is ImportSourceType.AUTO else requested_type
    )
    if source_type in {ImportSourceType.OPENAPI3, ImportSourceType.SWAGGER2}:
        operations = parse_openapi(document, source_type)
    elif source_type is ImportSourceType.POSTMAN:
        operations = parse_postman(document)
    else:
        raise ImportDocumentError("不支持的导入格式")
    if not operations:
        raise ImportDocumentError("文档中没有可导入的 HTTP 接口")
    return source_type, operations


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
    raise ImportDocumentError("无法识别导入格式, 请选择 OpenAPI、Swagger 或 Postman")


def _string_key_mapping(value: Mapping[object, object]) -> Mapping[str, object]:
    if not all(isinstance(key, str) for key in value):
        raise ImportDocumentError("导入文档对象键必须是字符串")
    return {str(key): item for key, item in value.items()}
