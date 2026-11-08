"""Independent draft observer process; authorization only via anonymous stdin pipe."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from scripts.selftest.io import PublicAPI, object_value, text_value, write_json
from scripts.selftest.runtime_faults import read_plan


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deadline", type=float, default=0.1)
    parser.add_argument("--crash", action="store_true")
    args = parser.parse_args()
    auth = object_value(json.loads(sys.stdin.buffer.read(8192)))
    api = PublicAPI(text_value(auth["url"]), text_value(auth["token"]))
    deadline = datetime.now(UTC) + timedelta(seconds=args.deadline)
    try:
        while True:
            snapshot = await read_plan(
                api,
                UUID(text_value(auth["project_id"])),
                UUID(text_value(auth["run_id"])),
            )
            write_json(args.output / "observer-last.json", snapshot)
            if args.crash:
                os._exit(70)
            if datetime.now(UTC) >= deadline:
                write_json(
                    args.output / "observer-result.json",
                    {
                        "status": "incomplete",
                        "exit_code": 2,
                        "reason_code": "OBSERVER_DEADLINE_EXCEEDED",
                        "observed_native_status": snapshot.run.status,
                    },
                )
                return 2
            await asyncio.sleep(0.05)
    finally:
        await api.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
