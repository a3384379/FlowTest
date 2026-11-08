"""Bounded HTTP metadata observations are never empty-set or partial-page proof."""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.contracts import Builds
from scripts.selftest.io import HarnessError
from scripts.selftest.mcp_probe_contracts import (
    ProbeAuthority,
    ProbeFixture,
    ProbePage,
    ProbeResource,
    ProbeSnapshot,
    probe_kinds,
    snapshot_digest,
)
from scripts.selftest.mcp_probe_reader import ProbeReader, _validate_page, validate_snapshot


@pytest.mark.parametrize("reason", ["before_grant", "future", "expired"])
def test_invalid_probe_time_is_rejected_with_bounded_diagnostic(authority, reason):
    page = pages(authority, 0)[0]
    now = authority.issued_at + timedelta(seconds=2)
    observed = now
    if reason == "before_grant":
        observed = authority.issued_at - timedelta(microseconds=1)
    elif reason == "future":
        observed = now + timedelta(microseconds=1)
    else:
        now = authority.expires_at
    page = page.model_copy(update={"observed_at": observed})
    with pytest.raises(HarnessError, match="OBSERVATION_TIME_MISMATCH:" + reason):
        _validate_page(authority, page, now)


@pytest.fixture
def authority() -> ProbeAuthority:
    now = datetime.now(UTC)
    return ProbeAuthority(
        probe_id=uuid4(),
        binding_id=uuid4(),
        binding_fingerprint="1" * 64,
        manifest_digest="2" * 64,
        source_digest="3" * 64,
        runtime_profile="standalone",
        builds=Builds(runner="candidate", target="target", fixture="mock", verifier="O"),
        fixtures=tuple(ProbeFixture(project_id=uuid4(), organization_id=uuid4()) for _ in range(2)),
        owner_user_id=uuid4(),
        reviewer_user_id=uuid4(),
        machine_account_ids=(uuid4(),),
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(seconds=599),
    )


def pages(authority: ProbeAuthority, count: int) -> list[ProbePage]:
    rows = tuple(
        sorted(
            (
                ProbeResource(
                    kind="workflow",
                    id=uuid4(),
                    project_id=authority.fixtures[0].project_id,
                    status="draft",
                )
                for _ in range(count)
            ),
            key=lambda row: (row.kind, str(row.id)),
        )
    )
    digest = snapshot_digest(authority, rows)
    result = []
    for offset in range(0, max(1, len(rows)), 100):
        more = offset + 100 < len(rows)
        result.append(
            ProbePage(
                probe_id=authority.probe_id,
                purpose="mcp_governance_negative",
                execution_scope="governance_negative_only",
                provenance="local_untrusted",
                binding_id=authority.binding_id,
                binding_fingerprint=authority.binding_fingerprint,
                manifest_digest=authority.manifest_digest,
                source_digest=authority.source_digest,
                runtime_profile=authority.runtime_profile,
                builds=authority.builds,
                covered_projects=authority.fixtures,
                covered_kinds=tuple(sorted(probe_kinds())),
                items=rows[offset : offset + 100],
                total=len(rows),
                next_cursor=f"{digest}.{offset + 100}" if more else None,
                has_more=more,
                complete=True,
                reason_codes=(),
                snapshot_digest=digest,
                observed_at=datetime.now(UTC),
                expires_at=authority.expires_at,
            )
        )
    return result


def test_reader_collects_complete_201_resource_three_page_snapshot_exactly(
    authority: ProbeAuthority,
) -> None:
    captured = pages(authority, 201)
    requests = []

    def serve(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=captured[len(requests) - 1].model_dump(mode="json"))

    async def execute() -> None:
        reader = ProbeReader(
            "http://owned-api",
            "synthetic-O-jwt",
            "nonce",
            authority,
            lambda: True,
            transport=httpx.MockTransport(serve),
        )
        try:
            snapshot = await reader.snapshot()
        finally:
            await reader.close()
        assert len(snapshot.resources) == 201 and len(snapshot.pages) == 3

    asyncio.run(execute())
    assert len(requests) == 3
    assert requests[0].url.path == f"/api/v1/agent/self-test-probes/{authority.probe_id}/inventory"
    assert all(
        request.headers["X-SelfTest-Manifest-Digest"] == authority.manifest_digest
        for request in requests
    )
    assert all(request.headers["Authorization"] == "Bearer synthetic-O-jwt" for request in requests)


