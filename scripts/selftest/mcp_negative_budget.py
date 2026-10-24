"""Synthetic fixture HTTP admission only; no request headers or bodies are observed."""

import json
import os
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from scripts.selftest.io import HarnessError
from starlette.types import ASGIApp, Receive, Scope, Send


class ProtocolHttpBudget:
    def __init__(self, path: Path, nonce: str, expires_at: float) -> None:
        self.path = path
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS budget(nonce TEXT PRIMARY KEY, "
                "expires_at REAL NOT NULL, "
                "admitted INTEGER NOT NULL DEFAULT 0, rejected INTEGER NOT NULL DEFAULT 0)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS tool_budget(id INTEGER PRIMARY KEY CHECK(id=1), "
                "admitted INTEGER NOT NULL, rejected INTEGER NOT NULL)"
            )
            connection.execute("INSERT OR IGNORE INTO tool_budget VALUES(1,0,0)")
            row = connection.execute("SELECT nonce,expires_at FROM budget").fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO budget(nonce,expires_at) VALUES (?,?)",
                    (nonce, expires_at),
                )
            elif row != (nonce, expires_at):
                raise HarnessError("SELFTEST_PROTOCOL_HTTP_BUDGET_IDENTITY_CHANGED")

    def reserve(self) -> bool:
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT expires_at,admitted FROM budget").fetchone()
            allowed = row[0] > time.time() and int(row[1]) < 500
            connection.execute(
                "UPDATE budget SET admitted=admitted+?,rejected=rejected+?",
                (int(allowed), int(not allowed)),
            )
        return allowed

    def counts(self) -> tuple[int, int]:
        with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as connection:
            row = connection.execute("SELECT admitted,rejected FROM budget").fetchone()
        return int(row[0]), int(row[1])

    def reserve_tool(self) -> bool:
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT tool_budget.admitted,budget.expires_at "
                "FROM tool_budget CROSS JOIN budget WHERE id=1"
            ).fetchone()
            allowed = int(row[0]) < 100 and float(row[1]) > time.time()
            connection.execute(
                "UPDATE tool_budget SET admitted=admitted+?,rejected=rejected+? WHERE id=1",
                (int(allowed), int(not allowed)),
            )
        return allowed

    def tool_counts(self) -> tuple[int, int]:
        with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT admitted,rejected FROM tool_budget WHERE id=1"
            ).fetchone()
        return int(row[0]), int(row[1])


class BudgetedAPI:
    def __init__(self, app: ASGIApp, budget: ProtocolHttpBudget) -> None:
        self.app, self.budget = app, budget

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not self.budget.reserve():
            body = json.dumps(
                {
                    "error": {
                        "code": "SELFTEST_PROTOCOL_HTTP_BUDGET_EXHAUSTED",
                        "trace_id": str(uuid4()),
                    }
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def create_api() -> BudgetedAPI:
    from app.main import create_app

    budget = ProtocolHttpBudget(
        Path(os.environ["FLOWTEST_PROTOCOL_BUDGET_PATH"]),
        os.environ["FLOWTEST_PROTOCOL_BUDGET_NONCE"],
        float(os.environ["FLOWTEST_PROTOCOL_BUDGET_DEADLINE"]),
    )
    return BudgetedAPI(create_app(), budget)
