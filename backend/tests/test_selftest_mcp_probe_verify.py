"""Synthetic scoped-metadata envelopes over retained wire inputs; no profile claims."""

import copy
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.selftest.contracts import Builds, canonical_digest
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.mcp_governance_contracts import Evidence, Manifest, ProposalView
from scripts.selftest.mcp_negative_contracts import ProtocolEvidence, ProtocolManifest
from scripts.selftest.mcp_probe_contracts import (
    ProbeAuthority,
    ProbeDesign,
    ProbeFixture,
    ProbeItem,
    ProbeOracle,
    ProbePage,
    ProbeResource,
    ProbeSnapshot,
    probe_kinds,
    snapshot_digest,
)
from scripts.selftest.mcp_probe_evidence import (
    DeployedEvidence,
    DisposalReceipt,
    ScenarioSnapshots,
    StackSnapshot,
)
from scripts.selftest.mcp_probe_verify import (
    EXPECTED_SYNTHETIC_DESIGN_DIGEST,
    verify_deployed,
    write_deployed_reports,
)

WORKTREE = Path(__file__).resolve().parents[2]


def summary(state: ProposalView) -> ProbeDesign:
    return ProbeDesign(
        document_digest=state.proposed_document_digest,
        intent_key_digest=canonical_digest(state.intent_key),
        objective_digest=canonical_digest(state.objective),
        oracles=tuple(
            ProbeOracle(
                id=row.id,
                kind=row.kind,
                expression_digest=canonical_digest(row.expression),
                operator=row.operator,
                expected_digest=row.expected_digest,
            )
            for row in state.oracles
        ),
    )


def materialize(state: ProposalView, resources: dict[tuple[str, str], ProbeResource]) -> None:
    design = summary(state)
    item = ProbeItem(
        id=state.item_id,
        item_type=state.item_type,
        action="create",
        review_status=state.item_review,
        reviewed_by_id=state.reviewed_by_id,
        materialized_resource_type=state.materialized_type,
        materialized_resource_id=state.materialized_id,
        proposed_document_digest=state.proposed_document_digest,
        design=design,
    )
    proposal = ProbeResource(
        kind="ai_change_set",
        id=state.id,
        project_id=state.project_id,
        status=state.status,
        fingerprint=state.source_fingerprint,
        created_by_id=state.created_by_id,
        actor_type=state.actor_type,
        items=(item,),
    )
    resources[(proposal.kind, str(proposal.id))] = proposal
    if state.approval_id is not None:
        row = ProbeResource(
            kind="change_set_approval",
            id=state.approval_id,
            project_id=state.project_id,
            parent_id=state.id,
            source_change_set_id=state.id,
            status="approved",
            reviewed_by_id=state.approved_by_id,
        )
        resources[(row.kind, str(row.id))] = row
    if state.materialized is not None:
        saved = state.materialized
        row = ProbeResource(
            kind="test_design",
            id=saved.id,
            project_id=saved.project_id,
            source_change_set_id=saved.source_change_set_id,
            status=saved.status,
            fingerprint=saved.fingerprint,
            reviewed_by_id=saved.reviewed_by_id,
            created_by_id=saved.reviewed_by_id,
            design=design,
        )
        resources[(row.kind, str(row.id))] = row


