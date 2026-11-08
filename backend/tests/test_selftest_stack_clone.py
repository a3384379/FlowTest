"""Exact image reuse checks provenance before creating another owned stack."""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest import stack_clone
from scripts.selftest.io import HarnessError, write_json
from scripts.selftest.local_stack import BuildReceipt
from test_selftest_ci_runner_lineage import binding


def source(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate"
    (candidate / "backend").mkdir(parents=True)
    (candidate / "backend/uv.lock").write_text("frozen")
    receipt = BuildReceipt(
        source_digest="c" * 64,
        candidate_source=str(candidate),
        dependency_digest=hashlib.sha256(b"frozen").hexdigest(),
        candidate_image_digest="sha256:" + "a" * 64,
        fixture_image_digest="sha256:" + "b" * 64,
    )
    current = binding().model_copy(update=receipt.model_dump())
    directory = tmp_path / "source"
    write_json(directory / "stack.json", current)
    write_json(directory / "build-receipt.json", receipt)
    write_json(
        directory / "ownership.json", {"project_name": current.project_name, "nonce": current.nonce}
    )
    monkeypatch.setattr(stack_clone, "_candidate_source", lambda _: candidate)
    monkeypatch.setattr(stack_clone, "source_digest", lambda _: "c" * 64)
    return directory, current, receipt


def test_reuses_only_exact_frozen_images_even_after_source_stack_disposal(tmp_path, monkeypatch):
    directory, current, receipt = source(tmp_path, monkeypatch)
    calls = []

    def docker(arguments):
        calls.append(arguments)
        return arguments[2]

    monkeypatch.setattr(stack_clone, "_docker", docker)
    assert stack_clone.source_receipt(directory) == (current, receipt)
    assert [call[2] for call in calls] == [
        receipt.candidate_image_digest,
        receipt.fixture_image_digest,
    ]
    assert all(call[:2] == ["image", "inspect"] for call in calls)


@pytest.mark.parametrize("mutation", ["receipt", "nonce", "source", "lock", "image"])
def test_rejects_drift_without_creating_destination(tmp_path: Path, monkeypatch, mutation):
    directory, current, receipt = source(tmp_path, monkeypatch)
    if mutation == "receipt":
        write_json(
            directory / "build-receipt.json", receipt.model_copy(update={"source_digest": "0" * 64})
        )
    elif mutation == "nonce":
        write_json(
            directory / "ownership.json", {"project_name": current.project_name, "nonce": "0" * 32}
        )
    elif mutation == "source":
        monkeypatch.setattr(stack_clone, "source_digest", lambda _: "0" * 64)
    elif mutation == "lock":
        (Path(receipt.candidate_source) / "backend/uv.lock").write_text("changed")
    monkeypatch.setattr(
        stack_clone, "_docker", lambda args: "wrong" if mutation == "image" else args[2]
    )
    destination = tmp_path / "new-stack"
    with pytest.raises(HarnessError, match="SELFTEST_CLONE_"):
        stack_clone.start(destination, directory)
    assert not destination.exists()
