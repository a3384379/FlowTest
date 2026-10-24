"""Assisted contracts use real public proposals; seeded seals are not live O acceptance."""

import base64
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

import pytest
from test_selftest_product_api import ProductContext
from test_selftest_product_api import product as product
from test_selftest_product_sources import _materialized
from test_selftest_retention import owned_storage as owned_storage
from test_tasking_api import tasking_context as tasking_context

from app.core.errors import AppError
from app.core.self_tests import get_self_test_settings
from app.domain.assisted_revisions import RevisionDifferenceLimit, revision_differences
from app.domain.self_tests import document_digest
from app.main import app
from app.models.ai import AIChangeSet
from app.models.self_tests import SelfTestBatch
from app.schemas.self_tests import SourceReference
from app.services.self_test_assisted import SelfTestAssistedSources

OLD_GRANT = "a" * 64
NEW_GRANT = "b" * 64


async def assisted_contract(product: ProductContext) -> tuple[dict, dict, dict]:
    """A deliberately synthetic before seal, followed by real human API review/publication."""
    config = product.config.model_copy(
        update={
            "principals": tuple(
                item.model_copy(update={"authorized_host_budget_digests": (OLD_GRANT, NEW_GRANT)})
                if item.id == "h"
                else item
                for item in product.config.principals
            )
        }
    )
    app.dependency_overrides[get_self_test_settings] = lambda: config
    before, original = await _materialized(product, mode="host_llm_mcp")
    original["sources"][0]["host_evidence"] = {
        "host": "synthetic-host",
        "model": "synthetic-model",
        "skill_digest": "1" * 64,
        "prompt_digest": "2" * 64,
        "authorized_budget_digest": OLD_GRANT,
        "actual_tool_calls": 40,
    }
    before = await product.post(
        product.agent + f"/runs/{before['id']}/materialized", original, machine="h"
    )
    async with product.native.session_maker() as session:
        model = await session.get(SelfTestBatch, UUID(before["id"]))
        assert model is not None
        model.phase, model.verdict, model.readiness = "completed", "failed", "ready"
        model.sealed_at, model.evidence_integrity, model.cleanup_status = (
            datetime.now(UTC),
            "complete",
            "completed",
        )
        model.artifact_refs = [original["manifest"]]
        await session.commit()
    after = await product.post(
        product.root + f"/installations/{before['installation_id']}/generation-batches",
        {
            "scenario_ids": ["ST-MCP-026"],
            "verification_scope": "diagnostic_subset",
            "generation_mode": "host_llm_mcp",
            "assisted_before_batch_id": before["id"],
        },
        key="assisted-new-batch",
        status=202,
    )
    task = await product.post(
        product.agent + f"/runs/{after['id']}/claim",
        {"expected_revision": after["revision"], "nonce": "assisted-" + "8" * 32},
        machine="h",
    )
    assert len(task["before_sources"]) == 1
    root = f"/api/v1/projects/{product.project_id}"
    original_workflow = product.mapping.assets[0].workflow.id
    exported = await product.get(root + f"/flow-specs/workflows/{original_workflow}/export")
    original_detail = await product.get(root + f"/workflows/{original_workflow}")
    api_node = next(
        node for node in original_detail["draft_definition"]["nodes"] if node["type"] == "api"
    )
    mappings = {
        item["ref"]: api_node["config"]["api_definition_id"]
        for item in exported["spec"]["operations"]
    }
    proposal = await product.post(
        root + "/flow-specs/imports",
        {
            "spec": {**exported["spec"], "name": "Assisted revision workflow"},
            "operation_mappings": mappings,
            "operation_version_mappings": {key: 1 for key in mappings},
        },
        status=201,
    )
    proposal_path = root + f"/flow-specs/change-sets/{proposal['id']}"
    await product.post(proposal_path + "/review", {"accept": True, "note": "Reviewed revision"})
    applied = await product.post(proposal_path + "/apply", {})
    version = await product.post(root + f"/workflows/{applied['workflow_id']}/versions", {})
    workflow = await product.get(root + f"/workflows/{applied['workflow_id']}")
    body = {
        "project_id": str(product.project_id),
        "idempotency_key": "assisted-case-user",
        "dry_run": False,
        "title": "人工修订固定用例",
        "confidence": 1,
        "risk_level": "high",
        "design": {
            "intent": {
                "key": "source.normalization",
                "objective": "核对实际审核发布图",
                "acceptance_criteria": ["断言实际值"],
            },
            "oracles": [
                {
                    "id": "actual",
                    "kind": "json_path",
                    "confidence": 1,
                    "expression": "body.actual",
                    "expected": 1,
                }
            ],
        },
        "test_cases": [
            {
                "name": "人工修订 Case",
                "definition": {
                    "workflow_id": workflow["id"],
                    "workflow_version": 1,
                    "environment_id": str(product.mapping.environment_id),
                },
            }
        ],
    }
    case_proposal = (
        await product.post(
            product.root + f"/runs/{after['id']}/assisted-case-proposals", body, status=202
        )
    )["data"]
    review = "/api/v1/mcp/write/change-sets/" + case_proposal["id"]
    approval = (await product.post(review + "/approve", {"note": "隔离 fixture 人工审核"}))["data"][
        "approval"
    ]["id"]
    for item in case_proposal["items"]:
        reviewed = (
            await product.post(
                review + f"/items/{item['id']}/accept", {"approval_id": approval, "note": "接受"}
            )
        )["data"]
    case_item = next(item for item in reviewed["items"] if item["item_type"] == "test_case")
    case_id = case_item["materialized_resource_id"]
    case_version = await product.post(
        f"/api/v1/projects/{product.project_id}/test-cases/{case_id}/versions",
        {"change_note": "辅助版本"},
    )
    lease = {"lease_token": task["lease_token"], "nonce": task["nonce"]}
    manifest = await product.post(
        product.agent + f"/runs/{after['id']}/artifacts",
        {
            **lease,
            "kind": "generation",
            "filename": "assisted.json",
            "content_base64": base64.b64encode(b'{"synthetic_contract":true}').decode(),
        },
        machine="h",
        status=201,
    )
    old_source = SourceReference.model_validate(original["sources"][0])
    source = deepcopy(original["sources"][0])
    source.update(
        workflow={"id": workflow["id"], "version": 1, "fingerprint": version["fingerprint"]},
        case={"id": case_id, "version": 1, "fingerprint": case_version["fingerprint"]},
        generation_manifest=manifest,
        fixture_batch_key=before["batch_key"],
        workflow_proposal={
            "change_set_id": proposal["id"],
            "route": "flow_spec_visual",
            "content_fingerprint": proposal["source_fingerprint"],
            "review_status": "accepted",
            "materialized_resource_id": workflow["id"],
        },
        case_proposal={
            "change_set_id": case_proposal["id"],
            "item_id": case_item["id"],
            "route": "controlled_write",
            "content_fingerprint": case_proposal["source_fingerprint"],
            "review_status": "accepted",
            "materialized_resource_id": case_id,
        },
    )
    async with product.native.session_maker() as session:
        editor = await session.get(AIChangeSet, UUID(proposal["id"]))
        assert editor is not None
        after_source = SourceReference.model_validate(source)
        service = SelfTestAssistedSources(session, config)
        old, new = await service._definitions(old_source), await service._definitions(after_source)
        changes = [
            dict(path=item.path, before_digest=item.before_digest, after_digest=item.after_digest)
            for item in revision_differences(old, new)
        ]
        actor_id = str(editor.created_by_id)
    source["assisted"] = {
        "authorization_digest": NEW_GRANT,
        "before_batch_id": before["id"],
        "origin_batch_id": before["id"],
        "before_source_digest": document_digest(old_source),
        "before_workflow": original["sources"][0]["workflow"],
        "before_case": original["sources"][0]["case"],
        "before_workflow_proposal": original["sources"][0]["workflow_proposal"],
        "before_case_proposal": original["sources"][0]["case_proposal"],
        "editor_id": actor_id,
        "workflow_reviewer_id": actor_id,
        "case_reviewer_id": actor_id,
        "reason_digest": "c" * 64,
        "diff_digest": document_digest(changes),
        "changes": changes,
        "revision_number": 1,
        "review_mode": "ci_fixture",
    }
    return task, before, {**lease, "sources": [source], "manifest": manifest}


