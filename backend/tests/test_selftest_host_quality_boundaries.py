"""Characterize full task denominators and independent frozen-source failures."""

import hashlib
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import canonical_digest  # noqa: E402
from scripts.selftest.host_materialized import HostMaterialization, HostSelection  # noqa: E402
from scripts.selftest.host_product_bridge import publish_materialized  # noqa: E402
from scripts.selftest.host_product_observe import _independent_manifest  # noqa: E402
from scripts.selftest.host_prompts import HostTask  # noqa: E402
from scripts.selftest.host_quality import (  # noqa: E402
    HostQualityReport,
    QualityAttempt,
    QualityTask,
    QualityTaskSet,
    quality_report,
)
from scripts.selftest.host_quality_evidence import materialized_quality  # noqa: E402
from scripts.selftest.host_verify import evaluate_host_batch  # noqa: E402
from scripts.selftest.io import HarnessError, read_json, write_json  # noqa: E402
from scripts.selftest.mcp_generation_journey import GeneratedAsset  # noqa: E402
from scripts.selftest.product_mcp import _source  # noqa: E402
from scripts.selftest.review_fixture_driver import ReviewedCase, ReviewedWorkflow  # noqa: E402
from scripts.selftest.start_plan import PlanSelection  # noqa: E402
from test_selftest_host_observer import FROZEN, fixture  # noqa: E402

from app.schemas.self_tests import (  # noqa: E402
    AgentTaskResponse,
    ArtifactReference,
    BatchResponse,
    HostEvidence,
)


def materialization():
    manifest, evidence, trail, grant = fixture()
    source = evidence.scenarios[0].provenance
    asset = GeneratedAsset(
        scenario_id=evidence.scenarios[0].scenario_id,
        variant_key=evidence.scenarios[0].variant_key,
        api_source=source.api_source,
        design={},  # Synthetic verifier seed; this test targets downstream source binding.
        design_fingerprint=source.design_fingerprint,
        compilation_fingerprint=source.compilation_fingerprint,
        oracle_bindings=source.oracle_bindings,
        calls=source.calls,
        generated_at=source.generated_at,
        frozen_at=source.frozen_at,
        workflow=ReviewedWorkflow(
            workflow={"id": str(source.workflow.id)},
            version={
                "version": source.workflow.version,
                "fingerprint": source.workflow.fingerprint,
            },
            proposal=source.workflow_proposal,
        ),
        case=ReviewedCase(
            case={"id": str(source.case.id)},
            version={"version": source.case.version, "fingerprint": source.case.fingerprint},
            proposal=source.case_proposal,
        ),
    )
    # The upstream generated-design validator is covered by the SDK/ASGI source tests.
    materialized = HostMaterialization.model_construct(
        attempt_id=trail.receipts[0].attempt_id,
        authorization_digest=grant.digest,
        task_digest=grant.authorization.task_digest,
        catalog_digest=trail.catalog_digest,
        host=trail.host,
        assets=(asset,),
        trail=trail,
    )
    return manifest, evidence, materialized, grant


def test_independent_execution_fingerprint_failure_cannot_count_source_complete():
    manifest, evidence, materialized, grant = materialization()
    actual = evidence.scenarios[0]
    changed = evidence.model_copy(
        update={
            "scenarios": (
                actual.model_copy(
                    update={
                        "execution": actual.execution.model_copy(
                            update={"workflow_fingerprint": "f" * 64}
                        )
                    }
                ),
            )
        }
    )
    verification = evaluate_host_batch(
        manifest,
        changed,
        trail=materialized.trail,
        grant=grant,
        now=datetime.fromisoformat(FROZEN) + timedelta(seconds=1),
    )
    report = verification.report
    assert "EXECUTION_FINGERPRINT_MISMATCH" in {
        finding.code for finding in report.scenarios[0].findings
    }
    taskset = QualityTaskSet(version="quality-v1", tasks=(QualityTask(task_id=actual.scenario_id),))
    quality = materialized_quality(taskset, materialized, changed, verification)
    source = next(item for item in quality.metrics if item.name == "source_completeness")
    assert (source.numerator, source.denominator) == (0, 1)


