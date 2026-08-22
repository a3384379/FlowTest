"""HTTP client for the FlowTest application gateway."""

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.domain.mcp_read import MCPReadEnvelope
from app.schemas.test_design import MCPControlledWriteEnvelope


class MCPGatewayError(Exception):
    """Safe client error that never carries response bodies or credentials."""

    def __init__(self, *, code: str, status_code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message = message


class MCPReadGatewayClient:
    """Typed HTTP client shared by stdio and Streamable HTTP MCP adapters."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        client_version: str = "flowtest-mcp-s42",
    ) -> None:
        self._base_url = _validate_base_url(base_url)
        self._token = token
        self._client_version = client_version[:80] or "flowtest-mcp-s42"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> "MCPReadGatewayClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_projects(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        token: str | None = None,
        resource_uri: str | None = None,
    ) -> MCPReadEnvelope:
        return await self._get(
            "/api/v1/mcp/read/projects",
            params={"page": page, "page_size": page_size},
            token=token,
            resource_uri=resource_uri,
        )

    async def get_project(
        self,
        project_id: UUID | str,
        *,
        token: str | None = None,
        resource_uri: str | None = None,
    ) -> MCPReadEnvelope:
        return await self._get(
            f"/api/v1/mcp/read/projects/{project_id}",
            token=token,
            resource_uri=resource_uri,
        )

    async def discover_services(
        self,
        project_id: UUID | str,
        *,
        environment_id: UUID | str | None = None,
        token: str | None = None,
        resource_uri: str | None = None,
    ) -> MCPReadEnvelope:
        params = {"environment_id": str(environment_id)} if environment_id else None
        return await self._get(
            f"/api/v1/mcp/read/projects/{project_id}/services",
            params=params,
            token=token,
            resource_uri=resource_uri,
        )

    async def inspect_contract(
        self,
        project_id: UUID | str,
        *,
        api_definition_id: UUID | str | None = None,
        token: str | None = None,
        resource_uri: str | None = None,
    ) -> MCPReadEnvelope:
        params = {"api_definition_id": str(api_definition_id)} if api_definition_id else None
        return await self._get(
            f"/api/v1/mcp/read/projects/{project_id}/contracts",
            params=params,
            token=token,
            resource_uri=resource_uri,
        )

    async def inspect_workflow(
        self,
        workflow_id: UUID | str,
        *,
        token: str | None = None,
        resource_uri: str | None = None,
    ) -> MCPReadEnvelope:
        return await self._get(
            f"/api/v1/mcp/read/workflows/{workflow_id}/draft",
            token=token,
            resource_uri=resource_uri,
        )

    async def inspect_run_evidence(
        self,
        execution_id: UUID | str,
        *,
        token: str | None = None,
        resource_uri: str | None = None,
    ) -> MCPReadEnvelope:
        return await self._get(
            f"/api/v1/mcp/read/runs/{execution_id}/evidence",
            token=token,
            resource_uri=resource_uri,
        )

    async def propose_test_design(
        self,
        payload: Mapping[str, Any],
        *,
        token: str | None = None,
    ) -> MCPControlledWriteEnvelope:
        return await self._post(
            "/api/v1/mcp/write/change-sets",
            payload=payload,
            token=token,
        )

    async def _get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        token: str | None,
        resource_uri: str | None,
    ) -> MCPReadEnvelope:
        headers = {"X-MCP-Client-Version": self._client_version}
        effective_token = token or self._token
        if effective_token:
            headers["Authorization"] = f"Bearer {effective_token}"
        if resource_uri and resource_uri.startswith("flowtest://"):
            headers["X-MCP-Resource-URI"] = resource_uri[:2048]
        try:
            response = await self._client.get(path, params=params, headers=headers)
        except httpx.HTTPError as error:
            raise MCPGatewayError(
                code="MCP_GATEWAY_UNAVAILABLE",
                status_code=503,
                message="MCP 应用网关暂时不可用",
            ) from error
        if response.is_error:
            raise _gateway_error(response)
        try:
            return MCPReadEnvelope.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise MCPGatewayError(
                code="MCP_GATEWAY_INVALID_RESPONSE",
                status_code=502,
                message="MCP 应用网关返回格式无效",
            ) from error

    async def _post(
        self,
        path: str,
        *,
        payload: Mapping[str, Any],
        token: str | None,
    ) -> MCPControlledWriteEnvelope:
        headers = {
            "X-MCP-Client-Version": self._client_version,
            "Content-Type": "application/json",
        }
        effective_token = token or self._token
        if effective_token:
            headers["Authorization"] = f"Bearer {effective_token}"
        try:
            response = await self._client.post(path, json=dict(payload), headers=headers)
        except httpx.HTTPError as error:
            raise MCPGatewayError(
                code="MCP_GATEWAY_UNAVAILABLE",
                status_code=503,
                message="MCP 应用网关暂时不可用",
            ) from error
        if response.is_error:
            raise _gateway_error(response)
        try:
            return MCPControlledWriteEnvelope.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise MCPGatewayError(
                code="MCP_GATEWAY_INVALID_RESPONSE",
                status_code=502,
                message="MCP 应用网关返回格式无效",
            ) from error


def _validate_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        return value.rstrip("/")
    except (AttributeError, ValueError) as error:
        raise ValueError("MCP API Base URL 必须是无凭据的 HTTP/HTTPS 地址") from error


def _gateway_error(response: httpx.Response) -> MCPGatewayError:
    code = "MCP_GATEWAY_REQUEST_FAILED"
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        candidate = error.get("code") if isinstance(error, dict) else None
        if isinstance(candidate, str) and candidate.isidentifier():
            code = candidate[:100]
    except (ValueError, TypeError):
        pass
    message = "MCP 应用网关拒绝了请求"
    if response.status_code == 401:
        message = "MCP 服务账号认证失败"
    elif response.status_code == 403:
        message = "MCP 服务账号没有所需权限"
    elif response.status_code == 404:
        message = "MCP 资源不存在"
    return MCPGatewayError(code=code, status_code=response.status_code, message=message)
