"""Historic wire observations are unit fixtures; current deployed H lineage remains separate."""

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.compile_boundary_contracts import (
    CompileBoundaryEvidence,
    CompileBoundaryManifest,
)
from scripts.selftest.compile_boundary_verify import verify

FIXTURE = Path(__file__).parent / "fixtures/compile_boundary_actual"


def test_compiler_cli_failure_exports_safe_codes_without_claiming_matched_rows(
    tmp_path, monkeypatch, capsys
):
    from scripts.selftest import run_compile_boundaries as entry
    from scripts.selftest.compile_boundary_contracts import CompileBoundaryReport
    from scripts.selftest.compile_boundary_verify import keys
    from scripts.selftest.io import HarnessError, read_json

    output = tmp_path / "compiler"

    async def fail(*args):
        output.mkdir()
        raise ExceptionGroup(
            "synthetic-private-sdk-frame",
            [
                HarnessError("SELFTEST_HTTP_422_SYNTHETIC:trace=synthetic-private-token"),
                RuntimeError("synthetic-private-token"),
            ],
        )

    monkeypatch.setattr(entry, "run", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "entry",
            "--directory",
            str(tmp_path / "owned"),
            "--product",
            str(tmp_path / "product"),
            "--output",
            str(output),
        ],
    )
    assert entry.main() == 2
    report = CompileBoundaryReport.model_validate(read_json(output / "failure.json"))
    assert report.expected_keys == keys() and report.matched_keys == ()
    assert report.reason_codes == ("SELFTEST_HTTP_422_SYNTHETIC", "SELFTEST_RUNTIMEERROR")
    assert report.exit_code == 2 and report.model_calls == 0
    assert "synthetic-private" not in (output / "failure.json").read_text()
    captured = capsys.readouterr()
    assert "synthetic-private" not in captured.out
    assert "synthetic-private-sdk-frame" in captured.err


def test_compiler_cli_refuses_output_replay_without_replacing_failure(tmp_path, monkeypatch):
    from scripts.selftest import run_compile_boundaries as entry

    output = tmp_path / "compiler"
    output.mkdir()
    first = output / "failure.json"
    first.write_bytes(b"first-failure-receipt")

    async def fail(*args):
        raise FileExistsError("synthetic-private-path")

    monkeypatch.setattr(entry, "run", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "entry",
            "--directory",
            str(tmp_path / "owned"),
            "--product",
            str(tmp_path / "product"),
            "--output",
            str(output),
        ],
    )
    assert entry.main() == 1
    assert first.read_bytes() == b"first-failure-receipt"
    assert list(output.iterdir()) == [first]


def test_compiler_finalizer_preserves_first_failure_receipt(tmp_path, monkeypatch):
    from scripts.selftest import run_compile_boundaries as entry
    from scripts.selftest.io import HarnessError

    output = tmp_path / "compiler"
    output.mkdir()
    first = output / "failure.json"
    first.write_bytes(b"first-failure-receipt")

    def fail(*args):
        raise HarnessError("SELFTEST_FINAL_DISPOSAL_INCOMPLETE:trace=synthetic-private-token")

    monkeypatch.setattr(entry, "finalize", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "entry",
            "--directory",
            str(tmp_path / "owned"),
            "--product",
            str(tmp_path / "product"),
            "--output",
            str(output),
            "--finalize-disposable",
        ],
    )
    assert entry.main() == 2
    assert first.read_bytes() == b"first-failure-receipt"
    assert len(list(output.glob("failure-*.json"))) == 1
    assert "synthetic-private" not in next(output.glob("failure-*.json")).read_text()


def inputs():
    return json.loads((FIXTURE / "manifest.json").read_text()), json.loads(
        (FIXTURE / "evidence.json").read_text()
    )


def result(manifest, evidence):
    return verify(
        CompileBoundaryManifest.model_validate(manifest),
        CompileBoundaryEvidence.model_validate(evidence),
    )