def snapshot(
    authority: ProbeAuthority, resources: dict[tuple[str, str], ProbeResource], at
) -> ProbeSnapshot:
    rows = tuple(resources[key] for key in sorted(resources))
    page = ProbePage(
        probe_id=authority.probe_id,
        purpose="mcp_governance_negative",
        execution_scope="governance_negative_only",
        provenance="local_untrusted",
        binding_id=authority.binding_id,
        binding_fingerprint=authority.binding_fingerprint,
        manifest_digest=authority.manifest_digest,
        source_digest=authority.source_digest,
        runtime_profile=authority.runtime_profile,
        builds=authority.builds,
        covered_projects=authority.fixtures,
        covered_kinds=tuple(sorted(probe_kinds())),
        items=rows,
        total=len(rows),
        next_cursor=None,
        has_more=False,
        complete=True,
        reason_codes=(),
        snapshot_digest=snapshot_digest(authority, rows),
        observed_at=at,
        expires_at=authority.expires_at,
    )
    return ProbeSnapshot(pages=(page,))


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch):
    from scripts.selftest import mcp_probe_verify

    monkeypatch.setattr(mcp_probe_verify, "ROOT", WORKTREE)
    path = WORKTREE / "backend/tests/fixtures/mcp_governance_actual_final"
    manifest = Manifest.model_validate(read_json(path / "manifest.json"))
    raw = Evidence.model_validate(read_json(path / "evidence.json"))
    nonce = uuid4().hex
    manifest = manifest.model_copy(update={"nonce": nonce})
    raw = raw.model_copy(update={"nonce": nonce})
    stack = StackSnapshot(
        schema_version="flowtest-selftest-binding-v1",
        project_name="flowtest-selftest-" + "1" * 12,
        nonce="2" * 32,
        runtime_profile="standalone",
        runner_url="http://runner.test",
        target_url="http://target.test",
        observer_url="http://observer.test",
        target_internal_url="http://target:8000",
        fixture_internal_url="http://mock-target:8080",
        private_subnet="172.18.0.0/24",
        candidate_image="candidate",
        candidate_image_digest="sha256:" + "a" * 64,
        fixture_image="mock",
        fixture_image_digest="sha256:" + "b" * 64,
        source_digest=manifest.source_digest,
        candidate_source=None,
        dependency_digest="c" * 64,
        runner_container_id="d" * 64,
        target_container_id="e" * 64,
        observer_container_id="f" * 64,
        runner_volume="owned-runner",
        target_volume="owned-target",
    )
    authority = ProbeAuthority(
        probe_id=nonce,
        binding_id=uuid4(),
        binding_fingerprint=canonical_digest(
            stack.model_dump(mode="json", exclude={"runner_container_id"})
        ),
        manifest_digest=canonical_digest(manifest.model_dump(mode="json")),
        source_digest=manifest.source_digest,
        runtime_profile="standalone",
        builds=Builds(
            runner=stack.candidate_image_digest,
            target=stack.candidate_image_digest,
            fixture="b" * 64,
            verifier="O",
        ),
        fixtures=(
            ProbeFixture(
                project_id=manifest.fixture.project_id,
                organization_id=manifest.fixture.organization_id,
            ),
            ProbeFixture(project_id=uuid4(), organization_id=uuid4()),
        ),
        owner_user_id=manifest.fixture.owner_user_id,
        reviewer_user_id=manifest.fixture.reviewer_user_id,
        machine_account_ids=(manifest.fixture.machine_id,),
        issued_at=manifest.created_at,
        expires_at=manifest.expires_at,
    )
    resources = {}
    captures = []
    rows = []
    for row in raw.scenarios:
        before = snapshot(authority, resources, row.started_at + timedelta(microseconds=1))
        if row.state is not None:
            materialize(row.state, resources)
        after = snapshot(authority, resources, row.completed_at - timedelta(microseconds=1))
        captures.append(ScenarioSnapshots(scenario_id=row.scenario_id, before=before, after=after))
        rows.append(row.model_copy(update={"state": None}))
    raw = raw.model_copy(update={"scenarios": tuple(rows)})
    receipt = DisposalReceipt(
        project_name=stack.project_name,
        binding_nonce=stack.nonce,
        runner_volume=stack.runner_volume,
        target_volume=stack.target_volume,
        candidate_image_digest=stack.candidate_image_digest,
        removed_at=raw.collected_at + timedelta(seconds=1),
        containers_absent=True,
        volumes_absent=True,
        networks_absent=True,
    )
    evidence = DeployedEvidence(
        pack_kind="governance42",
        manifest_digest=authority.manifest_digest,
        authority_digest=canonical_digest(authority.model_dump(mode="json")),
        stack=stack,
        protocol=None,
        governance=raw,
        snapshots=tuple(captures),
        gateway_cleanup_complete=True,
        disposal_receipt=receipt,
        collected_at=raw.collected_at,
        request_budget_mode="conservative_outbound_plus_candidate_rpc",
        http_outbound_admitted=raw.http_admitted - raw.tools_admitted,
        candidate_rpc_admitted=raw.tools_admitted,
        candidate_rpc_rejected=0,
    )
    return manifest, evidence, authority


