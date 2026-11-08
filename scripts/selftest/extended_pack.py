"""Additional native control scenarios, separate from the eight-case compatibility pack.

Use ``execute_fixed_baseline(..., pack=load_extended_pack())``. Golden files are
frozen before installation; neither this loader nor the Observer learns outcomes
from the candidate. A caller must use a fresh batch namespace and isolated target.
"""

from pathlib import Path

from scripts.selftest.fixed_baseline import CorePack, load_core_pack
from scripts.selftest.io import HarnessError

EXTENDED_DIRECTORY = Path(__file__).resolve().parents[2] / "selftest" / "packs" / "extended-v1"


def load_extended_pack(directory: Path = EXTENDED_DIRECTORY) -> CorePack:
    pack = load_core_pack(directory)
    if pack.manifest.pack_id != "extended-v1":
        raise HarnessError("SELFTEST_EXTENDED_PACK_ID_MISMATCH")
    return pack
