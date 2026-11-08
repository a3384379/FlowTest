"""Create a fresh owned Standalone from an exact existing build receipt, without a rebuild."""

import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path
from uuid import uuid4

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.local_stack import (
    BuildReceipt,
    StackBinding,
    StackOwnership,
    _binding,
    _candidate_source,
    _compose,
    _docker,
    _new_environment,
    source_digest,
    verify_binding,
)
from scripts.selftest.target_auth_policy import freeze_target_auth_policy


def source_receipt(directory: Path) -> tuple[StackBinding, BuildReceipt]:
    source = StackBinding.model_validate(read_json(directory / "stack.json"))
    ownership = StackOwnership.model_validate(read_json(directory / "ownership.json"))
    receipt = BuildReceipt.model_validate(read_json(directory / "build-receipt.json"))
    expected = BuildReceipt.model_validate(source.model_dump(), extra="ignore")
    if (source.project_name, source.nonce) != (
        ownership.project_name,
        ownership.nonce,
    ) or receipt != expected:
        raise HarnessError("SELFTEST_CLONE_SOURCE_RECEIPT_MISMATCH")
    root = _candidate_source(receipt.candidate_source)
    from scripts.selftest.local_stack import ROOT

    if (
        source_digest(root) != receipt.source_digest
        or hashlib.sha256(((root or ROOT) / "backend/uv.lock").read_bytes()).hexdigest()
        != receipt.dependency_digest
    ):
        raise HarnessError("SELFTEST_CLONE_SOURCE_CHANGED")
    for identity in (receipt.candidate_image_digest, receipt.fixture_image_digest):
        if _docker(["image", "inspect", identity, "--format", "{{.Id}}"]) != identity:
            raise HarnessError("SELFTEST_CLONE_IMAGE_MISMATCH")
    return source, receipt


def start(directory: Path, source_directory: Path, *, target_minutes: int = 15) -> StackBinding:
    source, receipt = source_receipt(source_directory)
    project, nonce = f"flowtest-selftest-{secrets.token_hex(6)}", uuid4().hex
    environment = _new_environment(
        receipt.candidate_image_digest, project, nonce, target_access_token_minutes=target_minutes
    )
    environment.update(
        FLOWTEST_SELFTEST_CANDIDATE_IMAGE=receipt.candidate_image_digest,
        FLOWTEST_SELFTEST_FIXTURE_IMAGE=receipt.fixture_image_digest,
    )
    if receipt.candidate_source is not None:
        environment["FLOWTEST_SELFTEST_BUILD_ROOT"] = receipt.candidate_source
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    env_path = directory / "private.env"
    descriptor = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write("".join(f"{key}={value}\n" for key, value in environment.items()))
    write_json(directory / "ownership.json", StackOwnership(project_name=project, nonce=nonce))
    write_json(directory / "build-receipt.json", receipt)
    write_json(
        directory / "source-receipt.json",
        {
            "source_binding_digest": canonical_digest(source.model_dump(mode="json")),
            "build_receipt_digest": canonical_digest(receipt.model_dump(mode="json")),
            "mode": "reuse_exact_images_without_rebuild",
        },
    )
    _compose(
        project,
        env_path,
        ["up", "--detach", "--no-build", "--wait", "--wait-timeout", "120"],
        timeout=180,
        log_path=directory / "start.log",
    )
    binding = _binding(project, nonce, environment, env_path)
    freeze_target_auth_policy(directory, project, nonce, environment)
    verify_binding(binding, directory)
    write_json(directory / "stack.json", binding)
    return binding


def main() -> None:
    parser = argparse.ArgumentParser(description="以固定镜像收据创建新的专用Standalone环境")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--source-stack-directory", type=Path, required=True)
    parser.add_argument("--target-access-token-minutes", type=int, choices=range(1, 61), default=15)
    args = parser.parse_args()
    binding = start(
        args.directory, args.source_stack_directory, target_minutes=args.target_access_token_minutes
    )
    print(json.dumps({"project_name": binding.project_name}))


if __name__ == "__main__":
    main()