def checked(captured, evidence=None):
    manifest, actual, authority = captured
    return verify_deployed(
        manifest, evidence or actual, authority, now=actual.collected_at + timedelta(seconds=2)
    )


def codes(report):
    return {row.code for row in report.findings} | {
        f.code for row in report.scenarios for f in row.findings
    }


def reseal(data, authority):
    """Recompute legitimate DTO snapshot hashes after a semantic mutation."""
    for captured in data["snapshots"]:
        for name in ("before", "after"):
            page = captured[name]["pages"][0]
            page["items"].sort(key=lambda row: (row["kind"], row["id"]))
            rows = tuple(ProbeResource.model_validate(row) for row in page["items"])
            page["snapshot_digest"] = snapshot_digest(authority, rows)
    return DeployedEvidence.model_validate(data)


def test_digest_metadata_42_exact_assets_source_oracle_and_review_bindings_match(captured):
    report = checked(captured)
    assert report.exit_code == 0, (
        report.findings,
        [(row.scenario_id, row.findings) for row in report.scenarios if row.findings],
    )
    assert len(report.scenarios) == 42


def test_normalized_whole_design_golden_is_frozen_independently():
    golden = read_json(
        WORKTREE / "selftest/packs/mcp-governance-negative-v1/normalized-design.golden.json"
    )
    assert canonical_digest(golden) == EXPECTED_SYNTHETIC_DESIGN_DIGEST


def test_resealed_first_proposal_and_saved_design_forgery_cannot_define_expected(captured):
    _, evidence, authority = captured
    data = evidence.model_dump(mode="json")
    for capture in data["snapshots"]:
        for side in ("before", "after"):
            for resource in capture[side]["pages"][0]["items"]:
                for item in resource["items"]:
                    item["proposed_document_digest"] = "a" * 64
                    item["design"]["document_digest"] = "a" * 64
                if resource["design"] is not None:
                    resource["design"]["document_digest"] = "a" * 64
                    resource["fingerprint"] = "a" * 64
    report = checked(captured, reseal(data, authority))
    assert report.exit_code == 1
    assert "PROBE_PROPOSED_DOCUMENT_MISMATCH" in codes(report)
    assert "PROBE_INVENTORY_INCOMPLETE_OR_CHANGED" not in codes(report)


def test_resealed_same_count_old_asset_replacement_fails_exact_set(captured):
    _, evidence, authority = captured
    data = evidence.model_dump(mode="json")
    rows = data["snapshots"][10]["after"]["pages"][0]["items"]
    assert len(rows) == 2 and all(row["kind"] == "ai_change_set" for row in rows)
    rows[0]["id"] = str(uuid4())
    report = checked(captured, reseal(data, authority))
    assert report.exit_code != 0
    assert "PROBE_EXACT_ASSET_SET_MISMATCH" in codes(report)
    assert "PROBE_INVENTORY_INCOMPLETE_OR_CHANGED" not in codes(report)


def test_resealed_retained_unrelated_source_change_fails(captured):
    _, evidence, authority = captured
    data = evidence.model_dump(mode="json")
    before = data["snapshots"][10]["before"]["pages"][0]["items"]
    retained = before[0]["id"]
    after = data["snapshots"][10]["after"]["pages"][0]["items"]
    next(row for row in after if row["id"] == retained)["fingerprint"] = "f" * 64
    report = checked(captured, reseal(data, authority))
    assert report.exit_code == 1
    assert "PROBE_UNRELATED_ASSET_CHANGED" in codes(report)
    assert "PROBE_INVENTORY_INCOMPLETE_OR_CHANGED" not in codes(report)


