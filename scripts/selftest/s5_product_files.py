"""Native FlowTest B file lifecycle, with independent exact-project artifact reads."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from scripts.selftest.bootstrap import Installation
from scripts.selftest.contracts import (
    BatchEvidence,
    BatchManifest,
    CreatedFileExpectation,
    RequiredDisposal,
    TargetDisposalReceipt,
    VerificationReport,
    canonical_digest,
)
from scripts.selftest.fixed_baseline import CorePack, load_core_pack
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import ROOT, StackBinding, _verify_removed
from scripts.selftest.native_api_pack import NativeAPIResult, _bind
from scripts.selftest.verify import verify_batch, write_report

PACK = ROOT / "selftest/packs/s5-product-files-v1"
ARTIFACT_PLACEHOLDER = "00000000-0000-4000-8000-000000000801"


async def prepare_pack(
    writer: PublicAPI,
    target_reader: PublicAPI,
    installed: Installation,
    binding: StackBinding,
    batch: str,
    directory: Path,
) -> CorePack:
    if installed.binding_nonce != binding.nonce:
        raise HarnessError("S5_PRODUCT_FILE_BINDING_CHANGED")
    receipt = directory / "source-upload.json"
    if receipt.exists():
        saved = read_json(receipt)
        if saved.get("status") != "completed":
            raise HarnessError("S5_PRODUCT_FILE_SOURCE_UPLOAD_UNKNOWN")
        identity = text_value(saved["artifact_id"])
    else:
        write_json(receipt, {"status": "pending"})
        source = await writer.upload_synthetic_binary(f"/projects/{installed.project_id}/files")
        identity = text_value(source["id"])
        write_json(receipt, {"status": "completed", "artifact_id": identity})
    listing = await target_reader.object(
        "GET", f"/projects/{installed.target_project_id}/files?page=1&page_size=100"
    )
    items = objects_value(listing["items"])
    if (
        listing["total"] != len(items)
        or len(items) > 100
        or any(item["project_id"] != str(installed.target_project_id) for item in items)
    ):
        raise HarnessError("S5_PRODUCT_FILE_BASELINE_INCOMPLETE")
    bindings = {
        ARTIFACT_PLACEHOLDER: identity,
        "00000000-0000-4000-8000-000000000001": str(installed.target_project_id),
        "00000000-0000-4000-8000-000000000002": str(installed.target_organization_id),
        "$B_EMAIL": installed.target_email,
        "$BATCH": batch,
    }
    pack = CorePack.model_validate(_bind(load_core_pack(PACK).model_dump(mode="json"), bindings))
    golden = CreatedFileExpectation(
        project_id=installed.target_project_id,
        created_by_id=installed.target_user_id,
        previous_artifact_ids=tuple(UUID(text_value(item["id"])) for item in items),
        target_origin=binding.target_internal_url.rstrip("/"),
        timestamp_precision="second" if binding.runtime_profile == "standalone" else "microsecond",
        content_utf8="flowtest-download",
        size_bytes=17,
        sha256=hashlib.sha256(b"flowtest-download").hexdigest(),
        content_type="application/octet-stream",
        filename="flowtest.bin",
    )
    disposal = RequiredDisposal(
        project_name=binding.project_name,
        target_container_id=binding.target_container_id,
        target_volume=binding.target_volume,
        target_image=binding.candidate_image_digest,
        binding_nonce=binding.nonce,
    )
    outcome = pack.expectations[0].expected.model_copy(
        update={"created_file": golden, "required_disposal": disposal}
    )
    expected = pack.expectations[0].model_copy(
        update={"expected": outcome, "fixture_batch_key": batch + "-phase-1"}
    )
    documents: dict[str, JsonObject] = {
        "api-definitions.json": {"apis": [item.model_dump(mode="json") for item in pack.apis]},
        "workflows.json": {"workflows": [item.model_dump(mode="json") for item in pack.workflows]},
        "expectations.json": {
            "expectations": [expected.model_dump(mode="json")],
            "fixtures": [item.model_dump(mode="json") for item in pack.fixtures],
        },
    }
    manifest = pack.manifest.model_copy(
        update={"files": {name: canonical_digest(value) for name, value in documents.items()}}
    )
    for name, value in documents.items():
        write_json(directory / "bound-pack" / name, value)
    write_json(directory / "bound-pack/manifest.json", manifest)
    return load_core_pack(directory / "bound-pack")


def finalize(binding: StackBinding, stack: Path, output: Path) -> NativeAPIResult:
    manifest = BatchManifest.model_validate(read_json(output / "manifest.json"))
    evidence = BatchEvidence.model_validate(read_json(output / "evidence.json"))
    original = VerificationReport.model_validate(read_json(output / "verification.json"))
    expected = RequiredDisposal(
        project_name=binding.project_name,
        target_container_id=binding.target_container_id,
        target_volume=binding.target_volume,
        target_image=binding.candidate_image_digest,
        binding_nonce=binding.nonce,
    )
    if (
        manifest.pack_id != "s5-product-files-v1"
        or len(manifest.scenarios) != 1
        or len(evidence.scenarios) != 1
        or (original.batch_key, original.pack_digest) != (manifest.batch_key, manifest.pack_digest)
        or manifest.scenarios[0].expected.required_disposal != expected
        or read_json(stack / "stack.json") != binding.model_dump(mode="json")
        or read_json(stack / "ownership.json")
        != {"project_name": binding.project_name, "nonce": binding.nonce}
        or read_json(stack / "cleanup.json")
        != {"project_name": binding.project_name, "status": "completed"}
    ):
        raise HarnessError("S5_PRODUCT_FILE_DISPOSAL_IDENTITY_CHANGED")
    _verify_removed(binding.project_name)
    now = datetime.now(UTC)
    receipt = TargetDisposalReceipt(
        **expected.model_dump(),
        removed_at=now,
        containers_absent=True,
        volumes_absent=True,
        networks_absent=True,
    )
    if not (output / "evidence.pre-disposal.json").exists():
        write_json(output / "evidence.pre-disposal.json", evidence)
    evidence = evidence.model_copy(
        update={
            "scenarios": (evidence.scenarios[0].model_copy(update={"target_disposal": receipt}),),
            "collected_at": now,
        }
    )
    report = verify_batch(manifest, evidence)
    write_json(output / "evidence.json", evidence)
    write_report(report, output)
    return NativeAPIResult(manifest=manifest, evidence=evidence, report=report, phases=())
