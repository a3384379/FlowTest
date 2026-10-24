"""Actual SDK tool adapters and public ASGI review readback; not a real Host run."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import jwt
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import canonical_digest  # noqa: E402
from scripts.selftest.host_contracts import HostBudget, HostModelSummary  # noqa: E402
from scripts.selftest.host_gateway import BoundedGateway  # noqa: E402
from scripts.selftest.host_launch import VerifiedGrant  # noqa: E402
from scripts.selftest.host_materialized import _case  # noqa: E402
from scripts.selftest.host_sources import (  # noqa: E402
    freeze_cases,
    freeze_workflows,
    reviewed_workflows,
)
from scripts.selftest.io import HarnessError, PublicAPI, object_value  # noqa: E402
from test_design_compilation import _issue, _prepare_api  # noqa: E402
from test_mcp_read import mcp_context as mcp_context  # noqa: E402
from test_selftest_host_adapter import authorization  # noqa: E402

from app.main import app  # noqa: E402
from app.mcp.client import MCPReadGatewayClient  # noqa: E402
from app.mcp.server import create_mcp_server  # noqa: E402


def unwrap(result):
    assert not result.is_error
    value = object_value(result.structured_content)
    assert "error" not in value
    return object_value(value.get("data", value))


@pytest.mark.asyncio
async def test_real_sdk_asgi_pending_review_publication_case_and_readonly_role_mapping(
    mcp_context, tmp_path
):
    context = mcp_context
    await _prepare_api(context)
    token = await _issue(
        context, ["mcp:read", "mcp:flow:propose", "mcp:evidence:write", "mcp:write"]
    )
    actor = UUID(jwt.decode(context["human_token"], options={"verify_signature": False})["sub"])
    names = (
        "flowtest.generate_test_design",
        "flowtest.begin_test_context",
        "flowtest.compile_test_design",
        "flowtest.propose_flow_draft",
        "flowtest.propose_test_design",
    )
    auth = authorization(
        project_id=context["project_id"],
        environment_ids=(context["environment_id"],),
        allowed_tools=names,
        reviewer_ids=(actor,),
        review_mode="ci_fixture",
        budget=HostBudget(
            maximum_tool_calls=10,
            wall_seconds=60,
            maximum_prompt_bytes=1024,
            maximum_result_bytes=1048576,
            maximum_total_result_bytes=8388608,
        ),
    )
    grant = VerifiedGrant(auth, canonical_digest(auth.model_dump(mode="json")))
    api = PublicAPI(
        "http://test",
        context["human_token"],
        str(context["organization_id"]),
        transport=httpx.ASGITransport(app=app),
    )
    async with MCPReadGatewayClient(
        base_url="http://test", token=token, transport=httpx.ASGITransport(app=app)
    ) as client:
        server = create_mcp_server(client=client)

        class SDKUpstream:
            async def call_tool(self, name, arguments):
                return await server.call_tool(name, arguments)

        gateway = BoundedGateway(
            authorization=auth,
            attempt_id=uuid4(),
            phase="workflow",
            catalog=tuple(await server.list_tools()),
            upstream=SDKUpstream(),
            directory=tmp_path,
            deadline=datetime.now(UTC) + timedelta(seconds=60),
        )
        project = str(context["project_id"])
        generated = unwrap(
            await gateway.call(
                "flowtest.generate_test_design",
                {
                    "project_id": project,
                    "api_definition_id": str(context["definition_id"]),
                    "api_version": 1,
                },
            )
        )
        begun = unwrap(
            await gateway.call(
                "flowtest.begin_test_context",
                {
                    "project_id": project,
                    "name": auth.batch_key,
                    "objective": "合成Host adapter API表征",
                    "target_environment_id": str(context["environment_id"]),
                    "required_evidence": ["contract"],
                    "contract_revisions": [
                        {
                            "source_ref": f"api-definition://{context['definition_id']}/version/1",
                            "revision": generated["origin"]["contract_fingerprint"],
                        }
                    ],
                },
            )
        )
        binding = {
            "context_id": begun["id"],
            "context_revision_id": begun["revision"]["id"],
            "context_fingerprint": begun["revision"]["fingerprint"],
        }
        scenario = next(
            item for item in generated["design"]["scenarios"] if item["kind"] == "happy_path"
        )
        compiled = unwrap(
            await gateway.call(
                "flowtest.compile_test_design",
                {
                    "request": {
                        "project_id": project,
                        "environment_id": str(context["environment_id"]),
                        "design": generated["design"],
                        "design_fingerprint": generated["fingerprint"],
                        "origin": generated["origin"],
                        "scenario_ids": [scenario["id"]],
                        "context_binding": binding,
                    }
                },
            )
        )
        assert compiled["readiness"] == "ready"
        executable = compiled["scenarios"][0]["executable_payload"]
        proposed = unwrap(
            await gateway.call(
                "flowtest.propose_flow_draft",
                {
                    "project_id": project,
                    "context_id": binding["context_id"],
                    "context_revision_id": binding["context_revision_id"],
                    "spec": executable["spec"],
                    "operation_mappings": executable["operation_mappings"],
                    "operation_version_mappings": executable["operation_version_mappings"],
                    "source_ref": f"mcp://selftest/{auth.batch_key}/workflow",
                    "idempotency_key": auth.batch_key + ":workflow",
                    "dry_run": False,
                },
            )
        )
        summary = HostModelSummary(
            phase="workflow",
            status="waiting_for_review",
            proposal_ids=(UUID(proposed["change_set_id"]),),
        )
        sources = await freeze_workflows(api, gateway, summary)
        with pytest.raises(HarnessError, match="WAITING_FOR_HUMAN_REVIEW"):
            await reviewed_workflows(api, sources, reviewer_ids=(actor,))
        proposal_path = f"/projects/{project}/flow-specs/change-sets/{sources[0].proposal_id}"
        await api.object(
            "POST", proposal_path + "/review", {"accept": True, "note": "ci_fixture明确模拟审核"}
        )
        applied = await api.object("POST", proposal_path + "/apply")
        await api.object(
            "POST", f"/projects/{project}/workflows/{applied['workflow_id']}/versions", {}
        )
        with pytest.raises(HarnessError, match="REVIEWER_NOT_AUTHORIZED"):
            await reviewed_workflows(api, sources, reviewer_ids=(uuid4(),))
        workflows = await reviewed_workflows(api, sources, reviewer_ids=(actor,))
        gateway.begin_case_phase(workflows)
        definition = {
            "workflow_id": str(workflows[0].workflow_id),
            "workflow_version": workflows[0].version,
            "environment_id": str(context["environment_id"]),
        }
        case = unwrap(
            await gateway.call(
                "flowtest.propose_test_design",
                {
                    "project_id": project,
                    "title": auth.batch_key + " case",
                    "confidence": 1.0,
                    "risk_level": "high",
                    "design": generated["design"],
                    "test_cases": [{"name": auth.batch_key + " case", "definition": definition}],
                    "source_ref": f"mcp://selftest/{auth.batch_key}/case",
                    "idempotency_key": auth.batch_key + ":case",
                    "dry_run": False,
                },
            )
        )
        cases = await freeze_cases(
            api,
            gateway,
            HostModelSummary(
                phase="case", status="waiting_for_review", proposal_ids=(UUID(case["id"]),)
            ),
            sources=sources,
        )
        path = f"/mcp/write/change-sets/{case['id']}"
        approval = object_value(
            (await api.object("POST", path + "/approve", {"note": "ci_fixture"}))["data"]
        )["approval"]["id"]
        for item in case["items"]:
            await api.object(
                "POST",
                path + f"/items/{item['id']}/accept",
                {"approval_id": approval, "note": "ci_fixture"},
            )
        accepted = await api.object("GET", path)
        item = next(
            value for value in accepted["data"]["items"] if value["item_type"] == "test_case"
        )
        await api.object(
            "POST",
            f"/projects/{project}/test-cases/{item['materialized_resource_id']}/versions",
            {},
        )
        requests = []

        async def readonly(request):
            assert request.method == "GET"
            requests.append(request.url.path)

        api._client.event_hooks["request"].append(readonly)
        actual = await _case(api, context["project_id"], cases[0], grant=grant)
        assert actual.proposal.review_mode == "ci_fixture" and actual.proposal.reviewer_id == actor
        assert actual.case["id"] == item["materialized_resource_id"]
        assert requests[0] == f"/api/v1/mcp/write/change-sets/{case['id']}"
    await api.close()