@pytest.mark.parametrize("field", ["http_outbound_admitted", "candidate_rpc_rejected"])
def test_admission_counter_drift_or_rejected_request_cannot_green(captured, field):
    _, evidence, _ = captured
    altered = evidence.model_copy(update={field: getattr(evidence, field) + 1})
    report = checked(captured, altered)
    assert report.exit_code == 1 and "PROBE_REQUEST_BUDGET_MISMATCH" in codes(report)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("missing_snapshot", "PROBE_SCENARIO_SNAPSHOTS_MISSING"),
        ("wrong_counter", "PROBE_OBSERVED_ASSET_COUNTER_MISMATCH"),
        ("forged_disposal", "PROBE_DISPOSAL_BINDING_OR_TIME_MISMATCH"),
        ("missing_disposal", "OWNED_ASSET_DISPOSAL_PENDING"),
        ("stack_drift", "PROBE_STACK_BINDING_MISMATCH"),
        ("nonce_binding", "PROBE_AUTHORITY_BINDING_MISMATCH"),
        ("raw_capture", "PROBE_UNEXPECTED_RAW_DESIGN_CAPTURE"),
        ("hidden_design", "PROBE_EXACT_ASSET_SET_MISMATCH"),
    ],
)
def test_deployed_oracle_rejects_metadata_cleanup_and_scope_anti_green(captured, mutation, code):
    _, evidence, _ = captured
    data = evidence.model_dump(mode="json")
    if mutation == "missing_snapshot":
        data["snapshots"].pop()
    elif mutation == "wrong_counter":
        data["governance"]["scenarios"][0]["after"]["designs"] = 1
    elif mutation == "forged_disposal":
        data["disposal_receipt"]["binding_nonce"] = "9" * 32
    elif mutation == "missing_disposal":
        data["disposal_receipt"] = None
    elif mutation == "stack_drift":
        data["stack"]["runner_volume"] = "another-volume"
    elif mutation == "nonce_binding":
        data["authority_digest"] = "0" * 64
    elif mutation == "raw_capture":
        data["governance"]["scenarios"][2]["state"] = read_json(
            WORKTREE / "backend/tests/fixtures/mcp_governance_actual_final/evidence.json"
        )["scenarios"][2]["state"]
    elif mutation == "hidden_design":
        target = data["snapshots"][0]["after"]
        extra = copy.deepcopy(data["snapshots"][13]["after"]["pages"][0]["items"])
        target["pages"][0]["items"] = extra
        target["pages"][0]["total"] = len(extra)
    report = checked(captured, DeployedEvidence.model_validate(data))
    assert report.exit_code != 0 and code in codes(report), codes(report)


def test_global_owned_disposal_pending_fails_junit_without_changing_sdk_raw_results(
    captured, tmp_path
):
    _, evidence, _ = captured
    pending = evidence.model_copy(update={"disposal_receipt": None})
    report = checked(captured, pending)
    write_deployed_reports(report, pending, tmp_path)
    assert report.exit_code == 2
    assert "OWNED_ASSET_DISPOSAL_PENDING" in (tmp_path / "verification.junit.xml").read_text()
    assert "failure" in (tmp_path / "execution.junit.xml").read_text()


@pytest.mark.parametrize("mutation", ["foreign_stack", "missing_owner_receipt", "not_removed"])
def test_disposal_finalizer_fails_closed_and_preserves_evidence(
    captured, tmp_path, monkeypatch, mutation
):
    from scripts.selftest import mcp_probe_run

    _, evidence, _ = captured
    directory, output = tmp_path / "owned", tmp_path / "result"
    directory.mkdir()
    write_json(directory / "stack.json", evidence.stack)
    write_json(
        directory / "ownership.json",
        {
            "project_name": evidence.stack.project_name,
            "nonce": evidence.stack.nonce,
        },
    )
    write_json(
        directory / "cleanup.json",
        {"project_name": evidence.stack.project_name, "status": "completed"},
    )
    write_json(output / "public/evidence.json", evidence)
    before = (output / "public/evidence.json").read_bytes()
    if mutation == "foreign_stack":
        write_json(directory / "stack.json", evidence.stack.model_copy(update={"nonce": "f" * 32}))
    elif mutation == "missing_owner_receipt":
        (directory / "ownership.json").unlink()

    def verify_removed(_):
        if mutation == "not_removed":
            raise HarnessError("SYNTHETIC_RESOURCES_STILL_PRESENT")
        pytest.fail("invalid identity must never reach Docker inspection")

    monkeypatch.setattr(mcp_probe_run, "_verify_removed", verify_removed)
    with pytest.raises((HarnessError, FileNotFoundError)):
        mcp_probe_run.finalize_disposal(directory, output)
    assert (output / "public/evidence.json").read_bytes() == before


