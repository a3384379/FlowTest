"""Local-only SDK acceptance; never connect this draft to an existing installation."""

from __future__ import annotations

import argparse
import asyncio
import secrets
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from scripts.selftest.io import HarnessError, write_json
from scripts.selftest.mcp_negative_contracts import (
    ProtocolEvidence,
    ProtocolManifest,
    ProtocolObservation,
)
from scripts.selftest.mcp_negative_fixture import LocalFixture, local_fixture
from scripts.selftest.mcp_negative_runner import freeze, observe
from scripts.selftest.mcp_negative_verify import (
    ProtocolReport,
    verify_protocol,
    write_incomplete_reports,
    write_reports,
)


async def _observations(
    fixture: LocalFixture,
    manifest: ProtocolManifest,
    python: Path,
    backend: Path,
    directory: Path,
) -> tuple[ProtocolObservation, ...]:
    rows: list[ProtocolObservation] = []
    try:
        async with asyncio.timeout((manifest.expires_at - datetime.now(UTC)).total_seconds()):
            for scenario in manifest.scenarios:
                row = await observe(
                    fixture, scenario, python, backend, directory / scenario.scenario_id
                )
                rows.append(row)
                write_json(
                    directory.parent / "public/partial-evidence.json",
                    {
                        "scenarios": [item.model_dump(mode="json") for item in rows],
                    },
                )
    except TimeoutError:
        # The frozen full denominator is unchanged; omitted scenarios remain incomplete.
        pass
    return tuple(rows)


async def run_local(output: Path, python: Path, backend: Path, pack: Path) -> ProtocolReport:
    """Only new loopback processes and a new owned SQLite DB are allowed."""
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        return await _run_owned(output, python, backend, pack)
    except (HarnessError, OSError, TimeoutError, ExceptionGroup, ValidationError, ValueError):
        return write_incomplete_reports(output / "public", "PROTOCOL_FIXTURE_OR_DRIVER_INCOMPLETE")


async def _run_owned(output: Path, python: Path, backend: Path, pack: Path) -> ProtocolReport:
    async with local_fixture(python, backend, output / "private") as fixture:
        manifest = freeze(pack, fixture, batch_key=output.name, nonce=secrets.token_hex(20))
        write_json(output / "public/manifest.json", manifest)
        rows = await _observations(fixture, manifest, python, backend, output / "private")
        admitted, rejected = fixture.budget.counts()
        tools, rejected_tools = fixture.budget.tool_counts()
        evidence = ProtocolEvidence(
            batch_key=manifest.batch_key,
            nonce=manifest.nonce,
            pack_digest=manifest.pack_digest,
            source_digest=manifest.source_digest,
            scenarios=rows,
            collected_at=datetime.now(UTC),
            cleanup_complete=False,
            protocol_attempts=tools,
            http_requests=admitted,
            rejected_http_requests=rejected,
            rejected_tool_calls=rejected_tools,
        )
    # local_fixture closes only its own handles before returning here.
    evidence = evidence.model_copy(
        update={"cleanup_complete": True, "collected_at": datetime.now(UTC)}
    )
    write_json(output / "public/evidence.json", evidence)
    report = verify_protocol(manifest, evidence, pack_path=pack)
    write_reports(report, evidence, output / "public")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="只对新建本地隔离进程运行 SDK 负向验收, 不是 F/C/S 部署验收"
    )
    parser.add_argument("--local-loopback-only", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument(
        "--pack",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "selftest/packs/mcp-negative-v1/pack.json",
    )
    args = parser.parse_args()
    if not args.local_loopback_only or args.output.exists():
        raise HarnessError("SELFTEST_NEW_LOCAL_DIRECTORY_REQUIRED")
    report = asyncio.run(
        run_local(
            args.output.resolve(),
            args.python.absolute(),
            args.backend.resolve(),
            args.pack.resolve(),
        )
    )
    print(f"{report.exit_code}: {args.output / 'public/verification.json'}")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