def test_unattempted_selected_task_makes_whole_quality_incomplete():
    taskset = QualityTaskSet(
        version="quality-v1", tasks=(QualityTask(task_id="one"), QualityTask(task_id="two"))
    )
    attempt = QualityAttempt(
        task_id="one",
        attempt_id=uuid4(),
        ordinal=1,
        evidence_digest="a" * 64,
        review_mode="ci_fixture",
        protocol_available=True,
        design_valid=True,
        executable_asset_generated=True,
        independent_execution_match=True,
        source_complete=True,
    )
    report = quality_report(taskset, (attempt,))
    assert report.coverage == "PARTIAL" and report.not_run_task_ids == ("two:default",)
    assert getattr(report, "evaluation_status", None) == "INCOMPLETE"


@pytest.mark.parametrize("task_ids", [("unrelated",), ("ST-ENG-002", "unattempted")])
def test_host_task_cannot_shrink_or_replace_frozen_quality_taskset(task_ids):
    manifest, evidence, _, _ = materialization()
    with pytest.raises(ValidationError, match="quality task set"):
        HostTask(
            project_id=manifest.project_id,
            batch_key=manifest.batch_key,
            objective="独立任务集契约表征",
            authorized_data_digest="a" * 64,
            quality_taskset=QualityTaskSet(
                version="quality-v1", tasks=tuple(QualityTask(task_id=value) for value in task_ids)
            ),
            selections=(
                HostSelection(
                    scenario_id=evidence.scenarios[0].scenario_id,
                    api_source=evidence.scenarios[0].provenance.api_source,
                    design_kind="happy_path",
                ),
            ),
        )


def frozen_source_context(tmp_path, monkeypatch):
    manifest, _, materialized, grant = materialization()
    asset = materialized.assets[0]
    frozen_task = HostTask(
        project_id=manifest.project_id,
        batch_key=manifest.batch_key,
        objective="服务端来源冻结独立核验",
        authorized_data_digest="a" * 64,
        quality_taskset=QualityTaskSet(
            version="quality-v1", tasks=(QualityTask(task_id=asset.scenario_id),)
        ),
        selections=(
            HostSelection(
                scenario_id=asset.scenario_id, api_source=asset.api_source, design_kind="happy_path"
            ),
        ),
    )
    grant = type(grant)(
        grant.authorization.model_copy(
            update={"task_digest": canonical_digest(frozen_task.model_dump(mode="json"))}
        ),
        grant.digest,
    )
    reference = ArtifactReference(
        id=uuid4(),
        sha256=canonical_digest(asset.model_dump(mode="json")),
        kind="generation",
    )
    source = _source(asset, reference).model_copy(
        update={"host_evidence": HostEvidence.model_validate(materialized.host.model_dump())}
    )
    batch = BatchResponse.model_construct(
        batch_key=manifest.batch_key, deadline=manifest.expires_at
    )
    task = AgentTaskResponse.model_construct(
        batch=batch,
        sources=(source,),
        nonce=manifest.nonce,
        budget=type("Budget", (), {"max_requests": 100})(),
    )
    selection = PlanSelection(
        project_id=manifest.project_id,
        suite_id=uuid4(),
        suite_version=1,
        suite_fingerprint="a" * 64,
        plan_id=uuid4(),
        cases=(),
        frozen_at=manifest.created_at,
    )

    def freeze(*args):
        write_json(args[-1] / "selection.json", selection)
        return manifest

    monkeypatch.setattr("scripts.selftest.host_product_observe.freeze_product_expectations", freeze)
    return task, materialized, manifest, selection, frozen_task, grant


def test_observer_rejects_local_compilation_changed_after_server_freeze(tmp_path, monkeypatch):
    task, materialized, manifest, selection, frozen_task, grant = frozen_source_context(
        tmp_path, monkeypatch
    )
    changed = materialized.model_copy(
        update={
            "assets": (
                materialized.assets[0].model_copy(update={"compilation_fingerprint": "f" * 64}),
            )
        }
    )
    with pytest.raises(HarnessError, match="HOST_OBSERVER_FROZEN_SOURCE"):
        _independent_manifest(task, changed, manifest, selection, frozen_task, grant, tmp_path)


def test_observer_accepts_exact_server_frozen_sources(tmp_path, monkeypatch):
    arguments = frozen_source_context(tmp_path, monkeypatch)
    _independent_manifest(*arguments, tmp_path)


