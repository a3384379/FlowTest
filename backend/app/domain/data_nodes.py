from enum import StrEnum

from sqlglot import exp, parse
from sqlglot.errors import ParseError


class DataNodeValidationError(ValueError):
    """Raised when a data-node operation violates the read-only contract."""


class CredentialKind(StrEnum):
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    REDIS = "redis"


class RedisReadCommand(StrEnum):
    GET = "GET"
    MGET = "MGET"
    HGET = "HGET"
    HGETALL = "HGETALL"
    SMEMBERS = "SMEMBERS"
    ZRANGE = "ZRANGE"
    EXISTS = "EXISTS"
    TTL = "TTL"


_FORBIDDEN_SQL_EXPRESSIONS = (
    exp.Alter,
    exp.Command,
    exp.Commit,
    exp.Create,
    exp.Delete,
    exp.Drop,
    exp.Insert,
    exp.Merge,
    exp.Rollback,
    exp.Set,
    exp.Transaction,
    exp.TruncateTable,
    exp.Update,
)


def validate_read_only_sql(query: str, kind: CredentialKind) -> str:
    normalized = query.strip().rstrip(";").strip()
    if not normalized:
        raise DataNodeValidationError("SQL 查询不能为空")
    if len(normalized) > 100_000:
        raise DataNodeValidationError("SQL 查询超过 100 KB 上限")
    dialect = "postgres" if kind is CredentialKind.POSTGRESQL else "mysql"
    try:
        statements = parse(normalized, read=dialect)
    except ParseError as error:
        raise DataNodeValidationError("SQL 语法无效") from error
    if len(statements) != 1 or statements[0] is None:
        raise DataNodeValidationError("仅允许单条 SQL 查询")
    statement = statements[0]
    if not isinstance(statement, exp.Query):
        raise DataNodeValidationError("仅允许 SELECT 或 WITH ... SELECT 查询")
    if any(statement.find(expression) is not None for expression in _FORBIDDEN_SQL_EXPRESSIONS):
        raise DataNodeValidationError("SQL 查询包含写入、DDL 或事务控制语句")
    return normalized


def validate_redis_read(command: str, arguments: list[str]) -> RedisReadCommand:
    try:
        parsed = RedisReadCommand(command.strip().upper())
    except ValueError as error:
        raise DataNodeValidationError("Redis 命令不在只读白名单中") from error
    if any(not value or len(value) > 4096 for value in arguments):
        raise DataNodeValidationError("Redis 参数不能为空且每项不得超过 4096 字符")
    expected = {
        RedisReadCommand.GET: (1, 1),
        RedisReadCommand.MGET: (1, 100),
        RedisReadCommand.HGET: (2, 2),
        RedisReadCommand.HGETALL: (1, 1),
        RedisReadCommand.SMEMBERS: (1, 1),
        RedisReadCommand.ZRANGE: (3, 3),
        RedisReadCommand.EXISTS: (1, 100),
        RedisReadCommand.TTL: (1, 1),
    }[parsed]
    if not expected[0] <= len(arguments) <= expected[1]:
        raise DataNodeValidationError(
            f"Redis {parsed.value} 参数数量必须在 {expected[0]} 到 {expected[1]} 之间"
        )
    if parsed is RedisReadCommand.ZRANGE:
        _validate_zrange(arguments)
    return parsed


def _validate_zrange(arguments: list[str]) -> None:
    try:
        start = int(arguments[1])
        stop = int(arguments[2])
    except ValueError as error:
        raise DataNodeValidationError("ZRANGE 起止位置必须是整数") from error
    if start < 0 or stop < start or stop - start >= 1000:
        raise DataNodeValidationError("ZRANGE 仅允许读取最多 1000 项的非负范围")
