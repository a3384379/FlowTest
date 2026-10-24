"""Frozen native upload/download and barrier cookie scenarios, separate from MCP generation."""

import base64
import hashlib
from pathlib import Path
from uuid import UUID

from pydantic import JsonValue
from scripts.selftest.contracts import (
    RequiredDisposal,
    ScenarioObservation,
    SyntheticArtifactEvidence,
    SyntheticArtifactExpectation,
    canonical_digest,
)
from scripts.selftest.engine_additional import _replace
from scripts.selftest.fixed_baseline import CorePack, FixedInstallation, load_core_pack
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import ROOT, StackBinding

PACK = ROOT / "selftest/packs/s5-native-v1"
ARTIFACT_PLACEHOLDER = "00000000-0000-4000-8000-000000000801"
SYNTHETIC_CONTENT = b"flowtest-download"


def bind_s5_pack(
    artifact_id: str,
    project_id: str,
    directory: Path,
    disposal: RequiredDisposal | None,
) -> CorePack:
    pack = load_core_pack(PACK)
    golden = SyntheticArtifactExpectation(
        artifact_id=UUID(artifact_id),
        project_id=UUID(project_id),
        content_utf8=SYNTHETIC_CONTENT.decode(),
        size_bytes=len(SYNTHETIC_CONTENT),
        sha256=hashlib.sha256(SYNTHETIC_CONTENT).hexdigest(),
        content_type="application/octet-stream",
        filename="flowtest.bin",
    )
    expected: list[JsonValue] = []
    for index, row in enumerate(pack.expectations):
        update: JsonObject = {}
        if index < 2:
            update["synthetic_artifact"] = golden.model_dump(mode="json")
        if index == 0 and disposal is not None:
            update["required_disposal"] = disposal.model_dump(mode="json")
        outcome = type(row.expected).model_validate(
            {**row.expected.model_dump(mode="json"), **update}
        )
        expected.append(row.model_copy(update={"expected": outcome}).model_dump(mode="json"))
    bindings = {ARTIFACT_PLACEHOLDER: artifact_id}
    documents: dict[str, JsonObject] = {
        "api-definitions.json": {
            "apis": [_replace(item.model_dump(mode="json"), bindings) for item in pack.apis]
        },
        "workflows.json": {"workflows": [item.model_dump(mode="json") for item in pack.workflows]},
        "expectations.json": {
            "expectations": expected,
            "fixtures": [item.model_dump(mode="json") for item in pack.fixtures],
        },
    }
    manifest = pack.manifest.model_copy(
        update={"files": {name: canonical_digest(value) for name, value in documents.items()}}
    )
    for name, value in documents.items():
        write_json(directory / name, value)
    write_json(directory / "manifest.json", manifest)
    return load_core_pack(directory)


async def prepare_s5_native_pack(
    api: PublicAPI, project_id: str, directory: Path, binding: StackBinding
) -> CorePack:
    receipt_path = directory / "synthetic-artifact.json"
    if receipt_path.exists():
        receipt = read_json(receipt_path)
        if receipt.get("status") != "completed" or receipt.get("project_id") != project_id:
            raise HarnessError("S5_FILE_UPLOAD_OUTCOME_UNKNOWN")
        identity = text_value(receipt["artifact_id"])
    else:
        write_json(receipt_path, {"project_id": project_id, "status": "pending"})
        artifact = await api.upload_synthetic_binary(f"/projects/{project_id}/files")
        identity = text_value(artifact["id"])
        if (
            artifact["project_id"] != project_id
            or artifact["sha256"] != hashlib.sha256(SYNTHETIC_CONTENT).hexdigest()
            or artifact["size_bytes"] != len(SYNTHETIC_CONTENT)
            or artifact["content_type"] != "application/octet-stream"
        ):
            raise HarnessError("S5_FILE_UPLOAD_IDENTITY_MISMATCH")
        write_json(
            receipt_path,
            {"project_id": project_id, "artifact_id": identity, "status": "completed"},
        )
    disposal = RequiredDisposal(
        project_name=binding.project_name,
        target_container_id=binding.runner_container_id,
        target_volume=binding.runner_volume,
        target_image=binding.candidate_image_digest,
        binding_nonce=binding.nonce,
    )
    return bind_s5_pack(identity, project_id, directory / "bound-pack", disposal)


async def observe_s5_artifact(
    reader: PublicAPI,
    pack: CorePack,
    installed: FixedInstallation,
    observations: list[ScenarioObservation],
) -> list[ScenarioObservation]:
    expected = pack.expectations[0].expected.synthetic_artifact
    if expected is None or expected.project_id != installed.project_id:
        raise HarnessError("S5_FILE_OBSERVER_SCOPE_MISMATCH")
    content, content_type = await reader.download_synthetic_binary(
        f"/projects/{installed.project_id}/files/{expected.artifact_id}"
    )
    raw: JsonValue = {
        "artifact_id": str(expected.artifact_id),
        "project_id": str(installed.project_id),
        "content_base64": base64.b64encode(content).decode("ascii"),
        "content_type": content_type,
    }
    evidence = SyntheticArtifactEvidence.model_validate(raw)
    return [
        observed.model_copy(update={"synthetic_artifact": evidence}) if index < 2 else observed
        for index, observed in enumerate(observations)
    ]