async def test_assisted_new_batch_keeps_origin_and_real_manual_reviews(
    product: ProductContext, owned_storage: object
) -> None:
    task, before, payload = await assisted_contract(product)
    current = await product.post(
        product.agent + f"/runs/{task['task_id']}/materialized", payload, machine="h"
    )
    assert current["phase"] == "ready" and current["resource_digest"] != before["resource_digest"]
    assert current["id"] != before["id"] and current["plan_run_ids"] == []
    origin = await product.get(product.root + f"/runs/{before['id']}")
    assert origin["sealed_verdict"] == origin["verdict"] == "failed"
    assert origin["resource_digest"] == before["resource_digest"]


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("authorization_digest", "d" * 64, "SELFTEST_HOST_EVIDENCE_UNAUTHORIZED"),
        ("editor_id", "00000000-0000-0000-0000-000000000001", "SELFTEST_ASSISTED_EDITOR_MISMATCH"),
        (
            "workflow_reviewer_id",
            "00000000-0000-0000-0000-000000000001",
            "SELFTEST_ASSISTED_REVIEWER_MISMATCH",
        ),
        ("diff_digest", "d" * 64, "SELFTEST_ASSISTED_DIFF_MISMATCH"),
        ("before_source_digest", "d" * 64, "SELFTEST_ASSISTED_BEFORE_SOURCE_CHANGED"),
    ],
)
async def test_assisted_rejects_unproved_receipts(
    product: ProductContext, owned_storage: object, field: str, value: str, code: str
) -> None:
    task, _, payload = await assisted_contract(product)
    payload["sources"][0]["assisted"][field] = value
    error = await product.post(
        product.agent + f"/runs/{task['task_id']}/materialized",
        payload,
        machine="h",
        status=403 if field == "authorization_digest" else 409,
    )
    assert error["error"]["code"] == code
    assert product.native.queue.test_plan_run_ids == []


