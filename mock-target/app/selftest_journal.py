"""SQLite-backed synthetic receipts shared by separate fixture listeners."""

import hashlib
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from .selftest_contracts import (
    SYNTHETIC_FILE_BYTES,
    BinaryResponseSnapshot,
    BudgetReceipt,
    BudgetScope,
    FixtureConfiguration,
    FixtureJournal,
    FixtureMetrics,
    FixtureOperation,
    FixtureRemovalCondition,
    FixtureRequestEvent,
    JournalEntry,
    SyntheticCookieSnapshot,
    SyntheticHeaderSnapshot,
    SyntheticRequest,
    SyntheticResponse,
)


class FixtureError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class FixtureReply:
    body: SyntheticResponse
    status_code: int
    delay_ms: int
    request_id: str


class FixtureStore:
    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS fixture_metadata (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS selftest_budget_scopes (
                    parent_batch_key TEXT NOT NULL, nonce TEXT NOT NULL,
                    budget_limit INTEGER NOT NULL,
                    fixture_digest TEXT NOT NULL, registration_epoch TEXT NOT NULL,
                    expires_at REAL NOT NULL, admitted_count INTEGER NOT NULL DEFAULT 0,
                    rejected_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(parent_batch_key, nonce)
                );
                CREATE TABLE IF NOT EXISTS selftest_fixtures (
                    batch_key TEXT NOT NULL, scenario_id TEXT NOT NULL,
                    configuration TEXT NOT NULL, registration_epoch TEXT NOT NULL,
                    expires_at REAL NOT NULL, request_count INTEGER NOT NULL DEFAULT 0,
                    stored_bytes INTEGER NOT NULL DEFAULT 0,
                    truncated INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (batch_key, scenario_id)
                );
                CREATE TABLE IF NOT EXISTS selftest_fixture_generations (
                    batch_key TEXT NOT NULL, scenario_id TEXT NOT NULL,
                    generation TEXT NOT NULL,
                    PRIMARY KEY(batch_key, scenario_id),
                    FOREIGN KEY(batch_key, scenario_id)
                        REFERENCES selftest_fixtures(batch_key, scenario_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS selftest_request_events (
                    request_id TEXT PRIMARY KEY,
                    batch_key TEXT NOT NULL, scenario_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL, started_at REAL NOT NULL,
                    completed_at REAL, outcome TEXT, active_at_begin INTEGER NOT NULL,
                    UNIQUE(batch_key, scenario_id, sequence),
                    FOREIGN KEY(batch_key, scenario_id)
                        REFERENCES selftest_fixtures(batch_key, scenario_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS selftest_receipts (
                    batch_key TEXT NOT NULL, scenario_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (batch_key, scenario_id, sequence),
                    FOREIGN KEY (batch_key, scenario_id)
                        REFERENCES selftest_fixtures(batch_key, scenario_id) ON DELETE CASCADE
                );
                """
            )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=5)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                yield connection

    def start_epoch(self) -> str:
        epoch = str(uuid4())
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO fixture_metadata(key, value) VALUES ('epoch', ?)",
                (epoch,),
            )
        return epoch

    @staticmethod
    def _epoch(connection: sqlite3.Connection) -> str:
        row = connection.execute("SELECT value FROM fixture_metadata WHERE key='epoch'").fetchone()
        if row is None:
            raise FixtureError("FIXTURE_NOT_STARTED", "合成目标尚未启动", 503)
        return str(row["value"])

    @staticmethod
    def _fixture(connection: sqlite3.Connection, batch: str, scenario: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM selftest_fixtures WHERE batch_key=? AND scenario_id=?",
            (batch, scenario),
        ).fetchone()
        if row is None:
            raise FixtureError("FIXTURE_NOT_FOUND", "合成场景不存在", 404)
        return cast(sqlite3.Row, row)

    def configure(self, batch: str, scenario: str, payload: FixtureConfiguration) -> None:
        with self._transaction() as connection:
            connection.execute(
                "DELETE FROM selftest_fixtures WHERE expires_at <= ?", (self._clock(),)
            )
            existing = connection.execute(
                "SELECT configuration FROM selftest_fixtures WHERE batch_key=? AND scenario_id=?",
                (batch, scenario),
            ).fetchone()
            encoded = payload.model_dump_json()
            if existing is not None:
                if existing["configuration"] != encoded:
                    raise FixtureError("FIXTURE_CONFIGURATION_CONFLICT", "场景已固定,不能覆盖", 409)
                self._register_budget(connection, batch, payload)
                self._generation(connection, batch, scenario)
                return
            self._register_budget(connection, batch, payload)
            count = connection.execute("SELECT count(*) FROM selftest_fixtures").fetchone()[0]
            if count >= 128:
                raise FixtureError("FIXTURE_CAPACITY_EXCEEDED", "合成场景容量已满", 429)
            connection.execute(
                """INSERT INTO selftest_fixtures(
                    batch_key,scenario_id,configuration,registration_epoch,expires_at
                ) VALUES (?,?,?,?,?)""",
                (
                    batch,
                    scenario,
                    encoded,
                    self._epoch(connection),
                    self._clock() + payload.ttl_seconds,
                ),
            )

            self._generation(connection, batch, scenario)

    @staticmethod
    def _generation(connection: sqlite3.Connection, batch: str, scenario: str) -> str:
        connection.execute(
            "INSERT OR IGNORE INTO selftest_fixture_generations("
            "batch_key,scenario_id,generation) VALUES (?,?,?)",
            (batch, scenario, str(uuid4())),
        )
        row = connection.execute(
            "SELECT generation FROM selftest_fixture_generations "
            "WHERE batch_key=? AND scenario_id=?",
            (batch, scenario),
        ).fetchone()
        return str(row["generation"])

    def _register_budget(
        self, connection: sqlite3.Connection, batch: str, config: FixtureConfiguration
    ) -> None:
        scope = config.budget_scope or BudgetScope(parent_batch_key=batch, nonce=config.nonce)
        if scope.nonce != config.nonce:
            raise FixtureError("FIXTURE_BUDGET_NONCE_MISMATCH", "预算nonce与场景不一致", 409)
        now = self._clock()
        expires = scope.expires_at if scope.expires_at is not None else now + config.ttl_seconds
        if not now < expires <= now + 3600:
            raise FixtureError("FIXTURE_BUDGET_EXPIRED", "预算期限无效或已过期", 410)
        connection.execute("DELETE FROM selftest_budget_scopes WHERE expires_at<=?", (now,))
        existing = connection.execute(
            "SELECT * FROM selftest_budget_scopes WHERE parent_batch_key=? AND nonce=?",
            (scope.parent_batch_key, scope.nonce),
        ).fetchone()
        epoch = self._epoch(connection)
        if existing is not None:
            if (
                existing["budget_limit"] != scope.limit
                or existing["fixture_digest"] != config.fixture_digest
                or existing["registration_epoch"] != epoch
                or (scope.expires_at is not None and existing["expires_at"] != expires)
            ):
                raise FixtureError("FIXTURE_BUDGET_SCOPE_CONFLICT", "预算作用域不可变更", 409)
            return
        count = connection.execute("SELECT count(*) FROM selftest_budget_scopes").fetchone()[0]
        if int(count) >= 128:
            raise FixtureError("FIXTURE_BUDGET_CAPACITY_EXCEEDED", "活跃预算作用域容量已满", 429)
        connection.execute(
            "INSERT INTO selftest_budget_scopes("
            "parent_batch_key,nonce,budget_limit,fixture_digest,registration_epoch,expires_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                scope.parent_batch_key,
                scope.nonce,
                scope.limit,
                config.fixture_digest,
                epoch,
                expires,
            ),
        )

    def _reserve(self, batch: str, scenario: str) -> str:
        rejected = False
        with self._transaction() as connection:
            row = self._fixture(connection, batch, scenario)
            if row["expires_at"] <= self._clock():
                raise FixtureError("FIXTURE_EXPIRED", "合成场景已到期", 410)
            config = FixtureConfiguration.model_validate_json(row["configuration"])
            scope = config.budget_scope or BudgetScope(parent_batch_key=batch, nonce=config.nonce)
            budget = self._budget(connection, scope)
            if budget["expires_at"] <= self._clock():
                raise FixtureError("FIXTURE_BUDGET_EXPIRED", "合成预算已到期", 410)
            rejected = int(budget["admitted_count"]) >= int(budget["budget_limit"])
            connection.execute(
                "UPDATE selftest_budget_scopes SET admitted_count=admitted_count+?, "
                "rejected_count=rejected_count+? WHERE parent_batch_key=? AND nonce=?",
                (int(not rejected), int(rejected), scope.parent_batch_key, scope.nonce),
            )
            identity = self._generation(connection, batch, scenario)
        if rejected:
            raise FixtureError("FIXTURE_SIDE_EFFECT_BUDGET_EXHAUSTED", "合成处理预算已耗尽", 429)
        return identity

    @staticmethod
    def _budget(connection: sqlite3.Connection, scope: BudgetScope) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM selftest_budget_scopes WHERE parent_batch_key=? AND nonce=?",
            (scope.parent_batch_key, scope.nonce),
        ).fetchone()
        if row is None:
            raise FixtureError("FIXTURE_BUDGET_MISSING", "合成预算缺失", 410)
        return cast(sqlite3.Row, row)

    def _budget_receipt(
        self, connection: sqlite3.Connection, batch: str, config: FixtureConfiguration
    ) -> BudgetReceipt:
        scope = config.budget_scope or BudgetScope(parent_batch_key=batch, nonce=config.nonce)
        row = self._budget(connection, scope)
        return BudgetReceipt(
            **scope.model_dump(exclude={"expires_at"}),
            admitted_count=int(row["admitted_count"]),
            rejected_count=int(row["rejected_count"]),
            fixture_digest=str(row["fixture_digest"]),
            registration_epoch=str(row["registration_epoch"]),
            expires_at=float(row["expires_at"]),
        )

    def remove(
        self,
        batch: str,
        scenario: str,
        *,
        condition: FixtureRemovalCondition | None = None,
    ) -> None:
        with self._transaction() as connection:
            if condition is not None:
                self._validate_removal(connection, batch, scenario, condition)
            connection.execute(
                "DELETE FROM selftest_fixtures WHERE batch_key=? AND scenario_id=?",
                (batch, scenario),
            )

    def _validate_removal(
        self,
        connection: sqlite3.Connection,
        batch: str,
        scenario: str,
        condition: FixtureRemovalCondition,
    ) -> None:
        row = self._fixture(connection, batch, scenario)
        config = FixtureConfiguration.model_validate_json(row["configuration"])
        active = connection.execute(
            "SELECT count(*) FROM selftest_request_events "
            "WHERE batch_key=? AND scenario_id=? AND completed_at IS NULL",
            (batch, scenario),
        ).fetchone()[0]
        if (
            config.nonce != condition.expected_nonce
            or self._epoch(connection) != condition.expected_fixture_epoch
            or self._generation(connection, batch, scenario)
            != condition.expected_registration_epoch
            or int(active) != 0
        ):
            raise FixtureError(
                "FIXTURE_DELETE_PRECONDITION_MISMATCH",
                "命名空间归属、epoch 或活动请求已变化",
                409,
            )

    def record(
        self,
        batch: str,
        scenario: str,
        payload: SyntheticRequest,
        *,
        method: str,
        authorization_present: bool,
        cookie_present: bool,
        operation: FixtureOperation = "request",
        synthetic_precedence_header: SyntheticHeaderSnapshot | None = None,
        synthetic_cookie: SyntheticCookieSnapshot | None = None,
        binary_request: BinaryResponseSnapshot | None = None,
    ) -> FixtureReply:
        reservation = self._reserve(batch, scenario)
        with self._transaction() as connection:
            row = self._fixture(connection, batch, scenario)
            if reservation != self._generation(connection, batch, scenario):
                raise FixtureError("FIXTURE_RESERVATION_CHANGED", "合成场景预约已变化", 409)
            if row["expires_at"] <= self._clock():
                raise FixtureError("FIXTURE_EXPIRED", "合成场景已到期", 410)
            config = FixtureConfiguration.model_validate_json(row["configuration"])
            sequence = int(row["request_count"]) + 1
            if sequence > 10_000:
                raise FixtureError("FIXTURE_REQUEST_LIMIT", "合成请求预算已耗尽", 429)
            epoch = self._epoch(connection)
            body = SyntheticResponse(
                **config.response_body.model_dump(exclude={"value"}),
                value=payload.value
                if "value" in payload.model_fields_set
                else config.response_body.value,
                marker=payload.marker,
                branch=payload.branch,
                iteration_key=payload.iteration_key,
                request_count=sequence,
                fixture_epoch=epoch,
            )
            response_status = config.response_statuses[
                min(sequence - 1, len(config.response_statuses) - 1)
            ]
            entry = JournalEntry(
                sequence=sequence,
                method=method,
                path=f"/selftest/{batch}/{scenario}/{operation}",
                response_status=response_status,
                marker=payload.marker,
                request_body=payload,
                response_body=None if operation == "download" else body,
                binary_response=BinaryResponseSnapshot(
                    size_bytes=len(SYNTHETIC_FILE_BYTES),
                    sha256=hashlib.sha256(SYNTHETIC_FILE_BYTES).hexdigest(),
                    content_type="application/octet-stream",
                    filename="flowtest.bin",
                )
                if operation == "download"
                else None,
                authorization_present=authorization_present,
                cookie_present=cookie_present,
                fixture_epoch=epoch,
                received_at=self._clock(),
                synthetic_precedence_header=synthetic_precedence_header,
                synthetic_cookie=synthetic_cookie,
                binary_request=binary_request,
            )
            self._append(connection, row, config, entry)
            request_id = self._begin(connection, batch, scenario, sequence)
            return FixtureReply(body, response_status, config.delay_ms, request_id)

    def _begin(
        self, connection: sqlite3.Connection, batch: str, scenario: str, sequence: int
    ) -> str:
        active = connection.execute(
            "SELECT count(*) FROM selftest_request_events "
            "WHERE batch_key=? AND scenario_id=? AND completed_at IS NULL",
            (batch, scenario),
        ).fetchone()[0]
        if int(active) >= 500:
            raise FixtureError("FIXTURE_CONCURRENCY_LIMIT", "合成目标并发预算已耗尽", 429)
        request_id = str(uuid4())
        connection.execute(
            "INSERT INTO selftest_request_events("
            "request_id,batch_key,scenario_id,sequence,started_at,active_at_begin) "
            "VALUES (?,?,?,?,?,?)",
            (request_id, batch, scenario, sequence, self._clock(), int(active) + 1),
        )
        return request_id

    def finish(self, request_id: str, outcome: Literal["completed", "cancelled", "failed"]) -> bool:
        with self._transaction() as connection:
            updated = connection.execute(
                "UPDATE selftest_request_events SET completed_at=?,outcome=? "
                "WHERE request_id=? AND completed_at IS NULL",
                (self._clock(), outcome, request_id),
            )
            return updated.rowcount == 1

    @staticmethod
    def _metrics(
        connection: sqlite3.Connection, batch: str, scenario: str, total: int
    ) -> FixtureMetrics:
        rows = connection.execute(
            "SELECT request_id,sequence,started_at,completed_at,outcome,active_at_begin "
            "FROM selftest_request_events WHERE batch_key=? AND scenario_id=? "
            "ORDER BY sequence LIMIT 500",
            (batch, scenario),
        ).fetchall()
        events = [FixtureRequestEvent.model_validate(dict(row)) for row in rows]
        return FixtureMetrics(
            events=events,
            complete=len(events) == total
            and all(event.completed_at is not None for event in events),
            active_count=sum(event.completed_at is None for event in events),
            peak_concurrency=max((event.active_at_begin for event in events), default=0),
            completed_count=sum(event.outcome == "completed" for event in events),
            cancelled_count=sum(event.outcome == "cancelled" for event in events),
            failed_count=sum(event.outcome == "failed" for event in events),
        )

    @staticmethod
    def _append(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        config: FixtureConfiguration,
        entry: JournalEntry,
    ) -> None:
        encoded = entry.model_dump_json(exclude_unset=True)
        size = len(encoded.encode())
        truncated = bool(row["truncated"])
        truncated = truncated or entry.sequence > config.max_entries
        truncated = truncated or int(row["stored_bytes"]) + size > config.max_bytes
        stored_bytes = int(row["stored_bytes"])
        if not truncated:
            connection.execute(
                "INSERT INTO selftest_receipts VALUES (?,?,?,?)",
                (row["batch_key"], row["scenario_id"], entry.sequence, encoded),
            )
            stored_bytes += size
        connection.execute(
            """UPDATE selftest_fixtures SET request_count=?,stored_bytes=?,truncated=?
               WHERE batch_key=? AND scenario_id=?""",
            (
                entry.sequence,
                stored_bytes,
                int(truncated),
                row["batch_key"],
                row["scenario_id"],
            ),
        )

    def journal(
        self, batch: str, scenario: str, *, after_sequence: int = 0, limit: int = 100
    ) -> FixtureJournal:
        with self._transaction() as connection:
            row = self._fixture(connection, batch, scenario)
            config = FixtureConfiguration.model_validate_json(row["configuration"])
            records = connection.execute(
                """SELECT sequence,payload FROM selftest_receipts
                   WHERE batch_key=? AND scenario_id=? AND sequence>? ORDER BY sequence LIMIT ?""",
                (batch, scenario, after_sequence, limit + 1),
            ).fetchall()
            entries = [
                JournalEntry.model_validate_json(item["payload"]) for item in records[:limit]
            ]
            epoch = self._epoch(connection)
            changed = str(row["registration_epoch"]) != epoch
            return FixtureJournal(
                batch_key=batch,
                scenario_id=scenario,
                nonce=config.nonce,
                fixture_digest=config.fixture_digest,
                fixture_epoch=epoch,
                registration_epoch=self._generation(connection, batch, scenario),
                request_count=int(row["request_count"]),
                entries=entries,
                truncated=bool(row["truncated"]) or changed,
                expired=row["expires_at"] <= self._clock(),
                epoch_changed=changed,
                next_sequence=entries[-1].sequence if len(records) > limit else None,
                expires_at=float(row["expires_at"]),
                metrics=self._metrics(connection, batch, scenario, int(row["request_count"])),
                budget=self._budget_receipt(connection, batch, config),
            )
