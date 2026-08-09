from dataclasses import dataclass
from typing import cast

import httpx
from pydantic import JsonValue

from app.core.config import settings
from app.core.logging import redact
from app.domain.api_assets import BodyKind
from app.engine.contracts import NodeType, RetryCategory, WorkflowNode
from app.engine.scheduler import ExecutionContext, NodeExecutionError
from app.services.api_assets import PreparedRequest
from app.services.executions import (
    PreparedMultipart,
    _redact_response_headers,
    _response_body,
    _send_request,
)


@dataclass(frozen=True, slots=True)
class PreparedWorkflowRequest:
    request: PreparedRequest
    body_kind: BodyKind
    multipart: PreparedMultipart | None


class WorkflowNodeExecutor:
    def __init__(
        self,
        client: httpx.AsyncClient,
        requests: dict[str, PreparedWorkflowRequest],
    ) -> None:
        self._client = client
        self._requests = requests

    async def execute(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        del context
        if node.type in {NodeType.START, NodeType.END}:
            return None
        if node.type is not NodeType.API:
            raise NodeExecutionError(
                code="UNSUPPORTED_NODE_TYPE",
                message=f"当前版本不支持 {node.type.value} 节点",
            )
        prepared = self._requests[node.id]
        try:
            response = await _send_request(
                self._client,
                prepared.request,
                body_kind=prepared.body_kind,
                timeout_seconds=300,
                multipart=prepared.multipart,
            )
        except httpx.TimeoutException as error:
            raise NodeExecutionError(
                code="NETWORK_TIMEOUT",
                message="目标接口请求超时",
                category=RetryCategory.NETWORK_ERROR,
            ) from error
        except httpx.HTTPError as error:
            raise NodeExecutionError(
                code="NETWORK_ERROR",
                message="无法连接目标接口",
                category=RetryCategory.NETWORK_ERROR,
            ) from error

        output = _response_output(response)
        if response.status_code >= 500:
            raise NodeExecutionError(
                code="HTTP_5XX",
                message=f"目标接口返回 {response.status_code}",
                category=RetryCategory.SERVER_ERROR,
                output=output,
            )
        if response.status_code >= 400:
            raise NodeExecutionError(
                code="HTTP_4XX",
                message=f"目标接口返回 {response.status_code}",
                output=output,
            )
        return output


def _response_output(response: httpx.Response) -> dict[str, JsonValue]:
    size_bytes = len(response.content)
    if size_bytes > settings.inline_body_limit_bytes:
        raise NodeExecutionError(
            code="WORKFLOW_RESPONSE_TOO_LARGE",
            message="工作流节点响应超过 2 MB 内联上限",
            output={
                "status_code": response.status_code,
                "size_bytes": size_bytes,
            },
        )
    return {
        "status_code": response.status_code,
        "headers": cast(JsonValue, _redact_response_headers(dict(response.headers))),
        "body": cast(JsonValue, redact(_response_body(response))),
        "size_bytes": size_bytes,
    }
