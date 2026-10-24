"""Execute synthetic semantic counterexamples through real SDK and ordinary native Runs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from scripts.selftest.bad_targets_budget import (
    BadTargetsBudget,
    BoundedBadTargetAPI,
    BoundedBadTargetProtocol,
)
from scripts.selftest.bootstrap import Installation
from scripts.selftest.cleanup import RoundCleanup
from scripts.selftest.collect_evidence import journal, normalize_execution, wait_plan
from scripts.selftest.contracts import (
    Builds,
    FixtureBudgetScope,
    PlanRunSnapshot,
    SuiteReference,
    canonical_digest,
)
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import ROOT, StackBinding
from scripts.selftest.mcp_probe_evidence import StackSnapshot
from scripts.selftest.mcp_protocol_runner import ProtocolClient
from scripts.selftest.semantic_contracts import (
    SemanticArtifact,
    SemanticEvidence,
    SemanticManifest,
    SemanticObservation,
    SemanticReport,
    SemanticRubric,
    SemanticVariant,
)
from scripts.selftest.semantic_generation import generate_semantic_assets, project_artifact
from scripts.selftest.semantic_verify import golden_schema, verify_semantic, write_semantic_reports
from scripts.selftest.start_plan import PlanSelection, launch_plan, prepare_plan


async def _configure(
    observer: PublicAPI,
    batch: str,
    nonce: str,
    digest: str,
    deadline: datetime,
) -> str:
    scope = FixtureBudgetScope(parent_batch_key=batch, nonce=nonce, expires_at=deadline.timestamp())
    await observer.request(
        "PUT",
        f"/selftest/batches/{batch}/scenarios/ST-MCP-026",
        {
            "nonce": nonce,
            "fixture_digest": digest,
            "ttl_seconds": max(1, int((deadline - datetime.now(UTC)).total_seconds())),
            "budget_scope": scope.model_dump(mode="json"),
            "max_entries": 10,
            "response_statuses": [200],
            "response_body": {"actual": 1, "code": 0, "value": None},
        },
    )
    initial = await journal(observer, batch, "ST-MCP-026", deadline=deadline)
    if initial.request_count or initial.truncated or initial.expired:
        raise HarnessError("SELFTEST_SEMANTIC_FIXTURE_NOT_EMPTY")
    return initial.fixture_epoch


async def _collect(
    reader: PublicAPI,
    artifact: SemanticArtifact,
    run: JsonObject,
    item: JsonObject,
    selection: PlanSelection,
) -> SemanticObservation:
    raw = await reader.object(
        "GET",
        (
            f"/ci/projects/{selection.project_id}/workflow-executions/{item['execution_id']}/evidence"
        ),
    )
    complete = (
        raw["truncated"] is False
        and raw["bindings_complete"] is True
        and raw["node_total"] == len(objects_value(raw["nodes"]))
        and all(node["assertions_complete"] is True for node in objects_value(raw["nodes"]))
        and item["attempts_complete"] is True
        and item["execution_ids"] == [item["execution_id"]]
    )
    frozen = next(case for case in selection.cases if case.case_id == artifact.case_id)
    snapshot = PlanRunSnapshot.model_validate(
        {
            **{
                key: item[key]
                for key in (
                    "target_type",
                    "target_id",
                    "target_version",
                    "workflow_id",
                    "workflow_version",
                    "environment_id",
                    "attempts",
                    "status",
                    "target_snapshot_digest",
                )
            },
            "project_id": str(selection.project_id),
            "run_id": run["run_id"],
            "run_item_id": item["id"],
            "execution_id": item["execution_id"],
            "expected_target_snapshot_digest": frozen.target_snapshot_digest,
            "source_suite": SuiteReference(
                id=selection.suite_id, version=selection.suite_version
            ).model_dump(mode="json"),
        }
    )
    return SemanticObservation(
        variant=artifact.variant,
        execution=normalize_execution(raw),
        run=snapshot,
        source_plan_run_item_id=UUID(text_value(raw["source_plan_run_item_id"])),
        source_case_id=UUID(text_value(raw["source_case_id"])),
        complete=complete,
    )


async def execute_semantic_pack(
    client: ProtocolClient,
    reviewer: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    *,
    installation: Installation,
    binding: StackBinding,
    batch_key: str,
    nonce: str,
    builds: Builds,
    output_dir: Path,
    deadline: datetime,
) -> tuple[SemanticManifest, SemanticEvidence, SemanticReport]:
    started = datetime.now(UTC)
    budget = BadTargetsBudget(deadline)
    transport = client.transport
    client = BoundedBadTargetProtocol(client, budget)
    reviewer, reader, observer = (
        BoundedBadTargetAPI(api, budget) for api in (reviewer, reader, observer)
    )
    cleanup = RoundCleanup(
        batch_key=batch_key,
        project_id=installation.project_id,
        output_dir=output_dir,
        writer=reviewer,
        reader=reader,
        observer=observer,
        nonce=nonce,
        fixture_digest=builds.fixture,
    )
    cleanup.register_fixture("ST-MCP-026")
    try:
        epoch = await _configure(observer, batch_key, nonce, builds.fixture, deadline)
        assets = await generate_semantic_assets(
            client,
            reviewer,
            installation=installation,
            output_dir=output_dir / "assets",
        )
        selection = await prepare_plan(
            reviewer,
            project_id=str(installation.project_id),
            cases=tuple(item.case for item in assets),
            batch_key=batch_key,
            output_dir=output_dir,
        )
        variants: tuple[SemanticVariant, ...] = (
            "positive_control",
            "missing_assertion",
            "wrong_field",
            "wrong_operator",
            "expected_from_actual",
        )
        artifacts = tuple(
            project_artifact(asset, variant)
            for asset, variant in zip(assets, variants, strict=True)
        )
        manifest = SemanticManifest(
            batch_key=batch_key,
            pack_digest=canonical_digest(
                read_json(ROOT / "selftest/packs/mcp-semantic-review-v1/pack.json")
            ),
            transport=transport,
            nonce=nonce,
            builds=builds,
            stack=StackSnapshot.model_validate(binding.model_dump(mode="json")),
            rubric=SemanticRubric(response_schema=golden_schema()),
            artifacts=artifacts,
            selection=selection,
            fixture_epoch=epoch,
            created_at=started,
            expires_at=min(deadline, started + timedelta(seconds=600)),
        )
        write_json(output_dir / "manifest.json", manifest)
        cleanup.arm_plan(selection.plan_id, tuple(item.case_id for item in selection.cases))
        launched = await launch_plan(reviewer, selection=selection, batch_key=batch_key)
        cleanup.started_plan(launched.run_id)
        run = await wait_plan(reader, str(installation.project_id), str(launched.run_id), deadline)
        cleanup.plan.observe(run)
        items = objects_value(run["items"])
        if {item["target_id"] for item in items} != {
            str(item.case_id) for item in artifacts
        } or len(items) != 5:
            raise HarnessError("SELFTEST_SEMANTIC_PLAN_SET_MISMATCH")
        observations = tuple(
            [
                await _collect(
                    reader,
                    artifact,
                    run,
                    next(item for item in items if item["target_id"] == str(artifact.case_id)),
                    selection,
                )
                for artifact in artifacts
            ]
        )
        fixture = await journal(observer, batch_key, "ST-MCP-026", deadline=deadline)
        receipt = await cleanup.finish()
        evidence = SemanticEvidence(
            manifest_digest=canonical_digest(manifest.model_dump(mode="json")),
            observations=observations,
            journal=fixture,
            cleanup_completed=receipt.status == "completed",
            tool_attempts=client.attempt_count,
            tool_receipts=tuple(client.receipts),
            direct_http_attempts=budget.attempts,
            collected_at=datetime.now(UTC),
        )
        report = verify_semantic(manifest, evidence)
        write_json(output_dir / "evidence.json", evidence)
        write_semantic_reports(report, evidence, output_dir)
        return manifest, evidence, report
    finally:
        await cleanup.finish()
