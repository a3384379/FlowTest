"""The CLI shares a frozen fixture allowance before registering any namespace."""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.contracts import FixtureBudgetScope
from scripts.selftest.io import HarnessError, PublicAPI
from scripts.selftest.run import _configure


async def test_canaries_register_the_same_absolute_parent_budget() -> None:
    registrations: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            registrations.append(json.loads(request.content))
            return httpx.Response(204)
        return httpx.Response(
            200,
            json={
                "request_count": 0,
                "truncated": False,
                "expired": False,
                "fixture_epoch": "epoch",
            },
        )

    scope = FixtureBudgetScope(
        parent_batch_key="frozen-parent",
        nonce="frozen-nonce",
        expires_at=(datetime.now(UTC) + timedelta(seconds=550)).timestamp(),
    )
    api = PublicAPI("http://observer", api_prefix="", transport=httpx.MockTransport(respond))
    try:
        for scenario in ("ST-MCP-025", "ST-MCP-026"):
            await _configure(api, "frozen-parent", scenario, scope.nonce, "a" * 64, scope=scope)
    finally:
        await api.close()
    assert len(registrations) == 2
    assert all(item["budget_scope"] == scope.model_dump(mode="json") for item in registrations)
    assert all(0 < item["ttl_seconds"] <= 550 for item in registrations)


@pytest.mark.parametrize("mutation", ["expired", "nonce", "extended"])
async def test_invalid_frozen_budget_is_rejected_before_fixture_registration(mutation: str) -> None:
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        return httpx.Response(204)

    scope = FixtureBudgetScope(
        parent_batch_key="frozen-parent",
        nonce="other" if mutation == "nonce" else "frozen-nonce",
        expires_at=(
            datetime.now(UTC)
            + timedelta(
                seconds=-10 if mutation == "expired" else 900 if mutation == "extended" else 550
            )
        ).timestamp(),
    )
    api = PublicAPI("http://observer", api_prefix="", transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(HarnessError, match="SELFTEST_FIXTURE_BUDGET_INVALID"):
            await _configure(
                api, "frozen-parent", "ST-MCP-025", "frozen-nonce", "a" * 64, scope=scope
            )
    finally:
        await api.close()
    assert requests == []
