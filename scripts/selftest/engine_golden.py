"""Run the independently frozen Schema/Header/file/status/empty-loop native pack."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from scripts.selftest.contracts import Builds
from scripts.selftest.fixed_baseline import (
    CorePack,
    FixedResult,
    execute_fixed_baseline,
    load_core_pack,
)
from scripts.selftest.io import PublicAPI

PACK_DIRECTORY = Path(__file__).resolve().parents[2] / "selftest/packs/engine-golden-v1"


def load_engine_golden_pack() -> CorePack:
    return load_core_pack(PACK_DIRECTORY)


async def execute_engine_golden(
    api: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    *,
    project_id: str,
    environment_id: str,
    service_id: str,
    batch_key: str,
    nonce: str,
    fixture_digest: str,
    builds: Builds,
    output_dir: Path,
    deadline: datetime,
) -> FixedResult:
    return await execute_fixed_baseline(
        api,
        reader,
        observer,
        project_id=project_id,
        environment_id=environment_id,
        service_id=service_id,
        batch_key=batch_key,
        nonce=nonce,
        fixture_digest=fixture_digest,
        builds=builds,
        output_dir=output_dir,
        pack=load_engine_golden_pack(),
        deadline=deadline,
    )
