"""Synthetic O fixtures for reviewed revisions; no model or human acceptance claim."""

import hashlib
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import canonical_digest  # noqa: E402
from scripts.selftest.host_assisted import archived_grant, differences  # noqa: E402
from scripts.selftest.host_assisted_verify import (  # noqa: E402
    _delta,
    evaluate_assisted_batch,
    validate_assisted,
)
from scripts.selftest.host_launch import VerifiedGrant  # noqa: E402
from scripts.selftest.host_materialized import (  # noqa: E402
    HostMaterialization,
    HostRevision,
    HostSelection,
)
from scripts.selftest.host_product_bridge import materialized_source  # noqa: E402
from scripts.selftest.host_prompts import HostTask  # noqa: E402
from scripts.selftest.host_quality import QualityTask, QualityTaskSet  # noqa: E402
from scripts.selftest.host_quality_evidence import materialized_quality  # noqa: E402
from scripts.selftest.host_revisions import AssistedRequest, AssistedSelection  # noqa: E402
from scripts.selftest.host_runtime_config import HostRuntimeConfig  # noqa: E402
from scripts.selftest.host_verify import evaluate_host_batch  # noqa: E402
from scripts.selftest.io import HarnessError, write_json  # noqa: E402
from test_selftest_host_quality_boundaries import materialization  # noqa: E402

from app.domain.test_design import TestDesignDocument as DesignDocument  # noqa: E402
from app.domain.test_design import fingerprint_design  # noqa: E402
from app.engine.contracts import WorkflowDefinition  # noqa: E402
from app.schemas.self_tests import (  # noqa: E402
    AgentTaskResponse,
    ArtifactReference,
    AssistedBeforeSource,
    AssistedLineage,
    BatchResponse,
    FrozenBatchManifest,
)


