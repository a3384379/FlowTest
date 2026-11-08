"""Frozen finite public-API probe descriptors, separate from native execution packs."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from scripts.selftest.contracts import Contract, Identity, canonical_digest
from scripts.selftest.io import HarnessError, read_json

type BoundaryPackId = Literal[
    "initialization-boundaries-v1", "security-boundaries-v1", "auth-expiry-v1"
]


class BoundaryPack(Contract):
    pack_id: BoundaryPackId
    version: Literal["1.0.0"]
    scenario_ids: tuple[Identity, ...] = Field(min_length=1, max_length=5)
    runtime_seconds: Literal[600]
    request_budget: Literal[500]
    provenance: Literal["local_untrusted"]
    claims_native_execution: Literal[False]
    scope: str = Field(min_length=1, max_length=300)

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


def load_boundary_pack(pack_id: BoundaryPackId, scenarios: tuple[str, ...]) -> BoundaryPack:
    root = Path(__file__).resolve().parents[2]
    pack = BoundaryPack.model_validate(read_json(root / "selftest/packs" / pack_id / "pack.json"))
    if pack.pack_id != pack_id or pack.scenario_ids != scenarios:
        raise HarnessError("SELFTEST_BOUNDARY_FROZEN_DENOMINATOR_MISMATCH")
    return pack
