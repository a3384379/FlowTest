"""Independent O must reject changed request routes and approval input bindings."""

import copy
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parents[2]))
from scripts.selftest.io import read_json
from scripts.selftest.mcp_probe_contracts import ProbeAuthority
from scripts.selftest.mcp_probe_evidence import DisposalReceipt
from scripts.selftest.review_boundary_contracts import ReviewEvidence, ReviewManifest
from scripts.selftest.review_boundary_verify import verify

FIXTURE = Path(__file__).parent / "fixtures/review_boundary_actual"


def bundle():
    manifest = ReviewManifest.model_validate(read_json(FIXTURE / "manifest.json"))
    evidence = ReviewEvidence.model_validate(read_json(FIXTURE / "evidence.json"))
    authority = ProbeAuthority.model_validate(read_json(FIXTURE / "authority.json"))
    return manifest, evidence, authority


def test_actual_twelve_rows_only_need_exact_owned_disposal():
    manifest, evidence, authority = bundle()
    report = verify(
        manifest, evidence, authority, now=evidence.collected_at + timedelta(milliseconds=1)
    )
    assert report.exit_code == 2
    assert [f.code for f in report.findings] == ["OWNED_ASSET_DISPOSAL_PENDING"]
    assert len(report.scenarios) == 12
    assert all(row.verification_status == "matched" for row in report.scenarios)


@pytest.mark.parametrize(
    "mutation",
    ["wrong_publication_path", "wrong_approval_content_request", "wrong_preview_budget_request"],
)
def test_changed_http_request_binding_cannot_reuse_matching_metadata(mutation):
    manifest, evidence, authority = bundle()
    raw = copy.deepcopy(evidence.model_dump(mode="json"))
    if mutation == "wrong_publication_path":
        raw["observations"][1]["http"][1]["path"] = "/projects/foreign/workflows/other/versions"
    elif mutation == "wrong_approval_content_request":
        raw["observations"][3]["http"][1]["request_digest"] = "0" * 64
    else:
        raw["observations"][0]["http"][3]["request_digest"] = "0" * 64
    report = verify(
        manifest,
        ReviewEvidence.model_validate(raw),
        authority,
        now=evidence.collected_at + timedelta(milliseconds=1),
    )
    assert report.exit_code == 1 or any(
        row.verification_status != "matched" for row in report.scenarios
    )


def finalized_fixture():
    manifest, evidence, authority = bundle()
    stack = evidence.stack
    # Unit-only absence receipt; never archived as deployed cleanup evidence.
    receipt = DisposalReceipt(
        project_name=stack.project_name,
        binding_nonce=stack.nonce,
        runner_volume=stack.runner_volume,
        target_volume=stack.target_volume,
        candidate_image_digest=stack.candidate_image_digest,
        removed_at=evidence.collected_at,
        containers_absent=True,
        volumes_absent=True,
        networks_absent=True,
    )
    return manifest, evidence.model_copy(update={"disposal": receipt}), authority


MUTATIONS = (
    (("tool_count",), 29),
    (("http_rejected",), 1),
    (("protocol_cleanup_complete",), False),
    (("manifest_digest",), "0" * 64),
    (("authority_digest",), "0" * 64),
    (("sources", 0, "spec", "run_policy", "force_cancel_skips_cleanup"), True),
    (("sources", 0, "spec", "nodes", 1, "config", "seconds"), 0),
    (("sources", 0, "fixture_epoch"), "different-epoch"),
    (("observations", 0, "calls", 0, "tool_name"), "flowtest.publish_workflow"),
    (("observations", 0, "calls", 0, "result_digest"), "0" * 64),
    (("observations", 0, "calls", 3, "success"), True),
    (("observations", 0, "tool_results", 0, "business_code"), "GENERIC_FAILURE"),
    (("observations", 0, "tool_results", 0, "trace_present"), False),
    (("observations", 0, "preview", "run_purpose"), "standard"),
    (("observations", 0, "preview", "source_case_id"), "10000000-0000-0000-0000-000000000000"),
    (("observations", 0, "preview", "cleanup_status"), "failed"),
    (("observations", 0, "preview", "status"), "passed"),
    (("observations", 0, "preview", "bindings_complete"), False),
    (("observations", 0, "preview", "truncated"), True),
    (("observations", 0, "preview", "children_total"), 1),
    (("observations", 0, "preview_execution_ids", 1), "10000000-0000-0000-0000-000000000000"),
    (("observations", 0, "preview_approval", "budget", "max_requests"), 3),
    (
        ("observations", 0, "preview_approval", "executor_id"),
        "10000000-0000-0000-0000-000000000000",
    ),
    (("observations", 0, "journal", "request_count"), 2),
    (("observations", 0, "journal", "truncated"), True),
    (("observations", 0, "journal", "entries", 0, "authorization_present"), True),
    (("observations", 0, "journal", "fixture_epoch"), "different-epoch"),
    (("observations", 1, "http", 1, "outcome"), "received"),
    (("observations", 1, "http", 1, "response_digest"), "0" * 64),
    (("observations", 2, "http", 2, "code"), "WORKFLOW_DRAFT_CONFLICT"),
    (("observations", 2, "workflow_read_envelope", "data", "name"), "overwritten"),
    (("observations", 3, "proposal_arguments", "design", "oracles", 0, "expected"), 201),
    (("observations", 4, "http", 1, "status"), 200),
    (("observations", 5, "checkpoint"), None),
    (("disposal", "binding_nonce"), "f" * 32),
    (("disposal", "candidate_image_digest"), "sha256:" + "f" * 64),
)


@pytest.mark.parametrize(
    ("path", "value"), MUTATIONS, ids=["-".join(map(str, path)) for path, _ in MUTATIONS]
)
def test_frozen_raw_evidence_mutations_cannot_pass(path, value):
    manifest, evidence, authority = finalized_fixture()
    frozen_now = evidence.collected_at + timedelta(milliseconds=1)
    assert verify(manifest, evidence, authority, now=frozen_now).exit_code == 0
    original = evidence.model_dump(mode="json")
    changed = copy.deepcopy(original)
    if path == ("tool_count",):
        path = ("tools_admitted",)
    node = changed
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    try:
        parsed = ReviewEvidence.model_validate(changed)
    except ValidationError:
        return
    assert verify(manifest, parsed, authority, now=frozen_now).exit_code != 0
    assert evidence.model_dump(mode="json") == original
