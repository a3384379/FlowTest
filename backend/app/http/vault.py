from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.domain.data_nodes import CredentialSecretProvider


@dataclass(frozen=True, slots=True)
class VaultKV2Configuration:
    enabled: bool
    address: str
    token: str
    namespace: str
    mount: str
    prefix: str
    timeout_seconds: int
    verify_tls: bool
    production: bool

    @classmethod
    def from_settings(cls, configured: Settings) -> "VaultKV2Configuration":
        return cls(
            enabled=configured.vault_kv2_enabled,
            address=configured.vault_address.rstrip("/"),
            token=configured.vault_token,
            namespace=configured.vault_namespace,
            mount=configured.vault_kv2_mount.strip("/"),
            prefix=configured.vault_kv2_prefix.strip("/"),
            timeout_seconds=configured.vault_request_timeout_seconds,
            verify_tls=configured.vault_tls_verify,
            production=configured.environment.lower() in {"production", "prod"},
        )


class VaultKV2CredentialSecretStore:
    provider_name = CredentialSecretProvider.VAULT_KV2

    def __init__(self, configuration: VaultKV2Configuration) -> None:
        self._configuration = configuration

    async def write(self, *, reference: str, secret: str) -> None:
        response = await self._request(
            "POST",
            self._data_url(reference),
            json={"data": {"secret": secret}},
        )
        if response.status_code not in {200, 204}:
            raise _vault_unavailable()

    async def read(self, *, reference: str) -> str:
        response = await self._request("GET", self._data_url(reference))
        if response.status_code == 404:
            raise AppError(
                code="VAULT_SECRET_NOT_FOUND",
                message="Vault 中的 Credential 已不存在",
                status_code=503,
            )
        if response.status_code != 200:
            raise _vault_unavailable()
        try:
            payload = response.json()
            secret = payload["data"]["data"]["secret"]
        except (KeyError, TypeError, ValueError) as error:
            raise _vault_unavailable() from error
        if not isinstance(secret, str) or not secret:
            raise _vault_unavailable()
        return secret

    async def delete(self, *, reference: str) -> None:
        response = await self._request("DELETE", self._metadata_url(reference))
        if response.status_code not in {200, 204, 404}:
            raise _vault_unavailable()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        self._ensure_enabled()
        headers = {"X-Vault-Token": self._configuration.token}
        if self._configuration.namespace:
            headers["X-Vault-Namespace"] = self._configuration.namespace
        try:
            async with httpx.AsyncClient(
                timeout=self._configuration.timeout_seconds,
                verify=self._configuration.verify_tls,
                follow_redirects=False,
            ) as client:
                return await client.request(method, url, headers=headers, json=json)
        except httpx.HTTPError as error:
            raise _vault_unavailable() from error

    def _data_url(self, reference: str) -> str:
        return self._url("data", reference)

    def _metadata_url(self, reference: str) -> str:
        return self._url("metadata", reference)

    def _url(self, resource: str, reference: str) -> str:
        self._ensure_enabled()
        segments = [
            self._configuration.mount,
            resource,
            self._configuration.prefix,
            *reference.split("/"),
        ]
        encoded_path = "/".join(quote(segment, safe="") for segment in segments if segment)
        return f"{self._configuration.address}/v1/{encoded_path}"

    def _ensure_enabled(self) -> None:
        parsed = urlsplit(self._configuration.address)
        allowed_schemes = {"https"} if self._configuration.production else {"http", "https"}
        if (
            not self._configuration.enabled
            or parsed.scheme not in allowed_schemes
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or not self._configuration.token
        ):
            raise AppError(
                code="VAULT_NOT_CONFIGURED",
                message="Vault KV v2 尚未正确配置",
                status_code=503,
            )


def _vault_unavailable() -> AppError:
    return AppError(code="VAULT_UNAVAILABLE", message="Vault KV v2 暂时不可用", status_code=503)
