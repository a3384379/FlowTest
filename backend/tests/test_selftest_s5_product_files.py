"""Native A calls separate B file APIs; ASGI facts do not imply deployment acceptance."""

import base64
import sys
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import respx
from test_artifacts_and_auth_api import MemoryObjectStorage
from test_selftest_ci_runner_lineage import binding as synthetic_binding
from test_selftest_engine_dependencies import DependencyContext
from test_selftest_engine_dependencies import dependency_context as dependency_context
from test_selftest_native_api_pack import identity, isolated_target, target_environment
from test_tasking_api import TaskingTestContext
from test_tasking_api import tasking_context as tasking_context

from app.core.config import RuntimeProfile, settings
from app.main import app

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))
from scripts.selftest.bootstrap import Installation  # noqa: E402
from scripts.selftest.contracts import Builds  # noqa: E402
from scripts.selftest.io import PublicAPI  # noqa: E402
from scripts.selftest.native_api_pack import execute_native_api_pack  # noqa: E402
from scripts.selftest.s5_product_files import prepare_pack  # noqa: E402
from scripts.selftest.verify import verify_batch  # noqa: E402


@pytest.mark.asyncio
async def test_native_product_file_is_uploaded_downloaded_and_independently_read_by_viewer(
    dependency_context: DependencyContext,
    tasking_context: TaskingTestContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = dependency_context
    monkeypatch.setattr(settings, "runtime_profile", RuntimeProfile.STANDALONE)
    monkeypatch.setattr("app.services.artifacts.object_storage", MemoryObjectStorage())
    a_project = await context.api.object("GET", f"/projects/{context.project}")
    capture, capture_token, _ = await identity(
        context.api,
        tasking_context.client,
        email="s5-file-capture@example.com",
        project=context.project,
        organization=str(a_project["organization_id"]),
    )
    capture_reader = PublicAPI(
        "http://test",
        capture_token,
        str(a_project["organization_id"]),
        transport=httpx.ASGITransport(app=app),
    )
    bound = synthetic_binding().model_copy(
        update={"target_internal_url": "http://native-b.example"}
    )
    try:
        async with isolated_target(tmp_path) as (target_app, b_client, b):
            project = await b.object("POST", "/projects", {"name": "S5合成文件隔离项目"})
            bp, bo = str(project["id"]), str(project["organization_id"])
            b.set_organization(bo)
            actor, _, password = await identity(
                b,
                b_client,
                email="s5-file-actor@example.com",
                project=bp,
                organization=bo,
                role="owner",
            )
            viewer, viewer_token, _ = await identity(
                b, b_client, email="s5-file-viewer@example.com", project=bp, organization=bo
            )
            await context.api.object(
                "PUT",
                f"/projects/{context.project}/secrets",
                {"name": "SELFTEST_B_PASSWORD", "value": password},
            )
            env, service = await target_environment(context.api, context.project)
            installed = Installation(
                binding_nonce=bound.nonce,
                organization_id=UUID(str(a_project["organization_id"])),
                project_id=UUID(context.project),
                reviewer_id=UUID(capture["id"]),
                reviewer_email=capture["email"],
                mcp_account_id=UUID(capture["id"]),
                target_project_id=UUID(bp),
                target_organization_id=UUID(bo),
                target_user_id=UUID(actor["id"]),
                target_email=actor["email"],
                fixture_environment_id=UUID(context.environment),
                fixture_service_id=UUID(context.service),
                target_environment_id=UUID(env["id"]),
                target_service_id=UUID(service["id"]),
                target_viewer_id=UUID(viewer["id"]),
                target_viewer_email=viewer["email"],
            )
            target_reader = PublicAPI(
                "http://native-b.example",
                viewer_token,
                bo,
                transport=httpx.ASGITransport(app=target_app),
            )
            try:
                pack = await prepare_pack(
                    context.api, target_reader, installed, bound, "s5-b-files", tmp_path / "pack"
                )

                async def forward(request):
                    reply = await b_client.send(
                        httpx.Request(
                            request.method,
                            request.url,
                            content=request.content,
                            headers=dict(request.headers),
                        )
                    )
                    return httpx.Response(
                        reply.status_code, content=reply.content, headers=reply.headers
                    )

                with respx.mock as routes:
                    routes.route(host="native-b.example").mock(side_effect=forward)
                    result = await execute_native_api_pack(
                        context.api,
                        context.reader,
                        context.observer,
                        capture_reader=capture_reader,
                        target_reader=target_reader,
                        installation=installed,
                        batch_key="s5-b-files",
                        nonce="s5-b-files-nonce-001",
                        fixture_digest="a" * 64,
                        builds=Builds(
                            runner="unit", target="unit", fixture="a" * 64, verifier="unit"
                        ),
                        output_dir=tmp_path / "run",
                        binding=bound,
                        pack=pack,
                    )
                assert result.report.exit_code == 2
                assert [f.code for r in result.report.scenarios for f in r.findings] == [
                    "OWNED_ASSET_DISPOSAL_PENDING"
                ], result.report.model_dump(mode="json")
                observation = result.evidence.scenarios[0]
                actual = observation.created_file
                assert actual is not None
                assert actual.project_id == UUID(bp) and actual.created_by_id == UUID(actor["id"])
                assert len(actual.observed_artifact_ids) == 1
                assert base64.b64decode(actual.content_base64) == b"flowtest-download"
                assert observation.execution.status == "passed"
                damaged = actual.model_copy(
                    update={"observed_artifact_ids": (*actual.observed_artifact_ids, UUID(int=1))}
                )
                evidence = result.evidence.model_copy(
                    update={
                        "scenarios": (observation.model_copy(update={"created_file": damaged}),)
                    }
                )
                report = verify_batch(result.manifest, evidence)
                assert "S5_PRODUCT_FILE_CONTENT_OR_SOURCE_CHANGED" in [
                    f.code for r in report.scenarios for f in r.findings
                ]
            finally:
                await target_reader.close()
    finally:
        await capture_reader.close()
