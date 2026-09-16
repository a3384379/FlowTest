"""Operation-level Swagger/OpenAPI adapters; output feeds existing contract builders."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.parameter_identity import parameter_identity
from app.importers.openapi_normalization import (
    SCHEMA_KEYS,
    SourceNormalizer,
    mapping,
    pointer,
    sequence,
)


@dataclass(slots=True)
class OperationAdapter:
    normalizer: SourceNormalizer
    source: str

    def prepare(self, operation: dict[str, object], common: list[object]) -> dict[str, object]:
        result = dict(operation)
        parameters = common + sequence(operation.get("parameters"))
        adapted = [
            self.parameter(value, index, len(common)) for index, value in enumerate(parameters)
        ]
        result["parameters"] = self.effective_parameters(adapted)
        self.capabilities(operation)
        result["consumes"] = operation.get("consumes", self.normalizer.document.get("consumes", []))
        if "requestBody" in operation:
            body, origin, _ = self.normalizer.resolve(
                operation["requestBody"], self.source + "/requestBody", "$.request_body"
            )
            body["content"] = self.content(
                body.get("content"), origin + "/content", "$.request_body.schema"
            )
            result["requestBody"] = body
        result["responses"] = self.responses(operation.get("responses"))
        for media_type in sequence(result["consumes"]):
            self.media_capabilities(
                str(media_type), {}, self.source + "/consumes", "$.request_body"
            )
        if self.normalizer.method == "GET" and (
            "requestBody" in result
            or any(mapping(p).get("in") == "body" for p in sequence(result["parameters"]))
        ):
            self.normalizer.warn(
                self.source,
                "$.request_body",
                "requestBody",
                "GET_WITH_BODY",
                "保留 GET 请求体; 目标服务或代理可能不支持",
            )
        if not result["consumes"] and any(
            mapping(p).get("in") in {"body", "formData"} for p in sequence(result["parameters"])
        ):
            self.normalizer.warn(
                self.source + "/consumes",
                "$.request_body.content_type",
                "consumes",
                "CONTENT_TYPE_DEFAULTED",
                "根据 body/formData/file 使用 JSON、URL 编码表单或 multipart 默认值",
            )
        return result

    def parameter(self, value: object, index: int, common_count: int) -> dict[str, object]:
        source = (
            pointer("#/paths", self.normalizer.endpoint) + "/parameters/" + str(index)
            if index < common_count
            else self.source + "/parameters/" + str(index - common_count)
        )
        canonical = f"$.parameters[{index}].schema"
        parameter, source, _ = self.normalizer.resolve(value, source, canonical)
        location = parameter.get("in")
        if location == "body":
            canonical = "$.request_body.schema"
        if location == "formData":
            canonical = "$.request_body.schema.properties." + str(parameter.get("name", ""))
        if "schema" in parameter:
            parameter["schema"] = self.normalizer.schema(
                parameter["schema"], source + "/schema", canonical
            )
        elif self.normalizer.dialect == "SWAGGER_2_0":
            schema = self.normalizer.schema(
                {
                    key: item
                    for key, item in parameter.items()
                    if key in SCHEMA_KEYS and key != "required"
                },
                source,
                canonical,
            )
            parameter.update(schema)
            parameter["schema"] = schema
        self.serialization(parameter, source, canonical)
        query_schema = mapping(parameter.get("schema"))
        if location == "query" and (
            query_schema.get("type") == "object"
            or mapping(query_schema.get("items")).get("type") in {"object", "array"}
        ):
            self.normalizer.warn(
                source,
                canonical,
                "style",
                "QUERY_REQUIRES_CONFIGURATION",
                "复杂 query 对象序列化需人工配置",
                loss=True,
            )
        if (
            location == "path"
            and "{" + str(parameter.get("name")) + "}" not in self.normalizer.endpoint
        ):
            self.normalizer.warn(
                source,
                canonical,
                "in",
                "PATH_PARAMETER_MISMATCH",
                "保留参数声明; 路径模板没有匹配占位符",
                loss=True,
            )
        return parameter

    def serialization(self, parameter: dict[str, object], source: str, canonical: str) -> None:
        if self.normalizer.dialect != "SWAGGER_2_0" or parameter.get("type") != "array":
            return
        collection = parameter.get("collectionFormat", "csv")
        location = parameter.get("in")
        styles = {
            "csv": "form" if location in {"query", "formData"} else "simple",
            "multi": "form",
            "ssv": "spaceDelimited",
            "pipes": "pipeDelimited",
            "tsv": "tabDelimited",
        }
        if collection in styles:
            parameter["style"] = styles[str(collection)]
            parameter["explode"] = collection == "multi"
        if collection == "tsv":
            self.normalizer.warn(
                source + "/collectionFormat",
                canonical,
                "collectionFormat",
                "COLLECTION_FORMAT_COMPATIBILITY",
                "tabDelimited 兼容样式; 使用制表符分隔数组, 非 OpenAPI 标准 style",
            )

    def content(self, value: object, source: str, canonical: str) -> dict[str, object]:
        content = mapping(value)
        result: dict[str, object] = {}
        if len(content) > 1:
            self.normalizer.warn(
                source,
                canonical,
                "content",
                "MULTIPLE_MEDIA_TYPES",
                "Canonical 选择首个优先 JSON 的媒体类型; 其他类型保留在源文档",
                loss=True,
            )
        for media_type in sorted(content, key=lambda name: ("json" not in name, name)):
            raw = content[media_type]
            media = mapping(raw)
            if "schema" in media:
                media["schema"] = self.normalizer.schema(
                    media["schema"], pointer(source, media_type) + "/schema", canonical
                )
            self.media_capabilities(media_type, media, pointer(source, media_type), canonical)
            result[media_type] = media
        return result

    def responses(self, value: object) -> dict[str, object]:
        result: dict[str, object] = {}
        for status, raw_response in mapping(value).items():
            canonical = "$.responses." + status + ".schema"
            response, source, _ = self.normalizer.resolve(
                raw_response, self.source + "/responses/" + status, canonical
            )
            if "schema" in response:
                response["schema"] = self.normalizer.schema(
                    response["schema"], source + "/schema", canonical
                )
            if "content" in response:
                response["content"] = self.content(
                    response["content"], source + "/content", canonical
                )
            if re.fullmatch(r"[1-5][0-9]{2}|default", status) is None:
                self.normalizer.warn(
                    source,
                    canonical,
                    "responses",
                    "RESPONSE_RANGE_UNSUPPORTED",
                    "响应范围保留在源文档; 不推断具体状态码",
                    loss=True,
                )
            result[status] = response
        return result

    def effective_parameters(self, parameters: list[dict[str, object]]) -> list[object]:
        effective: dict[tuple[str, str], object] = {}
        for parameter in parameters:
            key = parameter_identity(str(parameter.get("in", "")), str(parameter.get("name", "")))
            effective[key] = parameter
        return list(effective.values())

    def capabilities(self, operation: dict[str, object]) -> None:
        if not mapping(self.normalizer.document.get("info")).get("version"):
            self.normalizer.warn(
                "#/info/version",
                "$.revision",
                "version",
                "INFO_VERSION_MISSING",
                "未声明文档业务版本; 不推断版本",
            )
        for keyword in ("callbacks",):
            if operation.get(keyword):
                self.normalizer.warn(
                    self.source + "/" + keyword,
                    "$",
                    keyword,
                    "OPERATION_CAPABILITY_UNSUPPORTED",
                    "保留在源文档; 未生成回调执行步骤",
                    loss=True,
                )
        for keyword in ("webhooks", "jsonSchemaDialect"):
            if self.normalizer.document.get(keyword):
                self.normalizer.warn(
                    "#/" + keyword,
                    "$",
                    keyword,
                    "DOCUMENT_CAPABILITY_PARTIAL",
                    "未完整实现此文档级能力; 请核对源文档",
                    loss=True,
                )

    def media_capabilities(
        self, media_type: str, media: dict[str, object], source: str, canonical: str
    ) -> None:
        supported = (
            media_type
            in {"application/json", "application/x-www-form-urlencoded", "multipart/form-data"}
            or media_type.endswith("+json")
            or media_type.startswith("text/")
        )
        if not supported or media.get("encoding"):
            self.normalizer.warn(
                source,
                canonical,
                "encoding" if media.get("encoding") else "content",
                "MEDIA_REQUIRES_CONFIGURATION",
                "媒体类型或 encoding 尚未完整执行; 需人工配置",
                loss=True,
            )
        if media_type != "multipart/form-data":
            return
        for name, raw in mapping(mapping(media.get("schema")).get("properties")).items():
            schema = mapping(raw)
            if schema.get("format") == "binary":
                self.normalizer.warn(
                    pointer(source + "/schema/properties", name),
                    canonical,
                    "format",
                    "FILE_REQUIRES_CONFIGURATION",
                    "文件字段结构已导入; 执行前需显式绑定上传文件, 不读取示例路径",
                )
            if schema.get("type") == "array":
                self.normalizer.warn(
                    pointer(source + "/schema/properties", name),
                    canonical,
                    "items",
                    "MULTIPART_ARRAY_UNSUPPORTED",
                    "multipart 数组需人工配置",
                    loss=True,
                )
