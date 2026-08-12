import asyncio
import ipaddress
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, cast

from pydantic import JsonValue
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import URL, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.core.config import settings
from app.core.errors import AppError
from app.domain.data_nodes import (
    CredentialKind,
    DataNodeValidationError,
    validate_read_only_sql,
    validate_redis_read,
)
from app.domain.network import OutboundNetworkPolicy
from app.engine.scheduler import NodeExecutionError
from app.services.credentials import CredentialMaterial
from app.services.outbound import OutboundRequestGuard, outbound_request_guard


@dataclass(frozen=True, slots=True)
class PreparedDataNode:
    credential: CredentialMaterial


class DataNodeRunner(Protocol):
    async def execute_sql(
        self,
        credential: CredentialMaterial,
        query: str,
        parameters: Mapping[str, JsonValue],
        timeout_seconds: int,
    ) -> JsonValue: ...

    async def execute_redis(
        self,
        credential: CredentialMaterial,
        command: str,
        arguments: list[str],
        timeout_seconds: int,
    ) -> JsonValue: ...


class InfrastructureDataNodeRunner:
    def __init__(
        self,
        network_policy: OutboundNetworkPolicy,
        *,
        outbound_guard: OutboundRequestGuard = outbound_request_guard,
    ) -> None:
        self._network_policy = network_policy
        self._outbound_guard = outbound_guard

    async def execute_sql(
        self,
        credential: CredentialMaterial,
        query: str,
        parameters: Mapping[str, JsonValue],
        timeout_seconds: int,
    ) -> JsonValue:
        if credential.kind not in {CredentialKind.POSTGRESQL, CredentialKind.MYSQL}:
            raise NodeExecutionError(
                code="CREDENTIAL_KIND_MISMATCH",
                message="SQL 节点必须使用 PostgreSQL 或 MySQL Credential",
            )
        normalized = _validated_sql(query, credential.kind)
        expected_addresses = await self._enforce_target(credential)
        engine = _sql_engine(credential)
        try:
            async with asyncio.timeout(timeout_seconds):
                async with engine.connect() as connection:
                    await _verify_sql_peer(connection, expected_addresses)
                    rows = await _read_rows(connection, normalized, parameters)
        except TimeoutError as error:
            raise NodeExecutionError(code="DATA_NODE_TIMEOUT", message="SQL 查询超时") from error
        except SQLAlchemyError as error:
            raise NodeExecutionError(
                code="SQL_EXECUTION_FAILED", message="SQL 查询执行失败"
            ) from error
        finally:
            await engine.dispose()
        return _bounded_output({"row_count": len(rows), "rows": cast(JsonValue, rows)})

    async def execute_redis(
        self,
        credential: CredentialMaterial,
        command: str,
        arguments: list[str],
        timeout_seconds: int,
    ) -> JsonValue:
        if credential.kind is not CredentialKind.REDIS:
            raise NodeExecutionError(
                code="CREDENTIAL_KIND_MISMATCH",
                message="Redis 节点必须使用 Redis Credential",
            )
        parsed = _validated_redis(command, arguments)
        expected_addresses = await self._enforce_target(credential)
        client: Redis = Redis(
            host=credential.host,
            port=credential.port,
            username=credential.username or None,
            password=credential.secret,
            ssl=credential.tls_enabled,
            decode_responses=True,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
            single_connection_client=True,
        )
        try:
            async with asyncio.timeout(timeout_seconds):
                await client.initialize()
                _verify_redis_peer(client, expected_addresses)
                result = await client.execute_command(parsed, *arguments)  # type: ignore[no-untyped-call]
        except TimeoutError as error:
            raise NodeExecutionError(code="DATA_NODE_TIMEOUT", message="Redis 读取超时") from error
        except RedisError as error:
            raise NodeExecutionError(
                code="REDIS_EXECUTION_FAILED", message="Redis 读取失败"
            ) from error
        finally:
            await client.aclose()
        return _bounded_output({"command": parsed, "result": _json_value(result)})

    async def _enforce_target(self, credential: CredentialMaterial) -> tuple[str, ...]:
        try:
            return await self._outbound_guard.enforce_target(
                credential.host,
                credential.port,
                self._network_policy,
            )
        except AppError as error:
            raise NodeExecutionError(code=error.code, message=error.message) from error


