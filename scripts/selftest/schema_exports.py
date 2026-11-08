"""Versioned JSON Schema exports for the additional frozen H/O contracts."""

from pathlib import Path

from scripts.selftest.auth_expiry import AuthExpiryResult
from scripts.selftest.canary_replay import CanaryPack, CanaryReport
from scripts.selftest.ci_extended import ExtendedReceipt
from scripts.selftest.compile_boundary_contracts import (
    CompileBoundaryEvidence,
    CompileBoundaryManifest,
    CompileBoundaryReport,
)
from scripts.selftest.contract_delta_contracts import (
    DeltaEvidence,
    DeltaManifest,
    DeltaReport,
)
from scripts.selftest.contracts import (
    BatchEvidence,
    BatchManifest,
    Contract,
    GenerationProvenance,
    VerificationReport,
)
from scripts.selftest.initialization_contracts import InitializationResult
from scripts.selftest.io import write_json
from scripts.selftest.local_stack import ROOT
from scripts.selftest.native_control_contracts import (
    NativeControlEvidence,
    NativeControlManifest,
    NativeControlReport,
)
from scripts.selftest.product_boundary_contracts import (
    ProductBoundaryEvidence,
    ProductBoundaryManifest,
    ProductBoundaryPack,
    ProductBoundaryReport,
)
from scripts.selftest.quality_contracts import (
    QualityEvidence,
    QualityManifest,
    QualityPack,
)
from scripts.selftest.quality_verify import QualityReport
from scripts.selftest.review_boundary_contracts import ReviewEvidence, ReviewManifest
from scripts.selftest.review_boundary_verify import ReviewReport
from scripts.selftest.runtime_faults import FrozenRuntimeBatch, RuntimePackReport
from scripts.selftest.security_boundary_contracts import BoundaryResult
from scripts.selftest.semantic_contracts import (
    SemanticEvidence,
    SemanticManifest,
    SemanticReport,
)
from scripts.selftest.worker_fault_contracts import (
    WorkerEvidence,
    WorkerManifest,
    WorkerPack,
    WorkerReport,
)

SCHEMAS: tuple[tuple[str, type[Contract]], ...] = (
    ("compile-boundary-manifest-v1", CompileBoundaryManifest),
    ("compile-boundary-evidence-v1", CompileBoundaryEvidence),
    ("compile-boundary-verification-v1", CompileBoundaryReport),
    ("product-boundary-pack-v1", ProductBoundaryPack),
    ("product-boundary-manifest-v1", ProductBoundaryManifest),
    ("product-boundary-evidence-v1", ProductBoundaryEvidence),
    ("product-boundary-verification-v1", ProductBoundaryReport),
    ("observer-canary-pack-v1", CanaryPack),
    ("observer-canary-verification-v1", CanaryReport),
    ("manifest", BatchManifest),
    ("evidence", BatchEvidence),
    ("verification", VerificationReport),
    ("generation-provenance", GenerationProvenance),
    ("worker-fault-pack-v1", WorkerPack),
    ("worker-fault-manifest-v1", WorkerManifest),
    ("worker-fault-evidence-v1", WorkerEvidence),
    ("worker-fault-verification-v1", WorkerReport),
    ("quality-pack-v1", QualityPack),
    ("quality-manifest-v1", QualityManifest),
    ("quality-evidence-v1", QualityEvidence),
    ("quality-verification-v1", QualityReport),
    ("review-recovery-manifest-v1", ReviewManifest),
    ("review-recovery-evidence-v1", ReviewEvidence),
    ("review-recovery-verification-v1", ReviewReport),
    ("security-boundaries-result-v1", BoundaryResult),
    ("initialization-boundaries-result-v1", InitializationResult),
    ("auth-expiry-result-v1", AuthExpiryResult),
    ("native-control-manifest-v1", NativeControlManifest),
    ("native-control-evidence-v1", NativeControlEvidence),
    ("native-control-verification-v1", NativeControlReport),
    ("contract-delta-manifest-v1", DeltaManifest),
    ("contract-delta-evidence-v1", DeltaEvidence),
    ("contract-delta-verification-v1", DeltaReport),
    ("semantic-review-manifest-v1", SemanticManifest),
    ("semantic-review-evidence-v1", SemanticEvidence),
    ("semantic-review-verification-v1", SemanticReport),
    ("ci-extended-receipt-v1", ExtendedReceipt),
)


def export(directory: Path) -> None:
    for name, model in SCHEMAS:
        write_json(
            directory / f"{name}.schema.json",
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                **model.model_json_schema(),
            },
        )
    runtime = ROOT / "selftest/packs/runtime-faults-v1"
    for name, model in (
        ("batch-manifest.schema.json", FrozenRuntimeBatch),
        ("verification-report.schema.json", RuntimePackReport),
    ):
        write_json(runtime / name, model.model_json_schema())


if __name__ == "__main__":
    export(ROOT / "selftest/schemas")
