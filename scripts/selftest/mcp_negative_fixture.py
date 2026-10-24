"""Disposable loopback-only process fixture; no existing deployment is contacted."""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import socket
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
from scripts.selftest.io import HarnessError, JsonObject, PublicAPI, text_value
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.mcp_negative_contracts import Actor, EmptyAssets


@dataclass(repr=False, frozen=True)
class MachineFixtures:
    tokens: dict[Actor, str]
    project_a: UUID
    project_b: UUID
    organization_a: UUID
    organization_b: UUID


@dataclass(frozen=True)
class LocalFixture:
    api_url: str
    mcp_url: str
    database: Path
    private_directory: Path
    source_digest: str
    budget: ProtocolHttpBudget
    deadline: datetime
    credentials: MachineFixtures


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


async def _wait(process: asyncio.subprocess.Process, port: int) -> None:
    for _ in range(150):
        if process.returncode is not None:
            raise HarnessError("SELFTEST_OWNED_PROCESS_EXITED")
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.1)
        else:
            writer.close()
            await writer.wait_closed()
            return
    raise HarnessError("SELFTEST_OWNED_PROCESS_NOT_READY")


@asynccontextmanager
async def process(
    python: Path,
    arguments: list[str],
    directory: Path,
    environment: dict[str, str],
) -> AsyncIterator[asyncio.subprocess.Process]:
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    with (directory / "process.log").open("w", encoding="utf-8") as log:
        owned = await asyncio.create_subprocess_exec(
            str(python),
            *arguments,
            cwd=directory,
            env=environment,
            stdout=log,
            stderr=log,
        )
        try:
            yield owned
        finally:
            if owned.returncode is None:
                owned.terminate()
                try:
                    await asyncio.wait_for(owned.wait(), timeout=5)
                except TimeoutError:
                    owned.kill()
                    await owned.wait()


async def _account(
    api: PublicAPI,
    organization: UUID,
    key: str,
    scopes: list[str],
    *,
    expires: datetime | None = None,
) -> JsonObject:
    return await api.object(
        "POST",
        f"/organizations/{organization}/service-accounts",
        {
            "name": "协议隔离 " + key,
            "account_key": key,
            "scopes": list(scopes),
            "expires_at": expires.isoformat() if expires is not None else None,
        },
    )


async def _organization(api: PublicAPI, suffix: str) -> tuple[UUID, UUID]:
    organization = await api.object(
        "POST",
        "/organizations",
        {
            "name": "协议独立组织 " + suffix,
            "slug": "protocol-" + suffix,
        },
    )
    identifier = UUID(text_value(organization["id"]))
    project = await api.object(
        "POST",
        "/projects",
        {
            "name": "协议独立项目 " + suffix,
            "organization_id": str(identifier),
        },
    )
    return identifier, UUID(text_value(project["id"]))


async def provision(api_url: str, password: str) -> MachineFixtures:
    public = PublicAPI(api_url)
    try:
        login = await public.object(
            "POST",
            "/auth/login",
            {
                "email": "protocol-admin@example.com",
                "password": password,
            },
        )
    finally:
        await public.close()
    admin_token = text_value(login["access_token"])
    admin = PublicAPI(api_url, admin_token)
    try:
        organization_a, project_a = await _organization(admin, "synthetic-a")
        organization_b, project_b = await _organization(admin, "synthetic-b")
        reader_a = await _account(admin, organization_a, "reader-a", ["mcp:read"])
        reader_b = await _account(admin, organization_b, "reader-b", ["mcp:read"])
        limited = await _account(admin, organization_a, "limited", ["project:read"])
        revoked = await _account(admin, organization_a, "revoked", ["mcp:read"])
        await admin.object(
            "POST",
            f"/organizations/{organization_a}/service-accounts/{revoked['id']}/revoke",
            {},
        )
        expiry = datetime.now(UTC) + timedelta(seconds=1)
        expired = await _account(admin, organization_a, "expired", ["mcp:read"], expires=expiry)
        admin.set_organization(str(organization_a))
        ci = await admin.object(
            "POST",
            f"/projects/{project_a}/service-tokens",
            {
                "name": "协议交叉令牌",
                "scopes": ["read:execution"],
            },
        )
        await asyncio.sleep(max(0, (expiry - datetime.now(UTC)).total_seconds()) + 0.05)
        return MachineFixtures(
            tokens={
                "reader_a": text_value(reader_a["token"]),
                "reader_b": text_value(reader_b["token"]),
                "none": "",
                "limited": text_value(limited["token"]),
                "revoked": text_value(revoked["token"]),
                "expired": text_value(expired["token"]),
                "human": admin_token,
                "ci": text_value(ci["token"]),
            },
            project_a=project_a,
            project_b=project_b,
            organization_a=organization_a,
            organization_b=organization_b,
        )
    finally:
        await admin.close()