async def _verify_sql_peer(
    connection: AsyncConnection,
    expected_addresses: tuple[str, ...],
) -> None:
    raw_connection = await connection.get_raw_connection()
    driver_connection = raw_connection.driver_connection
    _verify_peer(
        _transport_peer(getattr(driver_connection, "_transport", None)), expected_addresses
    )


def _verify_redis_peer(client: Redis, expected_addresses: tuple[str, ...]) -> None:
    connection = client.connection
    writer = getattr(connection, "_writer", None)
    _verify_peer(_transport_peer(getattr(writer, "transport", None)), expected_addresses)


def _transport_peer(transport: object) -> str:
    get_extra_info = getattr(transport, "get_extra_info", None)
    if not callable(get_extra_info):
        raise NodeExecutionError(
            code="OUTBOUND_PEER_UNAVAILABLE",
            message="无法验证数据节点实际连接地址",
        )
    peer = get_extra_info("peername")
    if not isinstance(peer, tuple) or not peer or not isinstance(peer[0], str):
        raise NodeExecutionError(
            code="OUTBOUND_PEER_UNAVAILABLE",
            message="无法验证数据节点实际连接地址",
        )
    return peer[0]


def _verify_peer(peer: str, expected_addresses: tuple[str, ...]) -> None:
    try:
        actual = ipaddress.ip_address(peer)
        expected = {ipaddress.ip_address(value) for value in expected_addresses}
    except ValueError as error:
        raise NodeExecutionError(
            code="OUTBOUND_PEER_UNAVAILABLE",
            message="无法验证数据节点实际连接地址",
        ) from error
    if actual not in expected:
        raise NodeExecutionError(
            code="DNS_REBINDING_BLOCKED",
            message="数据节点实际连接地址与安全校验结果不一致",
        )


async def _read_rows(
    connection: AsyncConnection,
    query: str,
    parameters: Mapping[str, JsonValue],
) -> list[dict[str, JsonValue]]:
    async with connection.begin():
        await connection.execute(text("SET TRANSACTION READ ONLY"))
        stream = await connection.stream(text(query), dict(parameters))
        mappings = await stream.mappings().fetchmany(1001)
    if len(mappings) > 1000:
        raise NodeExecutionError(code="SQL_ROW_LIMIT_EXCEEDED", message="SQL 查询超过 1000 行上限")
    return [{name: _json_value(value) for name, value in row.items()} for row in mappings]


def _sql_engine(credential: CredentialMaterial) -> AsyncEngine:
    driver = (
        "postgresql+asyncpg" if credential.kind is CredentialKind.POSTGRESQL else "mysql+asyncmy"
    )
    url = URL.create(
        driver,
        username=credential.username or None,
        password=credential.secret,
        host=credential.host,
        port=credential.port,
        database=credential.database_name,
    )
    connect_args: dict[str, object] = {}
    if credential.tls_enabled:
        connect_args["ssl"] = True if credential.kind is CredentialKind.POSTGRESQL else {}
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
        connect_args=connect_args,
    )


def _validated_sql(query: str, kind: CredentialKind) -> str:
    try:
        return validate_read_only_sql(query, kind)
    except DataNodeValidationError as error:
        raise NodeExecutionError(code="UNSAFE_SQL", message=str(error)) from error


def _validated_redis(command: str, arguments: list[str]) -> str:
    try:
        return validate_redis_read(command, arguments).value
    except DataNodeValidationError as error:
        raise NodeExecutionError(code="UNSAFE_REDIS_COMMAND", message=str(error)) from error


def _bounded_output(output: dict[str, JsonValue]) -> dict[str, JsonValue]:
    size_bytes = len(json.dumps(output, ensure_ascii=False, default=str).encode())
    if size_bytes > settings.inline_body_limit_bytes:
        raise NodeExecutionError(
            code="DATA_NODE_RESPONSE_TOO_LARGE",
            message="数据节点结果超过 2 MB 内联上限",
        )
    return output


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    if isinstance(value, Mapping):
        return {str(name): _json_value(item) for name, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    return cast(JsonValue, str(value))