def test_independent_oracle_modules_do_not_import_product_models_or_harness_drivers():
    import ast

    forbidden = (
        "app",
        "scripts.selftest.local_stack",
        "scripts.selftest.mcp_probe_setup",
        "scripts.selftest.mcp_probe_run",
    )
    for filename in (
        "mcp_probe_verify.py",
        "mcp_probe_reader.py",
        "mcp_probe_contracts.py",
        "mcp_probe_evidence.py",
    ):
        tree = ast.parse((WORKTREE / "scripts/selftest" / filename).read_text())
        imports = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        assert not any(
            name == prefix or name.startswith(prefix + ".")
            for name in imports
            for prefix in forbidden
        )


def test_protocol_34_reuses_independent_oracle_with_public_empty_metadata_scope(captured):
    _, old, previous = captured
    fixture = WORKTREE / "backend/tests/fixtures/mcp_negative_actual_valid_write"
    manifest = ProtocolManifest.model_validate(read_json(fixture / "manifest.json"))
    raw = ProtocolEvidence.model_validate(read_json(fixture / "evidence.json"))
    nonce = uuid4().hex
    manifest = manifest.model_copy(update={"nonce": nonce})
    raw = raw.model_copy(update={"nonce": nonce})
    stack = old.stack.model_copy(update={"source_digest": manifest.source_digest})
    authority = previous.model_copy(
        update={
            "probe_id": UUID(nonce),
            "manifest_digest": canonical_digest(manifest.model_dump(mode="json")),
            "source_digest": manifest.source_digest,
            "binding_fingerprint": canonical_digest(
                stack.model_dump(mode="json", exclude={"runner_container_id"})
            ),
            "fixtures": (
                ProbeFixture(
                    project_id=manifest.fixture.project_a,
                    organization_id=manifest.fixture.organization_a,
                ),
                ProbeFixture(
                    project_id=manifest.fixture.project_b,
                    organization_id=manifest.fixture.organization_b,
                ),
            ),
            "issued_at": manifest.created_at,
            "expires_at": manifest.expires_at,
        }
    )
    captures = tuple(
        ScenarioSnapshots(
            scenario_id=row.scenario_id,
            before=snapshot(authority, {}, row.started_at + timedelta(microseconds=1)),
            after=snapshot(authority, {}, row.completed_at - timedelta(microseconds=1)),
        )
        for row in raw.scenarios
    )
    rpc = sum(len(row.requests) for row in raw.scenarios)
    # Unit-only admission envelope: local ingress counts are not deployed RPC
    # reservations. Keep that captured count as outbound units and add the
    # synthetic conservative reservations explicitly; this is not an actual run.
    outbound = raw.http_requests
    raw = raw.model_copy(update={"http_requests": outbound + rpc})
    receipt = old.disposal_receipt.model_copy(
        update={"removed_at": raw.collected_at + timedelta(seconds=1)}
    )
    evidence = DeployedEvidence(
        pack_kind="protocol34",
        manifest_digest=authority.manifest_digest,
        authority_digest=canonical_digest(authority.model_dump(mode="json")),
        stack=stack,
        protocol=raw,
        governance=None,
        snapshots=captures,
        gateway_cleanup_complete=True,
        disposal_receipt=receipt,
        collected_at=raw.collected_at,
        request_budget_mode="conservative_outbound_plus_candidate_rpc",
        http_outbound_admitted=outbound,
        candidate_rpc_admitted=rpc,
        candidate_rpc_rejected=0,
    )
    report = verify_deployed(
        manifest, evidence, authority, now=raw.collected_at + timedelta(seconds=2)
    )
    assert report.exit_code == 0, codes(report)
    assert len(report.scenarios) == 34