def fixture(tmp_path):
    manifest, evidence, original, old_grant = materialization()
    source = evidence.scenarios[0].provenance
    design = DesignDocument.model_validate(
        {
            "intent": {
                "key": "assisted-fixture",
                "objective": "原合成生成设计",
                "acceptance_criteria": ["保留合成黄金"],
            },
            "oracles": [
                {
                    "id": "oracle-canary",
                    "kind": "json_path",
                    "confidence": 1,
                    "expression": "body.actual",
                    "expected": 2,
                }
            ],
        }
    )
    definition = WorkflowDefinition.model_validate(
        {
            "nodes": [
                {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
                {
                    "id": "assert_canary",
                    "type": "assert",
                    "name": "固定断言",
                    "position": {"x": 100, "y": 0},
                    "config": {"expression": "body.actual", "operator": "eq", "expected": 2},
                },
                {"id": "end", "type": "end", "name": "结束", "position": {"x": 200, "y": 0}},
            ],
            "edges": [
                {"id": "first", "source": "start", "target": "assert_canary"},
                {"id": "last", "source": "assert_canary", "target": "end"},
            ],
        }
    ).model_dump(mode="json", exclude_none=True)
    asset = original.assets[0].model_copy(
        update={
            "design": design.model_dump(mode="json"),
            "design_fingerprint": fingerprint_design(design),
            "workflow": original.assets[0].workflow.model_copy(
                update={
                    "version": {**original.assets[0].workflow.version, "definition": definition}
                }
            ),
            "case": original.assets[0].case.model_copy(
                update={
                    "version": {
                        **original.assets[0].case.version,
                        "definition": {
                            "workflow_id": str(source.workflow.id),
                            "workflow_version": 1,
                            "environment_id": str(source.case.environment_id),
                        },
                    }
                }
            ),
        }
    )
    original = HostMaterialization.model_validate(
        original.model_copy(update={"assets": (asset,)}).model_dump(mode="json")
    )
    observed = evidence.scenarios[0].model_copy(
        update={
            "provenance": source.model_copy(update={"design_fingerprint": asset.design_fingerprint})
        }
    )
    evidence = evidence.model_copy(update={"scenarios": (observed,)})
    before_id = uuid4()
    old_dir = tmp_path / str(before_id)
    write_json(old_dir / "host-materialized.json", original)
    old_report = evaluate_host_batch(
        manifest, evidence, trail=original.trail, grant=old_grant, now=evidence.collected_at
    ).report
    assert old_report.batch_verdict == "passed"
    refs = []
    for kind, name, value in (
        ("manifest", "manifest.json", manifest),
        ("evidence", "evidence.json", evidence),
        ("verification", "verification.json", old_report),
    ):
        write_json(old_dir / name, value)
        refs.append(
            ArtifactReference(
                id=uuid4(),
                sha256=hashlib.sha256((old_dir / name).read_bytes()).hexdigest(),
                kind=kind,
            )
        )
    generation = ArtifactReference(
        id=uuid4(), sha256=canonical_digest(asset.model_dump(mode="json")), kind="generation"
    )
    before_source = materialized_source(original, asset, generation)
    before = AssistedBeforeSource(
        batch_id=before_id,
        batch_key=manifest.batch_key,
        scenario_id=asset.scenario_id,
        variant_key=asset.variant_key,
        source=before_source,
        source_digest=canonical_digest(before_source.model_dump(mode="json")),
        artifacts=tuple(refs),
        sealed_at=evidence.collected_at,
        verdict=old_report.batch_verdict,
        evidence_integrity="complete",
        cleanup_status="completed",
        resource_digest="a" * 64,
        policy_digest=manifest.policy_digest,
        builds=manifest.builds.model_dump(),
    )
    after_workflow = uuid4()
    after_case = uuid4()
    author = old_grant.authorization.reviewer_ids[0]
    chosen = AssistedSelection(
        scenario_id=asset.scenario_id,
        variant_key=asset.variant_key,
        workflow_proposal_id=uuid4(),
        case_proposal_id=uuid4(),
        case_item_id=uuid4(),
        editor_id=author,
        reason="修订请求并保留所有黄金断言",
    )
    taskset = QualityTaskSet(
        version="assisted-unit-v1", tasks=(QualityTask(task_id=asset.scenario_id),)
    )
    frozen_task = HostTask(
        project_id=manifest.project_id,
        batch_key="after-assistance",
        quality_taskset=taskset,
        objective="受控修订表征",
        selections=(
            HostSelection(
                scenario_id=asset.scenario_id,
                variant_key=asset.variant_key,
                api_source=asset.api_source,
                design_kind="happy_path",
            ),
        ),
        authorized_data_digest="a" * 64,
        assisted=AssistedRequest(before_batch_id=before_id, selections=(chosen,)),
    )
    auth = old_grant.authorization.model_copy(
        update={
            "authorization_id": uuid4(),
            "batch_key": frozen_task.batch_key,
            "task_digest": canonical_digest(frozen_task.model_dump(mode="json")),
            "review_mode": "ci_fixture",
        }
    )
    grant = VerifiedGrant(auth, canonical_digest(auth.model_dump(mode="json")))
    after_definition = {**definition, "variables": {"repair": "synthetic-fixture"}}
    after = asset.model_copy(
        update={
            "frozen_at": asset.frozen_at + timedelta(seconds=10),
            "workflow": asset.workflow.model_copy(
                update={
                    "workflow": {"id": str(after_workflow)},
                    "version": {
                        "version": 1,
                        "fingerprint": "b" * 64,
                        "definition": after_definition,
                    },
                    "proposal": asset.workflow.proposal.model_copy(
                        update={
                            "proposal_id": chosen.workflow_proposal_id,
                            "materialized_resource_id": after_workflow,
                            "reviewer_id": author,
                        }
                    ),
                }
            ),
            "case": asset.case.model_copy(
                update={
                    "case": {"id": str(after_case)},
                    "version": {
                        "version": 1,
                        "fingerprint": "c" * 64,
                        "definition": {
                            "workflow_id": str(after_workflow),
                            "workflow_version": 1,
                            "environment_id": str(source.case.environment_id),
                        },
                    },
                    "proposal": asset.case.proposal.model_copy(
                        update={
                            "proposal_id": chosen.case_proposal_id,
                            "item_id": chosen.case_item_id,
                            "materialized_resource_id": after_case,
                            "reviewer_id": author,
                        }
                    ),
                }
            ),
        }
    )
    left = {"workflow": definition, "case": asset.case.version["definition"]}
    right = {"workflow": after_definition, "case": after.case.version["definition"]}
    # Normalize default Case fields just as the public published readers do.
    from app.schemas.test_assets import PublishedTestCaseDefinition

    left["case"] = PublishedTestCaseDefinition.model_validate(left["case"]).model_dump(
        mode="json", exclude_none=True
    )
    right["case"] = PublishedTestCaseDefinition.model_validate(right["case"]).model_dump(
        mode="json", exclude_none=True
    )
    changes = differences(left, right)
    lineage = AssistedLineage(
        authorization_digest=grant.digest,
        before_batch_id=before_id,
        origin_batch_id=before_id,
        before_source_digest=before.source_digest,
        before_workflow=before_source.workflow,
        before_case=before_source.case,
        before_workflow_proposal=before_source.workflow_proposal,
        before_case_proposal=before_source.case_proposal,
        editor_id=author,
        workflow_reviewer_id=author,
        case_reviewer_id=author,
        reason_digest=canonical_digest(chosen.reason),
        diff_digest=canonical_digest([item.model_dump(mode="json") for item in changes]),
        changes=changes,
        revision_number=1,
        review_mode="ci_fixture",
    )
    result = HostMaterialization(
        attempt_id=uuid4(),
        authorization_digest=grant.digest,
        task_digest=auth.task_digest,
        catalog_digest=original.catalog_digest,
        host=original.host,
        assets=(after,),
        trail=original.trail,
        revisions=(
            HostRevision(
                scenario_id=asset.scenario_id,
                variant_key=asset.variant_key,
                origin_batch_key=manifest.batch_key,
                fixture_batch_key=manifest.batch_key,
                lineage=lineage,
            ),
        ),
    )
    after_manifest = manifest.model_copy(
        update={
            "batch_key": frozen_task.batch_key,
            "created_at": manifest.created_at + timedelta(seconds=5),
            "scenarios": tuple(
                item.model_copy(update={"fixture_batch_key": manifest.batch_key})
                for item in manifest.scenarios
            ),
        }
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    approval = tmp_path / "approval.pem"
    approval.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    approval.chmod(0o600)
    token = tmp_path / "archived.jwt"
    token.write_text(
        jwt.encode(
            {
                "iss": "approval",
                "aud": "host",
                "sub": old_grant.authorization.approved_by,
                "iat": int(manifest.created_at.timestamp()),
                "exp": int(manifest.expires_at.timestamp()),
                "authorization": old_grant.authorization.model_dump(mode="json"),
            },
            key,
            algorithm="RS256",
        )
    )
    token.chmod(0o600)
    config = HostRuntimeConfig.model_construct(
        approval_key_file=approval,
        approval_algorithm="RS256",
        approval_issuer="approval",
        approval_audience="host",
        archived_authorization_files=(token,),
        allowed_authorization_digests=(old_grant.digest, grant.digest),
    )
    task = AgentTaskResponse.model_construct(
        frozen_manifest=FrozenBatchManifest.model_construct(assisted_before_batch_id=before_id),
        before_sources=(before,),
        batch=BatchResponse.model_construct(batch_key=frozen_task.batch_key),
    )
    return (
        task,
        result,
        frozen_task,
        grant,
        config,
        tmp_path / str(uuid4()),
        after_manifest,
        evidence,
    )


def test_checked_revision_preserves_original_calls_and_is_only_assisted_quality(tmp_path):
    task, result, frozen_task, grant, config, directory, manifest, evidence = fixture(tmp_path)
    validated = validate_assisted(task, result, frozen_task, grant, config, directory, manifest)
    assert result.trail.receipts[0].attempt_id != result.attempt_id
    assert result.assets[0].calls[0].batch_key != manifest.batch_key
    actual = evidence.scenarios[0]
    after = result.assets[0]
    source = actual.provenance.model_copy(
        update={
            "batch_key": manifest.batch_key,
            "assisted": True,
            "design_fingerprint": after.design_fingerprint,
            "frozen_at": after.frozen_at,
            "workflow_proposal": after.workflow.proposal,
            "case_proposal": after.case.proposal,
            "workflow": actual.provenance.workflow.model_copy(
                update={"id": UUID(after.workflow.workflow["id"]), "fingerprint": "b" * 64}
            ),
            "case": actual.provenance.case.model_copy(
                update={
                    "id": UUID(after.case.case["id"]),
                    "workflow_id": UUID(after.workflow.workflow["id"]),
                    "fingerprint": "c" * 64,
                }
            ),
            "run": actual.provenance.run.model_copy(
                update={
                    "target_id": UUID(after.case.case["id"]),
                    "workflow_id": UUID(after.workflow.workflow["id"]),
                }
            ),
        }
    )
    execution = actual.execution.model_copy(
        update={
            "workflow_id": source.workflow.id,
            "workflow_fingerprint": "b" * 64,
            "started_at": manifest.created_at + timedelta(seconds=20),
            "completed_at": manifest.created_at + timedelta(seconds=21),
        }
    )
    observed = actual.model_copy(
        update={"provenance": source, "execution": execution, "attempts": (execution,)}
    )
    evidence = evidence.model_copy(
        update={
            "batch_key": manifest.batch_key,
            "collected_at": manifest.created_at + timedelta(seconds=22),
            "scenarios": (observed,),
        }
    )
    verified = evaluate_assisted_batch(
        manifest, evidence, validated=validated, now=evidence.collected_at
    )
    assert verified.report.batch_verdict == "passed", (
        [item.code for item in verified.report.findings],
        [[item.code for item in row.findings] for row in verified.report.scenarios],
    )
    quality = materialized_quality(frozen_task.quality_taskset, result, evidence, verified)
    metrics = {item.name: item for item in quality.metrics}
    assert metrics["first_generation_execution_match"].denominator == 0
    assert (
        metrics["assisted_execution_match"].numerator,
        metrics["assisted_execution_match"].denominator,
    ) == (1, 1)
    assert metrics["protocol_availability"].denominator == 0


@pytest.mark.parametrize("change", ["before_source", "reason", "tool_result", "artifact", "diff"])
def test_frozen_revision_mutations_block_before_any_new_run_read(change, tmp_path):
    task, result, frozen_task, grant, config, directory, manifest, _ = fixture(tmp_path)
    if change == "before_source":
        task = task.model_copy(update={"before_sources": ()})
    elif change == "reason":
        chosen = frozen_task.assisted.selections[0].model_copy(update={"reason": "other reason"})
        frozen_task = frozen_task.model_copy(
            update={"assisted": frozen_task.assisted.model_copy(update={"selections": (chosen,)})}
        )
    elif change == "tool_result":
        result = result.model_copy(
            update={
                "trail": result.trail.model_copy(update={"stop": None, "task_digest": "f" * 64})
            }
        )
    elif change == "artifact":
        path = directory.parent / str(frozen_task.assisted.before_batch_id) / "evidence.json"
        path.write_text("{}")
    else:
        revision = result.revisions[0]
        result = result.model_copy(
            update={
                "revisions": (
                    revision.model_copy(
                        update={
                            "lineage": revision.lineage.model_copy(update={"diff_digest": "f" * 64})
                        }
                    ),
                )
            }
        )
    with pytest.raises(HarnessError):
        validate_assisted(task, result, frozen_task, grant, config, directory, manifest)


def test_diff_paths_distinguish_header_literal_dots_brackets_and_unicode():
    left = {"workflow": {"headers": {"a.b": 1, "a": {"b": 1}, "中[文]": False}}}
    right = {"workflow": {"headers": {"a.b": 2, "a": {"b": 2}, "中[文]": None}}}
    changes = differences(left, right)
    assert tuple((item.path, item.before_digest, item.after_digest) for item in changes) == _delta(
        left, right
    )
    assert {item.path for item in changes} == {
        '$.workflow.headers["a.b"]',
        "$.workflow.headers.a.b",
        '$.workflow.headers["中[文]"]',
    }


def test_archived_approval_is_not_reusable_outside_recorded_lifetime(tmp_path):
    _, result, _, _, config, _, _, _ = fixture(tmp_path)
    with pytest.raises(HarnessError, match="TIME_CHANGED"):
        archived_grant(
            config,
            result.host.authorized_budget_digest,
            datetime.fromisoformat("2100-01-01T00:00:00+00:00"),
        )
