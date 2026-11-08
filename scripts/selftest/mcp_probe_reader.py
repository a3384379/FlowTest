"""Bounded public metadata reader and independent complete-snapshot checks."""

import asyncio
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from pydantic import ValidationError
from scripts.selftest.io import HarnessError
from scripts.selftest.mcp_probe_contracts import (
    ProbeAuthority,
    ProbePage,
    ProbeSnapshot,
    probe_kinds,
    snapshot_digest,
)


def _identity(page: ProbePage, authority: ProbeAuthority) -> bool:
    keys = (
        "probe_id",
        "binding_id",
        "binding_fingerprint",
        "manifest_digest",
        "source_digest",
        "runtime_profile",
        "builds",
        "expires_at",
    )
    projects = {(r.project_id, r.organization_id) for r in page.covered_projects}
    expected = {(r.project_id, r.organization_id) for r in authority.fixtures}
    return (
        all(getattr(page, key) == getattr(authority, key) for key in keys)
        and projects == expected
        and len(projects) == len(page.covered_projects)
        and set(page.covered_kinds) == probe_kinds()
        and len(set(page.covered_kinds)) == len(page.covered_kinds)
    )


def validate_snapshot(
    authority: ProbeAuthority, snapshot: ProbeSnapshot, *, now: datetime | None = None
) -> None:
    current = now or datetime.now(UTC)
    if not authority.issued_at <= current < authority.expires_at:
        raise HarnessError("SELFTEST_PROBE_AUTHORITY_EXPIRED")
    rows = snapshot.resources
    identities = [(row.kind, str(row.id)) for row in rows]
    if len(set(identities)) != len(identities) or identities != sorted(identities):
        raise HarnessError("SELFTEST_PROBE_RESOURCE_SET_MISMATCH")
    if len(rows) > 500:
        raise HarnessError("SELFTEST_PROBE_RESOURCE_LIMIT")
    expected_digest = snapshot_digest(authority, rows)
    offset = 0
    for index, page in enumerate(snapshot.pages):
        _validate_page(authority, page, current)
        offset += len(page.items)
        has_more = index + 1 < len(snapshot.pages)
        expected_cursor = f"{expected_digest}.{offset}" if has_more else None
        if (
            page.total != len(rows)
            or page.snapshot_digest != expected_digest
            or page.has_more != has_more
            or page.next_cursor != expected_cursor
            or (has_more and not page.items)
        ):
            raise HarnessError("SELFTEST_PROBE_PAGINATION_INCOMPLETE")


def _validate_page(authority: ProbeAuthority, page: ProbePage, now: datetime) -> None:
    if not _identity(page, authority):
        raise HarnessError("SELFTEST_PROBE_IDENTITY_MISMATCH")
    if not page.complete or page.reason_codes:
        raise HarnessError("SELFTEST_PROBE_PROJECTION_INCOMPLETE")
    if not authority.issued_at <= page.observed_at <= now < page.expires_at:
        reason = (
            "before_grant"
            if page.observed_at < authority.issued_at
            else "future"
            if page.observed_at > now
            else "expired"
        )
        raise HarnessError("SELFTEST_PROBE_OBSERVATION_TIME_MISMATCH:" + reason)
    projects = {fixture.project_id for fixture in authority.fixtures}
    if any(item.project_id not in projects for item in page.items):
        raise HarnessError("SELFTEST_PROBE_PROJECT_SCOPE_MISMATCH")


class ProbeReader:
    def __init__(
        self,
        api_url: str,
        token: str,
        nonce: str,
        authority: ProbeAuthority,
        reserve_request: Callable[[], bool],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.authority, self.reserve_request = authority, reserve_request
        self.client = httpx.AsyncClient(
            base_url=api_url.rstrip("/") + "/api/v1/",
            headers={
                "Authorization": "Bearer " + token,
                "X-SelfTest-Probe-Nonce": nonce,
                "X-SelfTest-Manifest-Digest": authority.manifest_digest,
            },
            trust_env=False,
            follow_redirects=False,
            timeout=15,
            transport=transport,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _page(self, params: dict[str, str], remaining_bytes: int) -> tuple[ProbePage, int]:
        path = f"agent/self-test-probes/{self.authority.probe_id}/inventory"
        content = bytearray()
        async with self.client.stream("GET", path, params=params) as response:
            if response.status_code != 200:
                raise HarnessError("SELFTEST_PROBE_READ_UNAVAILABLE_OR_OVERSIZED")
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > remaining_bytes:
                    raise HarnessError("SELFTEST_PROBE_READ_UNAVAILABLE_OR_OVERSIZED")
        try:
            page = ProbePage.model_validate(json.loads(content))
        except (ValidationError, ValueError) as error:
            raise HarnessError("SELFTEST_PROBE_RESPONSE_CONTRACT_INVALID") from error
        return page, len(content)

    async def snapshot(self) -> ProbeSnapshot:
        pages: list[ProbePage] = []
        cursor: str | None = None
        size = 0
        for _ in range(5):
            if not self.reserve_request():
                raise HarnessError("SELFTEST_PROBE_HTTP_BUDGET_EXHAUSTED")
            params = {"page_size": "100"}
            if cursor is not None:
                params["cursor"] = cursor
            started = time.monotonic()
            page, read_bytes = await self._page(params, 262144 - size)
            await self._settle_clock(page, time.monotonic() - started)
            size += read_bytes
            _validate_page(self.authority, page, datetime.now(UTC))
            pages.append(page)
            if not page.has_more:
                snapshot = ProbeSnapshot(pages=tuple(pages))
                validate_snapshot(self.authority, snapshot)
                return snapshot
            if page.next_cursor is None or page.next_cursor == cursor:
                raise HarnessError("SELFTEST_PROBE_CURSOR_INVALID")
            cursor = page.next_cursor
        raise HarnessError("SELFTEST_PROBE_PAGE_LIMIT")

    async def _settle_clock(self, page: ProbePage, elapsed: float) -> None:
        # Quarantine the received page until its timestamp is actually in the past.
        # No second request, timestamp rewrite, validator grace or TTL extension.
        now = datetime.now(UTC)
        lead = (page.observed_at - now).total_seconds()
        remaining = (min(page.expires_at, self.authority.expires_at) - now).total_seconds()
        if 0 < lead <= min(elapsed, 0.25, remaining):
            await asyncio.sleep(lead)
