import json
from urllib.parse import quote

import httpx
from pydantic import JsonValue

from app.core.errors import AppError
from app.domain.contract_hub import (
    MAX_PACT_BYTES,
    PactBrokerSource,
    PactDocument,
    PactTransportError,
    ProviderInteractionResult,
    ProviderInteractionVerifier,
    ProviderVerificationEvidence,
    normalize_contract_origin,
    response_mismatch_codes,
)
from app.domain.network import OutboundNetworkPolicy
from app.services.outbound import OutboundRequestGuard

MAX_PROVIDER_RESPONSE_BYTES = 2 * 1024 * 1024


class HttpProviderInteractionVerifier(ProviderInteractionVerifier):
    def __init__(
        self,
        *,
        request_timeout_seconds: float,
        guard: OutboundRequestGuard | None = None,
    ) -> None:
        self._timeout = request_timeout_seconds
        self._guard = guard or OutboundRequestGuard()

    async def verify(
        self,
        *,
        target_base_url: str,
        pact: PactDocument,
        network_policy: OutboundNetworkPolicy,
    ) -> ProviderVerificationEvidence:
        base_url = normalize_contract_origin(target_base_url)
        results: list[ProviderInteractionResult] = []
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            for index, interaction in enumerate(pact.interactions):
                try:
                    await self._guard.enforce(base_url, network_policy)
                    for state in interaction.provider_states:
                        await _configure_provider_state(client, base_url, state)
                    actual_status, actual_headers, actual_body = await _send_interaction(
                        client,
                        base_url,
                        interaction.request.method,
                        interaction.request.path,
                        interaction.request.query,
                        interaction.request.headers,
                        interaction.request.body,
                        interaction.response.body,
                    )
                    mismatches = response_mismatch_codes(
                        interaction.response,
                        actual_status=actual_status,
                        actual_headers=actual_headers,
                        actual_body=actual_body,
                    )
                except PactTransportError as error:
                    mismatches = (error.code,)
                except AppError:
                    mismatches = ("OUTBOUND_REQUEST_BLOCKED",)
                except (httpx.HTTPError, TimeoutError):
                    mismatches = ("PROVIDER_REQUEST_FAILED",)
                results.append(
                    ProviderInteractionResult(
                        interaction_index=index,
                        description=interaction.description,
                        status="failed" if mismatches else "passed",
                        mismatch_codes=mismatches,
                    )
                )
        return ProviderVerificationEvidence(
            status="failed" if any(item.status == "failed" for item in results) else "passed",
            interaction_results=tuple(results),
        )


class HttpPactBrokerSource(PactBrokerSource):
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        request_timeout_seconds: float,
        guard: OutboundRequestGuard | None = None,
    ) -> None:
        self._base_url = normalize_contract_origin(base_url)
        self._token = token
        self._timeout = request_timeout_seconds
        self._guard = guard or OutboundRequestGuard()

    async def fetch_pact(
        self,
        *,
        consumer: str,
        provider: str,
        consumer_version: str,
        network_policy: OutboundNetworkPolicy,
    ) -> bytes:
        try:
            await self._guard.enforce(self._base_url, network_policy)
        except AppError as error:
            raise PactTransportError(
                "PACT_BROKER_TARGET_BLOCKED",
                "Pact Broker 地址被出站策略拒绝",
            ) from error
        path = (
            f"/pacts/provider/{quote(provider, safe='')}/consumer/{quote(consumer, safe='')}"
            f"/version/{quote(consumer_version, safe='')}"
        )
        headers = {"Accept": "application/hal+json, application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with (
                httpx.AsyncClient(
                    timeout=self._timeout,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream("GET", f"{self._base_url}{path}", headers=headers) as response,
            ):
                if response.status_code != 200:
                    raise PactTransportError(
                        "PACT_BROKER_FETCH_FAILED",
                        f"Pact Broker 返回 HTTP {response.status_code}",
                    )
                return await _read_limited(
                    response,
                    MAX_PACT_BYTES,
                    error_code="PACT_BROKER_RESPONSE_TOO_LARGE",
                )
        except httpx.HTTPError as error:
            raise PactTransportError("PACT_BROKER_FETCH_FAILED", "Pact Broker 请求失败") from error


async def _configure_provider_state(
    client: httpx.AsyncClient,
    base_url: str,
    state: str,
) -> None:
    response = await client.post(
        f"{base_url}/_pact/provider-states",
        json={"state": state},
    )
    if response.status_code < 200 or response.status_code >= 300:
        raise PactTransportError("PROVIDER_STATE_FAILED", "Provider State 初始化失败")


async def _send_interaction(
    client: httpx.AsyncClient,
    base_url: str,
    method: str,
    path: str,
    query: dict[str, str | list[str]],
    headers: dict[str, str],
    request_body: JsonValue,
    expected_body: JsonValue,
) -> tuple[int, dict[str, str], JsonValue]:
    if request_body is None:
        request = client.build_request(
            method,
            f"{base_url}{path}",
            params=query,
            headers=headers,
        )
    else:
        request = client.build_request(
            method,
            f"{base_url}{path}",
            params=query,
            headers=headers,
            json=request_body,
        )
    response = await client.send(request, stream=True)
    try:
        content = await _read_limited(
            response,
            MAX_PROVIDER_RESPONSE_BYTES,
            error_code="PROVIDER_RESPONSE_TOO_LARGE",
        )
        body = _decode_body(content, expected_body)
        return response.status_code, dict(response.headers), body
    finally:
        await response.aclose()


async def _read_limited(response: httpx.Response, maximum: int, *, error_code: str) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > maximum:
            raise PactTransportError(error_code, "响应超过大小上限")
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_body(content: bytes, expected: JsonValue) -> JsonValue:
    if expected is None:
        return None
    try:
        return _json_value(json.loads(content))
    except (UnicodeDecodeError, json.JSONDecodeError):
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return None


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return None