def source_digest(backend: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted((backend / "app").rglob("*.py")):
        hasher.update(path.relative_to(backend).as_posix().encode())
        hasher.update(hashlib.sha256(path.read_bytes()).digest())
    return hasher.hexdigest()


@asynccontextmanager
async def local_fixture(
    python: Path, backend: Path, directory: Path
) -> AsyncIterator[LocalFixture]:
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    password = secrets.token_urlsafe(28)
    api_port, gateway_port = _port(), _port()
    deadline = datetime.now(UTC) + timedelta(seconds=600)
    nonce = secrets.token_hex(20)
    budget = ProtocolHttpBudget(directory / "http-budget.sqlite3", nonce, deadline.timestamp())
    api_url = f"http://127.0.0.1:{api_port}"
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(backend) + os.pathsep + str(backend.parent),
        "PYTHONUNBUFFERED": "1",
        "FLOWTEST_PROTOCOL_BUDGET_PATH": str(budget.path),
        "FLOWTEST_PROTOCOL_BUDGET_NONCE": nonce,
        "FLOWTEST_PROTOCOL_BUDGET_DEADLINE": str(deadline.timestamp()),
        "FLOWTEST_RUNTIME_PROFILE": "standalone",
        "FLOWTEST_DATA_DIR": str(directory / "data"),
        "FLOWTEST_DATABASE_URL": f"sqlite+aiosqlite:///{directory}/data.sqlite3",
        "FLOWTEST_STANDALONE_SCHEDULER_ENABLED": "false",
        "FLOWTEST_BOOTSTRAP_ADMIN_EMAIL": "protocol-admin@example.com",
        "FLOWTEST_BOOTSTRAP_ADMIN_PASSWORD": password,
        "FLOWTEST_SECRET_KEY": secrets.token_urlsafe(48),
        "FLOWTEST_LOG_LEVEL": "WARNING",
    }
    async with process(
        python,
        [
            "-m",
            "uvicorn",
            "scripts.selftest.mcp_negative_budget:create_api",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
            "--no-access-log",
        ],
        directory / "api",
        environment,
    ) as api:
        await _wait(api, api_port)
        async with httpx.AsyncClient(trust_env=False) as reader:
            response = await reader.get(api_url + "/api/v1/ready")
            if response.status_code != 200:
                raise HarnessError("SELFTEST_OWNED_API_NOT_READY")
        credentials = await provision(api_url, password)
        gateway_environment = {
            "PATH": environment["PATH"],
            "PYTHONPATH": str(backend),
            "PYTHONUNBUFFERED": "1",
            # Deliberate synthetic poison: HTTP must ignore the process token.
            "FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN": credentials.tokens["reader_a"],
        }
        arguments = [
            "-c",
            "from app.mcp.cli import main; main()",
            "--transport",
            "streamable-http",
            "--api-base-url",
            api_url,
            "--host",
            "127.0.0.1",
            "--port",
            str(gateway_port),
        ]
        async with process(
            python, arguments, directory / "gateway", gateway_environment
        ) as gateway:
            await _wait(gateway, gateway_port)
            yield LocalFixture(
                api_url,
                f"http://127.0.0.1:{gateway_port}/mcp",
                directory / "data.sqlite3",
                directory,
                source_digest(backend),
                budget,
                deadline,
                credentials,
            )


def asset_counts(fixture: LocalFixture) -> EmptyAssets:
    """Independent read-only SQL counts, never secrets or candidate verdicts."""
    database = fixture.database.resolve()
    if database.parent != fixture.private_directory.resolve() or not database.is_file():
        raise HarnessError("SELFTEST_OBSERVER_DATABASE_NOT_OWNED")
    statements = {
        "workflows": "SELECT count(*) FROM workflows",
        "workflow_versions": "SELECT count(*) FROM workflow_versions",
        "cases": "SELECT count(*) FROM test_cases",
        "case_versions": "SELECT count(*) FROM test_case_versions",
        "plans": "SELECT count(*) FROM test_plans",
        "runs": "SELECT count(*) FROM test_plan_runs",
        "executions": "SELECT count(*) FROM workflow_executions",
        "proposals": "SELECT count(*) FROM ai_change_sets",
    }
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        values = {
            key: int(connection.execute(sql).fetchone()[0]) for key, sql in statements.items()
        }
    return EmptyAssets.model_validate(values)
