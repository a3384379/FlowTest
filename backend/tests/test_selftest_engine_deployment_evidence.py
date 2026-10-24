"""ASGI draft integration; owned Docker absence is explicitly a substituted unit boundary."""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from test_selftest_engine_dependencies import DependencyContext
from test_selftest_engine_dependencies import dependency_context as dependency_context
from test_selftest_harness import binding_fixture
from test_tasking_api import tasking_context as tasking_context

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest import engine_additional  # noqa: E402
from scripts.selftest.contracts import BatchEvidence, Builds  # noqa: E402
from scripts.selftest.engine_additional import prepare_engine_additional_pack  # noqa: E402
from scripts.selftest.fixed_baseline import execute_fixed_baseline  # noqa: E402
from scripts.selftest.io import write_json  # noqa: E402
from scripts.selftest.verify import verify_batch  # noqa: E402


async def test_all_eleven_use_restricted_ci_child_bindings_and_independent_mock_metrics(
    dependency_context: DependencyContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = dependency_context
    stack_dir = tmp_path / "owned"
    stack_dir.mkdir()
    binding, _ = binding_fixture(stack_dir, monkeypatch)
    deadline = datetime.now(UTC) + timedelta(seconds=600)
    pack = await prepare_engine_additional_pack(
        context.api,
        project_id=context.project,
        service_id=context.service,
        batch_key="engine-deployment-evidence",
        output_dir=tmp_path / "preparation",
        deadline=deadline,
        binding=binding,
    )

    post_count = len(context.api.posts)
    repeated = await prepare_engine_additional_pack(
        context.api,
        project_id=context.project,
        service_id=context.service,
        batch_key="engine-deployment-evidence",
        output_dir=tmp_path / "preparation",
        deadline=deadline,
        binding=binding,
    )
    assert repeated == pack and len(context.api.posts) == post_count
    files = await context.api.object("GET", f"/projects/{context.project}/files?page_size=100")
    assert files["total"] == 1

    async def forward(request: httpx.Request) -> httpx.Response:
        response = await context.target.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx.Response(
            response.status_code, content=response.content, headers=dict(response.headers)
        )

    with respx.mock as routes:
        routes.route(host="fixed-fixture.example").mock(side_effect=forward)
        result = await execute_fixed_baseline(
            context.api,
            context.reader,
            context.observer,
            project_id=context.project,
            environment_id=context.environment,
            service_id=context.service,
            batch_key="engine-deployment-evidence",
            nonce="engine-deployment-nonce-001",
            fixture_digest="a" * 64,
            builds=Builds(
                runner=binding.candidate_image_digest,
                target=binding.candidate_image_digest,
                fixture="a" * 64,
                verifier="draft-independent-observer",
            ),
            output_dir=tmp_path / "result",
            pack=pack,
            deadline=deadline,
        )
    findings = [finding.code for item in result.report.scenarios for finding in item.findings]
    assert findings == ["OWNED_ASSET_DISPOSAL_PENDING"], result.report.model_dump_json(indent=2)
    assert result.report.exit_code == 2
    observed = {item.scenario_id: item for item in result.evidence.scenarios}
    metrics = observed["ST-ADD-parallel-bound"].journal.metrics
    assert metrics.peak_concurrency == 2 and metrics.completed_count == 4
    assert len(metrics.events) == 4 and metrics.complete
    assert len(observed["ST-ADD-dataset-rows"].children) == 2
    assert observed["ST-ADD-subflow-return"].execution.subflows[0].workflow_version == 1
    write_json(stack_dir / "stack.json", binding)
    write_json(
        stack_dir / "cleanup.json", {"project_name": binding.project_name, "status": "completed"}
    )
    monkeypatch.setattr(engine_additional, "_verify_removed", lambda _project: None)
    sealed = engine_additional.finalize_engine_additional_cleanup(
        result, binding=binding, stack_directory=stack_dir, output_dir=tmp_path / "result"
    )
    assert sealed.report.exit_code == 0, sealed.report.model_dump_json(indent=2)
    assert (
        engine_additional.finalize_engine_additional_cleanup(
            sealed, binding=binding, stack_directory=stack_dir, output_dir=tmp_path / "result"
        ).evidence
        == sealed.evidence
    )
    assert sealed.evidence.scenarios[8].execution.status == "cancelled"
    assert sealed.evidence.scenarios[2].execution.status == "failed"
    persisted = json.dumps(sealed.evidence.model_dump(mode="json"))
    assert "Authorization" not in persisted and "access_token" not in persisted
    _assert_specific_tampering(sealed)


def _assert_specific_tampering(result) -> None:
    cases = [
        (
            "FIXTURE_BUDGET_RECEIPT_MISSING",
            lambda value: value["scenarios"][0]["journal"].update(budget=None),
        ),
        (
            "FIXTURE_BUDGET_BINDING_MISMATCH",
            lambda value: value["scenarios"][0]["journal"]["budget"].update(
                parent_batch_key="other-batch"
            ),
        ),
        (
            "FIXTURE_BUDGET_EXCEEDED_OR_INCOMPLETE",
            lambda value: value["scenarios"][0]["journal"]["budget"].update(rejected_count=1),
        ),
        (
            "FIXTURE_BUDGET_REQUESTS_UNSETTLED",
            lambda value: value["scenarios"][0]["journal"]["metrics"].update(
                active_count=1, complete=False
            ),
        ),
        (
            "FIXTURE_BATCH_COUNTER_MISMATCH",
            lambda value: [
                item["journal"]["budget"].update(admitted_count=499) for item in value["scenarios"]
            ],
        ),
        (
            "FIXTURE_METRICS_INCOMPLETE",
            lambda value: value["scenarios"][3]["journal"]["metrics"]["events"].pop(),
        ),
        (
            "FIXTURE_CONCURRENCY_MISMATCH",
            lambda value: value["scenarios"][3]["journal"]["metrics"].update(peak_concurrency=3),
        ),
        (
            "FIXTURE_CONCURRENCY_MISMATCH",
            lambda value: value["scenarios"][3]["journal"]["metrics"]["events"][0].update(
                active_at_begin=99
            ),
        ),
        ("DATASET_CHILDREN_INCOMPLETE", lambda value: value["scenarios"][10]["children"].pop()),
        (
            "DATASET_CHILD_BINDING_MISMATCH",
            lambda value: value["scenarios"][10]["children"][0].update(api_sources=[]),
        ),
        (
            "DATASET_CHILD_ASSERTION_MISMATCH",
            lambda value: next(
                node
                for node in value["scenarios"][10]["children"][0]["nodes"]
                if node["node_id"] == "assert_row_status"
            )["assertions"][0].update(actual_digest="0" * 64),
        ),
        (
            "SUBFLOW_BINDING_MISMATCH",
            lambda value: value["scenarios"][9]["execution"]["subflows"][0].update(
                workflow_version=2
            ),
        ),
        (
            "TOP_NODE_SET_MISMATCH",
            lambda value: value["scenarios"][8]["execution"]["nodes"][1].update(
                error_code="NODE_TIMEOUT"
            ),
        ),
        (
            "OWNED_ASSET_DISPOSAL_PENDING",
            lambda value: value["scenarios"][10].update(target_disposal=None),
        ),
        (
            "OWNED_ASSET_DISPOSAL_MISMATCH",
            lambda value: value["scenarios"][10]["target_disposal"].update(
                target_volume="foreign-volume"
            ),
        ),
    ]
    for expected, tamper in cases:
        value = result.evidence.model_dump(mode="json")
        tamper(value)
        changed = BatchEvidence.model_validate(value)
        report = verify_batch(result.manifest, changed)
        assert report.exit_code != 0
        assert expected in {finding.code for finding in report.findings} | {
            finding.code for scenario in report.scenarios for finding in scenario.findings
        }, report.model_dump_json(indent=2)


def test_dataset_cannot_skip_owned_asset_requirement() -> None:
    from scripts.selftest.contracts import BatchManifest, ExpectedOutcome
    from scripts.selftest.verify_engine_additional import _disposal
    from test_selftest_verification import evidence_payload, manifest_payload

    manifest = BatchManifest.model_validate(manifest_payload())
    evidence = BatchEvidence.model_validate(evidence_payload())
    dataset = (
        engine_additional.load_core_pack(engine_additional.PACK).expectations[-1].expected.dataset
    )
    expectation = ExpectedOutcome(execution_status="passed", dataset=dataset)
    findings = _disposal(manifest, expectation, evidence.scenarios[0])
    assert [item.code for item in findings] == ["OWNED_ASSET_DISPOSAL_REQUIREMENT_MISSING"]