def _time_mutations(captured: list[ProbePage], authority: ProbeAuthority, mutation: str) -> None:
    first = captured[0]
    if mutation == "changed_page":
        captured[1] = captured[1].model_copy(update={"total": 102})
    elif mutation == "wrong_expiry":
        captured[0] = first.model_copy(
            update={"expires_at": authority.expires_at + timedelta(seconds=1)}
        )
    elif mutation == "page_expired":
        captured[0] = first.model_copy(
            update={"observed_at": authority.issued_at - timedelta(seconds=1)}
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_page",
        "duplicate",
        "subset_kinds",
        "wrong_project",
        "wrong_build",
        "incomplete",
        "wrong_digest",
        "changed_page",
        "wrong_expiry",
        "page_expired",
    ],
)
def test_snapshot_cannot_hide_missing_scope_page_resource_or_identity(
    authority: ProbeAuthority, mutation: str
) -> None:
    captured = pages(authority, 101)
    first = captured[0]
    if mutation == "missing_page":
        captured.pop()
    elif mutation == "duplicate":
        captured[1] = captured[1].model_copy(update={"items": first.items[:1]})
    elif mutation == "subset_kinds":
        captured[0] = first.model_copy(update={"covered_kinds": first.covered_kinds[:-1]})
    elif mutation == "wrong_project":
        captured[0] = first.model_copy(
            update={
                "items": (
                    first.items[0].model_copy(update={"project_id": uuid4()}),
                    *first.items[1:],
                )
            }
        )
    elif mutation == "wrong_build":
        captured[0] = first.model_copy(
            update={"builds": first.builds.model_copy(update={"runner": "different"})}
        )
    elif mutation == "incomplete":
        captured[0] = first.model_copy(update={"complete": False})
    elif mutation == "wrong_digest":
        captured[0] = first.model_copy(update={"snapshot_digest": "0" * 64})
    _time_mutations(captured, authority, mutation)
    with pytest.raises(HarnessError):
        validate_snapshot(authority, ProbeSnapshot(pages=tuple(captured)))


@pytest.mark.parametrize(
    "response",
    ["unknown_field", "over_budget", "truncated", "bad_cursor", "oversized", "wrong_snapshot"],
)
def test_reader_rejects_unsafe_http_projection_and_never_retries(
    authority: ProbeAuthority, response: str
) -> None:
    page = pages(authority, 0)[0].model_dump(mode="json")
    if response == "unknown_field":
        page["raw_payload"] = "synthetic-never-export"
    elif response == "truncated":
        page.update(complete=False, reason_codes=["PROJECTION_TRUNCATED"])
    elif response == "bad_cursor":
        page.update(has_more=True, next_cursor=None)
    elif response == "oversized":
        page["unsupported"] = "x" * 262144
    elif response == "wrong_snapshot":
        page["snapshot_digest"] = "0" * 64
    calls = []

    def serve(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=page)

    async def execute() -> None:
        reader = ProbeReader(
            "http://owned",
            "O",
            "nonce",
            authority,
            lambda: response != "over_budget",
            transport=httpx.MockTransport(serve),
        )
        try:
            with pytest.raises(HarnessError):
                await reader.snapshot()
        finally:
            await reader.close()

    asyncio.run(execute())
    assert len(calls) == (0 if response == "over_budget" else 1)


@pytest.mark.asyncio
async def test_transport_defers_small_clock_lead_without_retry_or_timestamp_rewrite(authority):
    original = pages(authority, 0)[0]
    served = []

    async def serve(request):
        await asyncio.sleep(0.1)
        page = original.model_copy(
            update={"observed_at": datetime.now(UTC) + timedelta(milliseconds=40)}
        )
        served.append(page)
        return httpx.Response(200, json=page.model_dump(mode="json"))

    reader = ProbeReader(
        "http://owned", "O", "nonce", authority, lambda: True, transport=httpx.MockTransport(serve)
    )
    try:
        snapshot = await reader.snapshot()
    finally:
        await reader.close()
    assert len(served) == 1
    assert snapshot.pages[0].observed_at == served[0].observed_at
    assert snapshot.pages[0].observed_at <= datetime.now(UTC)


@pytest.mark.asyncio
async def test_transport_rejects_future_beyond_observed_roundtrip_without_retry(authority):
    served = []

    async def serve(request):
        await asyncio.sleep(0.01)
        page = pages(authority, 0)[0].model_copy(
            update={"observed_at": datetime.now(UTC) + timedelta(seconds=5)}
        )
        served.append(page)
        return httpx.Response(200, json=page.model_dump(mode="json"))

    reader = ProbeReader(
        "http://owned", "O", "nonce", authority, lambda: True, transport=httpx.MockTransport(serve)
    )
    try:
        with pytest.raises(HarnessError, match="OBSERVATION_TIME_MISMATCH:future"):
            await reader.snapshot()
    finally:
        await reader.close()
    assert len(served) == 1
