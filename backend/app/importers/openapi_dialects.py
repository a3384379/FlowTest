"""Version-family dispatch independent of the persisted import format enum."""

import re
from collections.abc import Mapping


class OpenAPIVersionError(ValueError):
    pass


def source_dialect(document: Mapping[str, object]) -> str:
    swagger = document.get("swaggerVersion", document.get("swagger"))
    if str(swagger).startswith("1."):
        raise OpenAPIVersionError(
            "Legacy Swagger 1.x is not currently supported; "
            "please convert to Swagger 2.0 or OpenAPI 3.x."
        )
    if swagger == "2.0" and "openapi" not in document:
        return "SWAGGER_2_0"
    version = document.get("openapi")
    if swagger is None and isinstance(version, str) and re.fullmatch(r"3\.[012]\.\d+", version):
        return "OPENAPI_" + version[:3].replace(".", "_")
    raise OpenAPIVersionError(
        "不支持或冲突的规范版本, 请选择 Swagger 2.0 或 OpenAPI 3.0/3.1/3.2 文档"
    )
