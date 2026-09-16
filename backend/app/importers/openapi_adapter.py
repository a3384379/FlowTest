"""Operation-level Swagger/OpenAPI adapters; output feeds existing contract builders."""

from __future__ import annotations

from dataclasses import dataclass

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
        result["parameters"] = [
            self.parameter(value, index, len(common)) for index, value in enumerate(parameters)
        ]
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
        for media_type, raw in content.items():
            media = mapping(raw)
            if "schema" in media:
                media["schema"] = self.normalizer.schema(
                    media["schema"], pointer(source, media_type) + "/schema", canonical
                )
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
            result[status] = response
        return result