def test_real_sdk_control_requires_every_transport_and_both_scopes_without_writes():
    manifest, evidence = inputs()
    report = result(manifest, evidence)
    assert report.exit_code == 0
    assert len(report.expected_keys) == len(report.matched_keys) == 38
    assert 1 <= evidence["http_attempts"] <= 500
    assert evidence["tool_attempts"] == 44
    assert all(
        row["before"] == row["after"] and row["proposal_ids_before"] == row["proposal_ids_after"]
        for row in evidence["observations"]
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "scope_green",
        "foreign_project",
        "asset",
        "proposal",
        "request",
        "falsy",
        "oracle",
        "version",
        "reproducible",
        "receipt",
        "budget",
        "disposal",
    ],
)
def test_zero_summary_cannot_hide_compiler_wire_tampering(change):
    manifest, evidence = inputs()
    rows = {row["transport"] + "/" + row["key"]: row for row in evidence["observations"]}
    row = rows["stdio/positive"]
    payload = row["response"]["scenarios"][0]["executable_payload"]
    request = next(
        node for node in payload["native_definition"]["nodes"] if node["id"] == "request"
    )
    mutations = {
        "missing": lambda: evidence["observations"].pop(),
        "duplicate": lambda: evidence["observations"].__setitem__(-1, row),
        "scope_green": lambda: rows["stdio/scope_read"]["boundary"].__setitem__("is_error", False),
        "foreign_project": lambda: rows["stdio/organization"]["request"].__setitem__(
            "project_id", str(uuid4())
        ),
        "asset": lambda: row["after"]["workflow_ids"].append(str(uuid4())),
        "proposal": lambda: row["proposal_ids_after"].append(str(uuid4())),
        "request": lambda: row["request"].__setitem__("design_fingerprint", "0" * 64),
        "falsy": lambda: request["config"]["request_overrides"]["body"]["value"].__setitem__(
            "flag", 0
        ),
        "oracle": lambda: payload["native_definition"]["nodes"].__setitem__(
            0, {**payload["native_definition"]["nodes"][0], "id": "different"}
        ),
        "version": lambda: row["response"]["resolved_sources"].__setitem__("api_version", 2),
        "reproducible": lambda: rows["stdio/reproducible"]["response"].__setitem__(
            "persisted", True
        ),
        "receipt": lambda: row.__setitem__("calls", []),
        "budget": lambda: evidence.__setitem__("tool_attempts", 1),
        "disposal": lambda: evidence["disposal"].__setitem__("networks_absent", False),
    }
    mutations[change]()
    assert result(manifest, evidence).exit_code == 2


def test_pure_compile_is_not_a_formal_execution_or_a_trusted_required_gate():
    manifest, evidence = inputs()
    evidence["disposal"] = None
    report = result(manifest, evidence)
    assert report.reason_codes == ("OWNED_ASSET_DISPOSAL_PENDING",)
    assert report.model_calls == 0 and report.trust == "local_untrusted"
    assert all(
        row["response"]["execution_status"] == "not_run"
        for row in evidence["observations"]
        if row["response"] is not None
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "published",
        "executed",
        "reviewer",
        "definition",
        "auto_apply",
        "proposal",
        "deep_semantics",
    ],
)
def test_quick_and_flowspec_cannot_hide_publish_run_or_review_boundary_changes(change):
    manifest, evidence = inputs()
    row = evidence["drafts"][0]
    deep = evidence["drafts"][1]
    mutations = {
        "missing": lambda: evidence["drafts"].pop(),
        "published": lambda: row.__setitem__("published_version_count", 1),
        "executed": lambda: row["after"]["execution_ids"].append(str(uuid4())),
        "reviewer": lambda: row.__setitem__("reviewer_id", str(uuid4())),
        "definition": lambda: row.__setitem__("draft_digest", "0" * 64),
        "auto_apply": lambda: row.__setitem__("proposal_applied_before", row["applied_at"]),
        "proposal": lambda: row["proposal_ids_after"].pop(),
        "deep_semantics": lambda: deep.update(
            {"proposed_digest": "0" * 64, "draft_digest": "0" * 64}
        ),
    }
    mutations[change]()
    assert result(manifest, evidence).exit_code == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("expression", "body.unrelated"),
        ("operator", "not_equals"),
        ("source_node_id", "end"),
    ],
)
@pytest.mark.parametrize("node_id", ["assert_status", "assert_schema_1"])
def test_compiler_oracle_must_preserve_field_comparison_and_request_source(field, value, node_id):
    from scripts.selftest.compile_boundary_contracts import CompileBoundaryObservation
    from scripts.selftest.compile_boundary_verify import _ready

    _, evidence = inputs()
    row = next(
        item
        for item in evidence["observations"]
        if item["transport"] == "stdio" and item["key"] == "positive"
    )
    assert _ready(CompileBoundaryObservation.model_validate(row))
    node = next(
        item
        for item in row["response"]["scenarios"][0]["executable_payload"]["native_definition"][
            "nodes"
        ]
        if item["id"] == node_id
    )
    node["config"][field] = value
    assert not _ready(CompileBoundaryObservation.model_validate(row))


@pytest.mark.parametrize("change", ["wrong_api", "wrong_version", "disconnected", "cleanup_only"])
def test_compiler_cannot_detach_an_oracle_or_replace_its_pinned_request(change):
    from scripts.selftest.compile_boundary_contracts import CompileBoundaryObservation
    from scripts.selftest.compile_boundary_verify import _ready

    _, evidence = inputs()
    row = next(
        item
        for item in evidence["observations"]
        if item["transport"] == "stdio" and item["key"] == "positive"
    )
    graph = row["response"]["scenarios"][0]["executable_payload"]["native_definition"]
    request = next(node for node in graph["nodes"] if node["id"] == "request")
    status = next(node for node in graph["nodes"] if node["id"] == "assert_status")
    mutations = {
        "wrong_api": lambda: request["config"].__setitem__("api_definition_id", str(uuid4())),
        "wrong_version": lambda: request["config"].__setitem__("api_version", 999),
        "disconnected": lambda: graph.__setitem__("edges", []),
        "cleanup_only": lambda: status.__setitem__("phase", "cleanup"),
    }
    mutations[change]()
    assert not _ready(CompileBoundaryObservation.model_validate(row))
