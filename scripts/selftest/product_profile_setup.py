"""Activate public H/O configuration on only an owned Full/Compact API container."""

from pathlib import Path

from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.local_stack import StackBinding, _replace_private_environment, verify_binding
from scripts.selftest.profile_stack import ProfileProof, _compose, _freeze


def configure_profile_runner(
    binding: StackBinding,
    directory: Path,
    state: Path,
    private: dict[str, str],
) -> StackBinding:
    verify_binding(binding, directory)
    if binding.runtime_profile not in {"full", "compact"}:
        raise HarnessError("SELFTEST_PRODUCT_PROFILE_REQUIRED")
    previous = ProfileProof.model_validate(read_json(directory / "profile-proof.json"))
    write_json(state / "profile-proof.before.json", previous)
    _replace_private_environment(directory / "private.env", private)
    _compose(
        directory,
        binding.project_name,
        previous.runtime_profile,
        [
            "up",
            "--detach",
            "--no-deps",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "120",
            "runner",
        ],
        timeout=180,
    )
    updated = _freeze(
        directory,
        binding,
        binding.project_name,
        binding.nonce,
        previous.runtime_profile,
        previous.dependencies,
        private,
    )
    current = ProfileProof.model_validate(read_json(directory / "profile-proof.json"))
    retained = {item.role: item for item in previous.containers if item.role != "runner"}
    observed = {item.role: item for item in current.containers if item.role != "runner"}
    if (
        retained != observed
        or current.nonce != previous.nonce
        or current.project_name != previous.project_name
        or current.dependencies != previous.dependencies
        or current.runtime_profile != previous.runtime_profile
        or updated.source_digest != binding.source_digest
        or updated.candidate_image_digest != binding.candidate_image_digest
    ):
        raise HarnessError("SELFTEST_PRODUCT_RECONFIGURATION_RESOURCE_DRIFT")
    verify_binding(updated, directory)
    return updated