@pytest.mark.parametrize(
    "field",
    [
        "design_fingerprint",
        "compilation_fingerprint",
        "oracle_mapping_digest",
        "api_sources_digest",
        "protocol_receipts_digest",
    ],
)
def test_observer_compares_each_frozen_digest_not_only_golden_outcome(field, tmp_path, monkeypatch):
    task, materialized, manifest, selection, frozen_task, grant = frozen_source_context(
        tmp_path, monkeypatch
    )
    frozen = task.sources[0].model_copy(update={field: "f" * 64})
    task = task.model_copy(update={"sources": (frozen,)})
    with pytest.raises(HarnessError, match="HOST_OBSERVER_FROZEN_SOURCE_CHANGED"):
        _independent_manifest(task, materialized, manifest, selection, frozen_task, grant, tmp_path)


@pytest.mark.parametrize("change", ["design_body", "calls", "artifact", "host", "case", "workflow"])
def test_observer_rejects_asset_content_receipt_and_published_source_tampering(
    change, tmp_path, monkeypatch
):
    task, materialized, manifest, selection, frozen_task, grant = frozen_source_context(
        tmp_path, monkeypatch
    )
    asset, frozen = materialized.assets[0], task.sources[0]
    if change == "design_body":
        asset = asset.model_copy(update={"design": {"altered": True}})
    elif change == "calls":
        asset = asset.model_copy(
            update={
                "calls": (
                    asset.calls[0].model_copy(update={"request_digest": "f" * 64}),
                    *asset.calls[1:],
                )
            }
        )
    elif change == "artifact":
        frozen = frozen.model_copy(
            update={
                "generation_manifest": frozen.generation_manifest.model_copy(
                    update={"sha256": "f" * 64}
                )
            }
        )
    elif change == "host":
        frozen = frozen.model_copy(
            update={
                "host_evidence": frozen.host_evidence.model_copy(update={"model": "altered-model"})
            }
        )
    else:
        frozen = frozen.model_copy(
            update={change: getattr(frozen, change).model_copy(update={"version": 2})}
        )
    task = task.model_copy(update={"sources": (frozen,)})
    materialized = materialized.model_copy(update={"assets": (asset,)})
    with pytest.raises(HarnessError, match="HOST_OBSERVER_FROZEN_SOURCE"):
        _independent_manifest(task, materialized, manifest, selection, frozen_task, grant, tmp_path)


@pytest.mark.parametrize("change", ["missing", "duplicate", "foreign_scenario", "foreign_project"])
def test_observer_missing_duplicate_or_foreign_frozen_source_cannot_pass(
    change, tmp_path, monkeypatch
):
    task, materialized, manifest, selection, frozen_task, grant = frozen_source_context(
        tmp_path, monkeypatch
    )
    frozen = task.sources[0]
    sources = ()
    if change == "duplicate":
        sources = (frozen, frozen)
    elif change == "foreign_scenario":
        sources = (frozen.model_copy(update={"scenario_id": "ST-MCP-036"}),)
    elif change == "foreign_project":
        foreign = frozen.api_sources[0].model_copy(update={"project_id": uuid4()})
        sources = (frozen.model_copy(update={"api_sources": (foreign,)}),)
    task = task.model_copy(update={"sources": sources})
    with pytest.raises(HarnessError, match="HOST_OBSERVER_FROZEN_SOURCE"):
        _independent_manifest(task, materialized, manifest, selection, frozen_task, grant, tmp_path)


def test_whole_quality_not_run_and_unknown_observations_remain_unevaluated_or_incomplete():
    taskset = QualityTaskSet(version="quality-v1", tasks=(QualityTask(task_id="one"),))
    assert quality_report(taskset, ()).evaluation_status == "NOT_EVALUATED"
    unknown = QualityAttempt(
        task_id="one",
        attempt_id=uuid4(),
        ordinal=1,
        evidence_digest="a" * 64,
        review_mode="ci_fixture",
    )
    report = quality_report(taskset, (unknown,))
    assert report.coverage == "COMPLETE" and report.evaluation_status == "INCOMPLETE"
    evaluated = unknown.model_copy(
        update={
            "protocol_available": True,
            "design_valid": True,
            "executable_asset_generated": True,
            "independent_execution_match": False,
            "source_complete": False,
        }
    )
    complete = quality_report(taskset, (evaluated,))
    assert complete.evaluation_status == "EVALUATED"
    first = next(
        item for item in complete.metrics if item.name == "first_generation_execution_match"
    )
    assert (first.numerator, first.denominator) == (0, 1)


