from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel, JsonValue, ValidationError
from pydantic.json_schema import models_json_schema

from app.core.errors import AppError
from app.schemas.test_asset_packages import PackageApplyRequest, PackagePreviewRequest
from app.services.test_asset_packages import PACKAGE_MAX_BYTES


def package_request_contract(schema: type[BaseModel]) -> dict[str, JsonValue]:
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": {"$ref": f"#/components/schemas/{schema.__name__}"}}
            },
        }
    }


def install_package_openapi(application: FastAPI) -> None:
    original_openapi = application.openapi
    _, definitions = models_json_schema(
        [(PackagePreviewRequest, "validation"), (PackageApplyRequest, "validation")],
        ref_template="#/components/schemas/{model}",
    )

    def package_openapi() -> dict[str, Any]:
        document = original_openapi()
        document.setdefault("components", {}).setdefault("schemas", {}).update(definitions["$defs"])
        return document

    application.openapi = package_openapi  # type: ignore[method-assign]


async def read_package_payload[PackagePayload: BaseModel](
    request: Request, schema: type[PackagePayload]
) -> PackagePayload:
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > PACKAGE_MAX_BYTES:
            raise AppError(
                code="TEST_ASSET_PACKAGE_TOO_LARGE",
                message="导入请求超过 10 MiB, 请缩小原生包",
                status_code=413,
            )
        content.extend(chunk)
    try:
        return schema.model_validate_json(content)
    except ValidationError as error:
        raise AppError(
            code="TEST_ASSET_PACKAGE_INVALID",
            message="原生包格式不合法, 请检查格式版本、完整引用、内容指纹和运行参数",
            status_code=422,
        ) from error