def test_revision_diff_canonical_types_missing_null_and_escaped_keys() -> None:
    changes = revision_differences(
        {"workflow": {"missing": None, "truth": True, "a.b": 1}},
        {"workflow": {"truth": 1, "a.b": 2, "new": None}},
    )
    assert [item.path for item in changes] == [
        '$.workflow["a.b"]',
        "$.workflow.missing",
        "$.workflow.new",
        "$.workflow.truth",
    ]
    assert changes[1].after_digest is None and changes[1].before_digest == document_digest(None)
    assert changes[2].before_digest is None and changes[2].after_digest == document_digest(None)
    assert changes[3].before_digest != changes[3].after_digest
    with pytest.raises(RevisionDifferenceLimit):
        revision_differences({"workflow": {}}, {"workflow": {str(i): i for i in range(201)}})


@pytest.mark.parametrize(
    "field",
    [
        "design_fingerprint",
        "compilation_fingerprint",
        "protocol_receipts_digest",
        "api_sources_digest",
        "oracle_mapping_digest",
    ],
)
async def test_assisted_cannot_replace_original_golden(
    product: ProductContext, owned_storage: object, field: str
) -> None:
    task, _, payload = await assisted_contract(product)
    payload["sources"][0][field] = "d" * 64
    error = await product.post(
        product.agent + f"/runs/{task['task_id']}/materialized", payload, machine="h", status=409
    )
    assert error["error"]["code"] == "SELFTEST_ASSISTED_GOLDEN_CHANGED"


async def test_assisted_keeps_origin_host_trail_and_fixture_scope(
    product: ProductContext, owned_storage: object
) -> None:
    task, _, payload = await assisted_contract(product)
    original = deepcopy(payload)
    payload["sources"][0]["host_evidence"]["actual_tool_calls"] = 1
    error = await product.post(
        product.agent + f"/runs/{task['task_id']}/materialized", payload, machine="h", status=409
    )
    assert error["error"]["code"] == "SELFTEST_ASSISTED_ORIGIN_CHANGED"
    original["sources"][0]["fixture_batch_key"] = "other-batch"
    error = await product.post(
        product.agent + f"/runs/{task['task_id']}/materialized", original, machine="h", status=409
    )
    assert error["error"]["code"] == "SELFTEST_ASSISTED_FIXTURE_SCOPE_INVALID"


async def test_assisted_source_expiry_blocks_materialization(
    product: ProductContext, owned_storage: object
) -> None:
    from app.models.artifacts import Artifact

    task, _, payload = await assisted_contract(product)
    async with product.native.session_maker() as session:
        artifact = await session.get(
            Artifact, UUID(task["before_sources"][0]["artifacts"][0]["id"])
        )
        assert artifact is not None
        await owned_storage.delete(key=artifact.object_key)
    error = await product.post(
        product.agent + f"/runs/{task['task_id']}/materialized", payload, machine="h", status=409
    )
    assert error["error"]["code"] == "SELFTEST_ASSISTED_BEFORE_EVIDENCE_UNAVAILABLE"
    assert product.native.queue.test_plan_run_ids == []