def test_independent_assessments_preserve_matching_expected_raw_failure_source():
    manifest, evidence, materialized, grant = materialization()
    verification = evaluate_host_batch(
        manifest,
        evidence,
        trail=materialized.trail,
        grant=grant,
        now=datetime.fromisoformat(FROZEN) + timedelta(seconds=1),
    )
    taskset = QualityTaskSet(
        version="quality-v1", tasks=(QualityTask(task_id=materialized.assets[0].scenario_id),)
    )
    quality = materialized_quality(taskset, materialized, evidence, verification)
    assert verification.report.batch_verdict == "passed"
    assert verification.provenance[0].findings == ()
    assert (
        next(item for item in quality.metrics if item.name == "source_completeness").numerator == 1
    )


async def test_uploaded_bytes_survive_sorted_private_persistence_without_digest_drift(
    tmp_path, monkeypatch
):
    task, materialized, manifest, selection, frozen_task, grant = frozen_source_context(
        tmp_path, monkeypatch
    )
    task = task.model_copy(update={"project_id": manifest.project_id})
    task = task.model_copy(
        update={
            "batch": task.batch.model_copy(
                update={
                    "generation_mode": "host_llm_mcp",
                    "required_scenario_set": (materialized.assets[0],),
                }
            )
        }
    )
    uploaded = []

    class StopAfterUpload(Exception):
        pass

    async def capture_upload(machine, task, **values):
        uploaded.append(values["content"])
        raise StopAfterUpload

    monkeypatch.setattr("scripts.selftest.host_product_bridge.upload", capture_upload)
    with pytest.raises(StopAfterUpload):
        await publish_materialized(None, task, materialized=materialized, directory=tmp_path)
    frozen = task.sources[0]
    assert hashlib.sha256(uploaded[0]).hexdigest() == frozen.generation_manifest.sha256
    write_json(tmp_path / "asset.json", materialized.assets[0])
    restored = GeneratedAsset.model_validate(read_json(tmp_path / "asset.json"))
    materialized = materialized.model_copy(update={"assets": (restored,)})
    _independent_manifest(task, materialized, manifest, selection, frozen_task, grant, tmp_path)


def test_strict_quality_contract_cannot_label_partial_coverage_evaluated():
    taskset = QualityTaskSet(
        version="quality-v1", tasks=(QualityTask(task_id="one"), QualityTask(task_id="two"))
    )
    attempt = QualityAttempt(
        task_id="one",
        attempt_id=uuid4(),
        ordinal=1,
        evidence_digest="a" * 64,
        review_mode="ci_fixture",
    )
    report = quality_report(taskset, (attempt,)).model_dump(mode="json")
    report["evaluation_status"] = "EVALUATED"
    with pytest.raises(ValidationError, match="incomplete task coverage"):
        HostQualityReport.model_validate(report)


@pytest.mark.parametrize("change", ["workflow", "case"])
def test_source_completeness_uses_all_independent_published_provenance_findings(change):
    manifest, evidence, materialized, grant = materialization()
    observed = evidence.scenarios[0]
    source = observed.provenance
    if change == "workflow":
        source = source.model_copy(
            update={"workflow": source.workflow.model_copy(update={"fingerprint": "f" * 64})}
        )
    else:
        source = source.model_copy(
            update={"case": source.case.model_copy(update={"workflow_version": 2})}
        )
    evidence = evidence.model_copy(
        update={"scenarios": (observed.model_copy(update={"provenance": source}),)}
    )
    verification = evaluate_host_batch(
        manifest,
        evidence,
        trail=materialized.trail,
        grant=grant,
        now=datetime.fromisoformat(FROZEN) + timedelta(seconds=1),
    )
    assert verification.provenance[0].findings
    taskset = QualityTaskSet(
        version="quality-v1", tasks=(QualityTask(task_id=observed.scenario_id),)
    )
    report = materialized_quality(taskset, materialized, evidence, verification)
    assert (
        next(item for item in report.metrics if item.name == "source_completeness").numerator == 0
    )
