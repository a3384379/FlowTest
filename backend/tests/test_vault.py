import httpx
import pytest
import respx

from app.core.errors import AppError
from app.http.vault import VaultKV2Configuration, VaultKV2CredentialSecretStore

REFERENCE = "projects/project-1/credentials/credential-1"
DATA_URL = (
    "https://vault.example/v1/secret/data/flowtest/projects/project-1/credentials/credential-1"
)
METADATA_URL = (
    "https://vault.example/v1/secret/metadata/flowtest/projects/project-1/credentials/credential-1"
)


@pytest.mark.asyncio
@respx.mock
async def test_vault_kv2_write_read_delete_and_headers() -> None:
    store = VaultKV2CredentialSecretStore(_configuration())
    write_route = respx.post(DATA_URL).mock(return_value=httpx.Response(200, json={"data": {}}))
    read_route = respx.get(DATA_URL).mock(
        return_value=httpx.Response(200, json={"data": {"data": {"secret": "stored-value"}}})
    )
    delete_route = respx.delete(METADATA_URL).mock(return_value=httpx.Response(204))

    await store.write(reference=REFERENCE, secret="stored-value")
    assert await store.read(reference=REFERENCE) == "stored-value"
    await store.delete(reference=REFERENCE)

    assert write_route.calls.last.request.headers["x-vault-token"] == "vault-token"
    assert write_route.calls.last.request.headers["x-vault-namespace"] == "organization"
    assert read_route.called
    assert delete_route.called


@pytest.mark.asyncio
@respx.mock
async def test_vault_kv2_maps_missing_invalid_and_unavailable_responses() -> None:
    store = VaultKV2CredentialSecretStore(_configuration())
    read_route = respx.get(DATA_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(AppError) as missing:
        await store.read(reference=REFERENCE)
    assert missing.value.code == "VAULT_SECRET_NOT_FOUND"

    read_route.mock(return_value=httpx.Response(200, json={"data": {}}))
    with pytest.raises(AppError) as malformed:
        await store.read(reference=REFERENCE)
    assert malformed.value.code == "VAULT_UNAVAILABLE"

    respx.post(DATA_URL).mock(return_value=httpx.Response(500))
    with pytest.raises(AppError) as write_failed:
        await store.write(reference=REFERENCE, secret="value")
    assert write_failed.value.code == "VAULT_UNAVAILABLE"

    respx.delete(METADATA_URL).mock(return_value=httpx.Response(403))
    with pytest.raises(AppError) as delete_failed:
        await store.delete(reference=REFERENCE)
    assert delete_failed.value.code == "VAULT_UNAVAILABLE"

    read_route.mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(AppError) as unreachable:
        await store.read(reference=REFERENCE)
    assert unreachable.value.code == "VAULT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_vault_kv2_rejects_disabled_or_insecure_production_configuration() -> None:
    disabled = VaultKV2CredentialSecretStore(replace_configuration(enabled=False))
    with pytest.raises(AppError) as not_configured:
        await disabled.read(reference=REFERENCE)
    assert not_configured.value.code == "VAULT_NOT_CONFIGURED"

    insecure = VaultKV2CredentialSecretStore(
        replace_configuration(address="http://vault.example", production=True)
    )
    with pytest.raises(AppError) as invalid_url:
        await insecure.read(reference=REFERENCE)
    assert invalid_url.value.code == "VAULT_NOT_CONFIGURED"


def _configuration() -> VaultKV2Configuration:
    return VaultKV2Configuration(
        enabled=True,
        address="https://vault.example",
        token="vault-token",
        namespace="organization",
        mount="secret",
        prefix="flowtest",
        timeout_seconds=5,
        verify_tls=True,
        production=True,
    )


def replace_configuration(
    *,
    enabled: bool = True,
    address: str = "https://vault.example",
    production: bool = True,
) -> VaultKV2Configuration:
    configured = _configuration()
    return VaultKV2Configuration(
        enabled=enabled,
        address=address,
        token=configured.token,
        namespace=configured.namespace,
        mount=configured.mount,
        prefix=configured.prefix,
        timeout_seconds=configured.timeout_seconds,
        verify_tls=configured.verify_tls,
        production=production,
    )