async def test_assisted_sealed_history_retains_before_availability(
    product: ProductContext, owned_storage: object
) -> None:
    from app.models.artifacts import Artifact

    task, before, payload = await assisted_contract(product)
    await product.post(
        product.agent + f"/runs/{task['task_id']}/materialized", payload, machine="h"
    )
    async with product.native.session_maker() as session:
        model = await session.get(SelfTestBatch, UUID(task["task_id"]))
        assert model is not None
        model.phase, model.verdict = "completed", "passed"
        model.sealed_at, model.evidence_integrity, model.cleanup_status = (
            datetime.now(UTC),
            "complete",
            "completed",
        )
        model.artifact_refs = [payload["manifest"]]
        artifact = await session.get(
            Artifact, UUID(task["before_sources"][0]["artifacts"][0]["id"])
        )
        assert artifact is not None
        await owned_storage.delete(key=artifact.object_key)
        await session.commit()
    current = await product.get(product.root + f"/runs/{task['task_id']}")
    assert (current["verdict"], current["sealed_verdict"], current["evidence_integrity"]) == (
        "blocked",
        "passed",
        "expired",
    )
    origin = await product.get(product.root + f"/runs/{before['id']}")
    assert origin["sealed_verdict"] == "failed"


async def test_assisted_no_model_charge_and_machine_cannot_propose_as_user(
    product: ProductContext, owned_storage: object
) -> None:
    task, _, _payload = await assisted_contract(product)
    response = await product.native.client.post(
        product.root + f"/runs/{task['task_id']}/assisted-case-proposals",
        headers=product.machine("h"),
        json={},
    )
    assert response.status_code == 401
    error = await product.post(
        product.agent + f"/runs/{task['task_id']}/generation",
        {
            "lease_token": task["lease_token"],
            "nonce": task["nonce"],
            "stage": "designing",
            "readiness": "needs_input",
            "tool_call_count": 1,
            "proposals": [],
        },
        machine="h",
        status=409,
    )
    assert error["error"]["code"] == "SELFTEST_ASSISTED_MODEL_CALL_UNEXPECTED"


async def test_assisted_before_selection_cannot_be_shrunk_or_relabelled(
    product: ProductContext, owned_storage: object
) -> None:
    _, before, _ = await assisted_contract(product)
    error = await product.post(
        product.root + f"/installations/{before['installation_id']}/generation-batches",
        {
            "scenario_ids": ["ST-MCP-025"],
            "verification_scope": "diagnostic_subset",
            "generation_mode": "host_llm_mcp",
            "assisted_before_batch_id": before["id"],
        },
        key="assisted-shrunk",
        status=409,
    )
    assert error["error"]["code"] == "SELFTEST_ASSISTED_SELECTION_CHANGED"
    error = await product.post(
        product.root + f"/installations/{before['installation_id']}/generation-batches",
        {
            "generation_mode": "deterministic_mcp",
            "assisted_before_batch_id": before["id"],
        },
        key="assisted-relabelled",
        status=409,
    )
    assert error["error"]["code"] == "SELFTEST_ASSISTED_MODE_INVALID"


async def test_assisted_required_assertion_cannot_weaken_operator_or_expected(
    product: ProductContext, owned_storage: object
) -> None:
    task, _, payload = await assisted_contract(product)
    source = SourceReference.model_validate(payload["sources"][0])
    async with product.native.session_maker() as session:
        service = SelfTestAssistedSources(session, product.config)
        before = SourceReference.model_validate(task["before_sources"][0]["source"])
        definitions = await service._definitions(before)
    for field, value in (("operator", "not_equals"), ("expected", 999)):
        changed = deepcopy(definitions["workflow"])
        node = next(
            node for node in changed["nodes"] if node["id"] == source.oracle_bindings[0].node_id
        )
        node["config"][field] = value
        with pytest.raises(AppError) as caught:
            service._required_assertions(before, definitions["workflow"], changed)
        assert caught.value.code == "SELFTEST_ASSISTED_REQUIRED_ORACLE_CHANGED"


async def test_assisted_execution_rechecks_before_evidence_before_queue(
    product: ProductContext, owned_storage: object
) -> None:
    from app.models.artifacts import Artifact

    task, _, payload = await assisted_contract(product)
    ready = await product.post(
        product.agent + f"/runs/{task['task_id']}/materialized", payload, machine="h"
    )
    async with product.native.session_maker() as session:
        artifact = await session.get(
            Artifact, UUID(task["before_sources"][0]["artifacts"][0]["id"])
        )
        assert artifact is not None
        await owned_storage.delete(key=artifact.object_key)
    error = await product.post(
        product.root + f"/runs/{task['task_id']}/execute-materialized",
        {
            "resource_digest": ready["resource_digest"],
            "environment_fingerprint": ready["environment_fingerprint"],
            "confirmed": True,
        },
        key="assisted-expired-execution",
        status=409,
    )
    assert error["error"]["code"] == "SELFTEST_ASSISTED_BEFORE_EVIDENCE_UNAVAILABLE"
    assert product.native.queue.test_plan_run_ids == []
