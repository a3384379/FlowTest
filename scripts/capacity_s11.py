#!/usr/bin/env python3
"""Run the reproducible S11 API capacity gate against a live Compose stack."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass
from time import perf_counter

import httpx


@dataclass(frozen=True, slots=True)
class CapacityResult:
    requests: int
    concurrency: int
    failures: int
    duration_seconds: float
    throughput_per_second: float
    p95_seconds: float


async def main() -> None:
    requests = int(os.getenv("FLOWTEST_CAPACITY_REQUESTS", "300"))
    concurrency = int(os.getenv("FLOWTEST_CAPACITY_CONCURRENCY", "30"))
    p95_limit = float(os.getenv("FLOWTEST_CAPACITY_P95_SECONDS", "0.5"))
    target = os.getenv("FLOWTEST_API_URL", "http://localhost:8000/api/v1") + "/live"
    result = await run_capacity(target, requests=requests, concurrency=concurrency)
    print(json.dumps(asdict(result), sort_keys=True))
    if result.failures or result.p95_seconds > p95_limit:
        raise RuntimeError(
            f"capacity gate failed: failures={result.failures}, p95={result.p95_seconds:.3f}s"
        )


async def run_capacity(
    target: str, *, requests: int, concurrency: int
) -> CapacityResult:
    if requests < 1 or not 1 <= concurrency <= requests:
        raise ValueError(
            "requests and concurrency must define a positive bounded workload"
        )
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    failures = 0

    limits = httpx.Limits(
        max_connections=concurrency,
        max_keepalive_connections=concurrency,
    )
    async with httpx.AsyncClient(timeout=5, limits=limits) as client:

        async def warm_connection_pool() -> None:
            """Exclude one-time TCP pool creation from the steady-state API gate."""
            responses = await asyncio.gather(
                *(client.get(target) for _ in range(concurrency))
            )
            if any(response.status_code != 200 for response in responses):
                raise RuntimeError("capacity warm-up failed")

        await warm_connection_pool()

        async def issue_request() -> bool:
            async with semaphore:
                started = perf_counter()
                try:
                    response = await client.get(target)
                    return response.status_code == 200
                finally:
                    latencies.append(perf_counter() - started)

        started = perf_counter()
        results = await asyncio.gather(*(issue_request() for _ in range(requests)))
        duration = perf_counter() - started
        failures = sum(not item for item in results)

    ordered = sorted(latencies)
    p95_index = max(0, min(len(ordered) - 1, round(len(ordered) * 0.95) - 1))
    return CapacityResult(
        requests=requests,
        concurrency=concurrency,
        failures=failures,
        duration_seconds=round(duration, 6),
        throughput_per_second=round(requests / duration, 2),
        p95_seconds=round(ordered[p95_index], 6),
    )


if __name__ == "__main__":
    asyncio.run(main())
