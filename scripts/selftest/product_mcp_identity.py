"""Recover one owned product MCP actor without rotation or ambiguous POST replay."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from pydantic import AwareDatetime, Field, TypeAdapter, ValidationError
from scripts.selftest.bootstrap import Installation
from scripts.selftest.bootstrap_journal import bootstrap_lock
from scripts.selftest.contracts import Contract, canonical_digest
from scripts.selftest.io import HarnessError, PublicAPI, read_json, write_json
from scripts.selftest.local_stack import StackBinding
from scripts.selftest.product_agent_client import AgentRuntime, ProductAgentConfig

from app.schemas.mcp_connection import MCPConnectionResponse
from app.schemas.organizations import ServiceAccountIssuedResponse, ServiceAccountResponse

ACCOUNT_NAME = "产品自测独立生成身份"
SCOPES = tuple(
    sorted(
        (
            "project:read",
            "project:write",
            "mcp:read",
            "mcp:write",
            "mcp:flow:propose",
            "mcp:evidence:write",
            "mcp:project:bootstrap",
            "mcp:contract:import",
            "mcp:test-plan:propose",
        )
    )
)
ApiFactory = Callable[[str, str, str | None], PublicAPI]


class AccountReceipt(Contract):
    account_id: UUID
    expires_at: AwareDatetime


class AccountRequest(Contract):
    account_key: str = Field(min_length=1, max_length=120)
    expires_at: AwareDatetime


class IdentityIntent(Contract):
    binding_nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    project_id: UUID
    organization_id: UUID
    request: AccountRequest


class PrivateIdentity(IdentityIntent):
    account_id: UUID
    name: str
    scopes: tuple[str, ...]
    token: str = Field(min_length=32, max_length=512, repr=False)


class EncryptedIdentity(IdentityIntent):
    account_id: UUID
    name: str
    scopes: tuple[str, ...]
    token_ciphertext: str = Field(min_length=32, max_length=2048, repr=False)


def _cipher(identity: IdentityIntent, identifier: UUID, key: str) -> Fernet:
    context = canonical_digest(
        {
            **identity.model_dump(mode="json", include=set(IdentityIntent.model_fields)),
            "account_id": str(identifier),
        }
    )
    derived = hmac.new(key.encode(), context.encode(), hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def _seal(identity: PrivateIdentity, key: str) -> EncryptedIdentity:
    encrypted = (
        _cipher(identity, identity.account_id, key).encrypt(identity.token.encode()).decode()
    )
    return EncryptedIdentity.model_validate(
        {**identity.model_dump(exclude={"token"}), "token_ciphertext": encrypted}
    )


def _open(identity: EncryptedIdentity, key: str) -> PrivateIdentity:
    token = _cipher(identity, identity.account_id, key).decrypt(identity.token_ciphertext.encode())
    return PrivateIdentity.model_validate(
        {**identity.model_dump(exclude={"token_ciphertext"}), "token": token.decode()}
    )


def _utc(value: datetime) -> datetime:
    # ServiceAccountService explicitly treats legacy SQLite naive datetimes as UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _expiry(account: ServiceAccountResponse) -> datetime:
    if account.expires_at is None:
        raise HarnessError("SELFTEST_PRODUCT_MCP_ACCOUNT_CHANGED_OR_EXPIRED")
    return _utc(account.expires_at)


def _private(path: Path) -> None:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_mode & 0o077
        or path.stat().st_uid != os.getuid()
    ):
        raise HarnessError("SELFTEST_PRODUCT_MCP_PRIVATE_FILE_UNSAFE")


def _check_account(account: ServiceAccountResponse, organization: UUID) -> None:
    if (
        account.organization_id != organization
        or account.name != ACCOUNT_NAME
        or tuple(sorted(account.scopes)) != SCOPES
        or not account.enabled
        or account.revoked_at is not None
        or account.expires_at is None
        or _expiry(account) <= datetime.now(UTC)
        or not account.account_key.startswith("selftest-product-")
    ):
        raise HarnessError("SELFTEST_PRODUCT_MCP_ACCOUNT_CHANGED_OR_EXPIRED")


async def _accounts(api: PublicAPI, organization: UUID) -> list[ServiceAccountResponse]:
    result = await api.request("GET", f"/organizations/{organization}/service-accounts")
    return TypeAdapter(list[ServiceAccountResponse]).validate_python(result)


def _select(accounts: list[ServiceAccountResponse], identifier: UUID) -> ServiceAccountResponse:
    selected = [account for account in accounts if account.id == identifier]
    if len(selected) != 1:
        raise HarnessError("SELFTEST_PRODUCT_MCP_ACCOUNT_MISSING_OR_DUPLICATE")
    return selected[0]


async def _connection(identity: PrivateIdentity, stack: StackBinding, factory: ApiFactory) -> None:
    api = factory(stack.runner_url, identity.token, str(identity.organization_id))
    try:
        connection = MCPConnectionResponse.model_validate(
            await api.object("POST", "/mcp/connection", {})
        )
    finally:
        await api.close()
    if (
        connection.service_account_id != identity.account_id
        or connection.organization_id != identity.organization_id
        or tuple(sorted(connection.effective_scopes)) != SCOPES
        or connection.expires_at is None
        or _utc(connection.expires_at) != identity.request.expires_at
    ):
        raise HarnessError("SELFTEST_PRODUCT_MCP_CONNECTION_MISMATCH")


async def _validate(
    identity: PrivateIdentity,
    accounts: list[ServiceAccountResponse],
    installed: Installation,
    stack: StackBinding,
    factory: ApiFactory,
) -> None:
    if (identity.binding_nonce, identity.project_id, identity.organization_id) != (
        stack.nonce,
        installed.project_id,
        installed.organization_id,
    ):
        raise HarnessError("SELFTEST_PRODUCT_MCP_BINDING_MISMATCH")
    account = _select(accounts, identity.account_id)
    _check_account(account, installed.organization_id)
    if (
        identity.name != account.name
        or identity.scopes != SCOPES
        or identity.request.account_key != account.account_key
        or identity.request.expires_at != _expiry(account)
        or account.token_prefix != identity.token[:16]
    ):
        raise HarnessError("SELFTEST_PRODUCT_MCP_ACCOUNT_CHANGED_OR_EXPIRED")
    await _connection(identity, stack, factory)


def _origin(
    recovery: Path, installed: Installation, stack: StackBinding
) -> tuple[AgentRuntime, AccountReceipt]:
    if recovery.is_symlink():
        raise HarnessError("SELFTEST_PRODUCT_MCP_PRIVATE_FILE_UNSAFE")
    for name in ("agent-config.json", "harness-runtime.json", "mcp-account-receipt.json"):
        _private(recovery / name)
    config = ProductAgentConfig.model_validate(read_json(recovery / "agent-config.json"))
    runtime = AgentRuntime.model_validate(read_json(recovery / "harness-runtime.json"))
    receipt = AccountReceipt.model_validate(read_json(recovery / "mcp-account-receipt.json"))
    fingerprint = canonical_digest(
        {
            "nonce": stack.nonce,
            "subnet": stack.private_subnet,
            "runner_volume": stack.runner_volume,
            "target_volume": stack.target_volume,
            "project": str(installed.project_id),
        }
    )
    actual = (
        runtime.installation.binding_nonce,
        runtime.installation.organization_id,
        runtime.installation.project_id,
        runtime.installation.target_project_id,
        runtime.installation.target_organization_id,
        runtime.installation.target_user_id,
    )
    expected = (
        stack.nonce,
        installed.organization_id,
        installed.project_id,
        installed.target_project_id,
        installed.target_organization_id,
        installed.target_user_id,
    )
    if actual != expected or not _origin_config(config, installed, stack, fingerprint):
        raise HarnessError("SELFTEST_PRODUCT_MCP_RECOVERY_BINDING_MISMATCH")
    if (
        runtime.role != "harness"
        or runtime.expires_at.tzinfo is None
        or runtime.expires_at <= datetime.now(UTC)
        or runtime.installation.mcp_account_id != receipt.account_id
    ):
        raise HarnessError("SELFTEST_PRODUCT_MCP_RECOVERY_RUNTIME_INVALID")
    return runtime, receipt


def _origin_config(
    config: ProductAgentConfig, installed: Installation, stack: StackBinding, fingerprint: str
) -> bool:
    binding = config.binding
    return (
        config.project_id == installed.project_id
        and binding.allowed_project_ids == (installed.project_id,)
        and binding.runner_instance_id == f"runner-{stack.nonce}"
        and binding.target_instance_id == f"target-{stack.nonce}"
        and binding.target_project_id == installed.target_project_id
        and binding.target_organization_id == installed.target_organization_id
        and binding.target_user_id == installed.target_user_id
        and binding.environment_fingerprint == fingerprint
        and binding.isolation_fingerprint == fingerprint
    )


def _recover(
    recovery: Path,
    accounts: list[ServiceAccountResponse],
    installed: Installation,
    stack: StackBinding,
) -> PrivateIdentity:
    runtime, receipt = _origin(recovery, installed, stack)
    account = _select(accounts, receipt.account_id)
    _check_account(account, installed.organization_id)
    if receipt.expires_at != _expiry(account):
        raise HarnessError("SELFTEST_PRODUCT_MCP_RECOVERY_RECEIPT_MISMATCH")
    return PrivateIdentity(
        binding_nonce=stack.nonce,
        project_id=installed.project_id,
        organization_id=installed.organization_id,
        request=AccountRequest(account_key=account.account_key, expires_at=receipt.expires_at),
        account_id=receipt.account_id,
        name=account.name,
        scopes=tuple(sorted(account.scopes)),
        token=runtime.mcp_token,
    )


async def issue_identity(
    administrator: PublicAPI,
    organization_id: UUID,
    state: Path,
    *,
    request: AccountRequest | None = None,
) -> tuple[UUID, str]:
    request = request or AccountRequest(
        account_key="selftest-product-" + secrets.token_hex(8),
        expires_at=datetime.now(UTC) + timedelta(hours=2),
    )
    issued = ServiceAccountIssuedResponse.model_validate(
        await administrator.object(
            "POST",
            f"/organizations/{organization_id}/service-accounts",
            {
                "name": ACCOUNT_NAME,
                "account_key": request.account_key,
                "scopes": list(SCOPES),
                "expires_at": request.expires_at.isoformat(),
            },
        )
    )
    _check_account(issued, organization_id)
    write_json(
        state / "mcp-account-receipt.json",
        AccountReceipt(account_id=issued.id, expires_at=request.expires_at),
    )
    return issued.id, issued.token


async def resolve_identity(
    administrator: PublicAPI,
    installed: Installation,
    stack: StackBinding,
    directory: Path,
    state: Path,
    *,
    recover_state: Path | None,
    factory: ApiFactory,
    encryption_key: str,
) -> tuple[UUID, str]:
    expected = {"project_name": stack.project_name, "nonce": stack.nonce}
    if read_json(directory / "ownership.json") != expected:
        raise HarnessError("SELFTEST_PRODUCT_MCP_OWNERSHIP_MISMATCH")
    if len(encryption_key) < 32:
        raise HarnessError("SELFTEST_PRODUCT_MCP_ENCRYPTION_KEY_INVALID")
    try:
        with bootstrap_lock(directory, stack.nonce):
            identity = await _resolve(
                administrator, installed, stack, directory, state, recover_state, encryption_key
            )
            accounts = await _accounts(administrator, installed.organization_id)
            await _validate(identity, accounts, installed, stack, factory)
            write_json(
                directory / "product-mcp-identity.private.json", _seal(identity, encryption_key)
            )
            write_json(
                state / "mcp-account-receipt.json",
                AccountReceipt(
                    account_id=identity.account_id, expires_at=identity.request.expires_at
                ),
            )
            return identity.account_id, identity.token
    except (ValidationError, InvalidToken, UnicodeDecodeError):
        raise HarnessError("SELFTEST_PRODUCT_MCP_PRIVATE_IDENTITY_INVALID") from None


async def _resolve(
    api: PublicAPI,
    installed: Installation,
    stack: StackBinding,
    directory: Path,
    state: Path,
    recovery: Path | None,
    encryption_key: str,
) -> PrivateIdentity:
    path = directory / "product-mcp-identity.private.json"
    intent_path = directory / "product-mcp-identity-intent.json"
    if path.exists():
        _private(path)
        return _open(EncryptedIdentity.model_validate(read_json(path)), encryption_key)
    if intent_path.exists():
        raise HarnessError("SELFTEST_PRODUCT_MCP_UNKNOWN_RESULT_NEEDS_REVIEW")
    accounts = await _accounts(api, installed.organization_id)
    if recovery is not None:
        return _recover(recovery, accounts, installed, stack)
    if any(account.name == ACCOUNT_NAME for account in accounts):
        raise HarnessError("SELFTEST_PRODUCT_MCP_RECOVERY_REQUIRED")
    request = AccountRequest(
        account_key="selftest-product-" + secrets.token_hex(8),
        expires_at=datetime.now(UTC) + timedelta(hours=2),
    )
    intent = IdentityIntent(
        binding_nonce=stack.nonce,
        project_id=installed.project_id,
        organization_id=installed.organization_id,
        request=request,
    )
    write_json(intent_path, intent)
    identifier, token = await issue_identity(api, installed.organization_id, state, request=request)
    identity = PrivateIdentity(
        **intent.model_dump(), account_id=identifier, name=ACCOUNT_NAME, scopes=SCOPES, token=token
    )
    # Preserve the write-only token immediately. A later readback failure must not
    # turn an acknowledged account creation into another POST on the next run.
    write_json(path, _seal(identity, encryption_key))
    return identity
