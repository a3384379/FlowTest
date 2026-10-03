from fastapi import Request
from pydantic import BaseModel, ValidationError

from app.core.errors import AppError
from app.services.test_asset_packages import PACKAGE_MAX_BYTES


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
