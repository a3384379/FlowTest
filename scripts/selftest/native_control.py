"""Real native 4.0 MCP proposal, independent fixture review and ordinary pinned Run."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
from scripts.selftest.cleanup import PlanStopper
from scripts.selftest.collect_evidence import normalize_execution, wait_plan
from scripts.selftest.contract_delta_budget import DeltaAPI, DeltaBudget
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    object_value,
    objects_value,
    text_value,
    write_json,
)
from scripts.selftest.mcp_protocol_runner import ProtocolClient
from scripts.selftest.native_control_contracts import (
    NativeControlEvidence,
    NativeControlFreeze,
    NativeControlManifest,
    NativeControlPack,
    NativeExportObservation,
    NativePublishedCase,
)
from scripts.selftest.start_plan import launch_plan, prepare_plan


class NativeControlProtocol(ProtocolClient):
    def __init__(self, discovered: ProtocolClient, budget: DeltaBudget) -> None:
        if discovered.receipts or not discovered.catalog_digest:
            raise HarnessError("NATIVE_CONTROL_PROTOCOL_MUST_BE_FRESH")
        super().__init__(
            discovered.session, discovered.transport, discovered.batch_key, discovered.output_dir
        )
        self.tools, self.tool_schemas = discovered.tools, discovered.tool_schemas
        self.catalog_digest, self.budget = discovered.catalog_digest, budget

    async def call(
        self, tool_name: str, arguments: JsonObject, *, scenario_id: str, phase: str
    ) -> JsonObject:
        if tool_name != "flowtest.propose_control_workflow":
            raise HarnessError("NATIVE_CONTROL_TOOL_NOT_ALLOWED")
        self.budget.admit(4, tool=True)
        return await super().call(tool_name, arguments, scenario_id=scenario_id, phase=phase)


async def inventory(api: PublicAPI, project: str, resource: str) -> tuple[UUID, ...]:
    if resource not in {"workflows", "workflow-executions"}:
        raise HarnessError("NATIVE_CONTROL_INVENTORY_ROUTE_INVALID")
    page = await api.object("GET", f"/projects/{project}/{resource}?page=1&page_size=100")
    rows = objects_value(page["items"])
    if page["total"] != len(rows) or len(rows) >= 100:
        raise HarnessError("NATIVE_CONTROL_INVENTORY_INCOMPLETE")
    ids = tuple(UUID(text_value(item["id"])) for item in rows)
    if len(ids) != len(set(ids)):
        raise HarnessError("NATIVE_CONTROL_INVENTORY_DUPLICATE")
    return ids


async def _definition(
    api: PublicAPI, project: str, workflow: str, version: int | None
) -> JsonObject:
    root = f"/projects/{project}/workflows/{workflow}"
    if version is None:
        return object_value((await api.object("GET", root))["draft_definition"])
    values = objects_value(await api.request("GET", root + "/versions"))
    selected = [item for item in values if item["version"] == version]
    if len(values) != 1 or len(selected) != 1:
        raise HarnessError("NATIVE_CONTROL_PUBLISHED_VERSION_CHANGED")
    return object_value(selected[0]["definition"])


async def export_refusal(
    api: DeltaAPI,
    viewer: PublicAPI,
    frozen: NativeControlManifest,
    workflow: str,
    version: int | None,
) -> NativeExportObservation:
    project = str(frozen.project_id)
    before = await inventory(viewer, project, "workflow-executions")
    definition = await _definition(viewer, project, workflow, version)
    path = f"/projects/{project}/flow-specs/workflows/{workflow}/export"
    if version is not None:
        path += f"?version={version}"
    status, payload = await api.response("GET", path, {})
    error = object_value(payload.get("error", {}))
    return NativeExportObservation(
        variant="regions4_draft" if version is None else "regions4_published",
        workflow_id=UUID(workflow),
        version=version,
        path=path,
        status=status,
        error_code=text_value(error.get("code")),
        trace_present=isinstance(error.get("trace_id", payload.get("trace_id")), str),
        before_definition_digest=canonical_digest(definition),
        after_definition_digest=canonical_digest(
            await _definition(viewer, project, workflow, version)
        ),
        before_execution_ids=before,
        after_execution_ids=await inventory(viewer, project, "workflow-executions"),
    )


class NativeControlJourney:
    def __init__(
        self,
        frozen: NativeControlManifest,
        pack: NativeControlPack,
        client: ProtocolClient,
        writer: PublicAPI,
        reader: PublicAPI,
        viewer: PublicAPI,
        directory: Path,
        *,
        budget: DeltaBudget | None = None,
    ) -> None:
        self.frozen, self.pack, self.directory = frozen, pack, directory
        self.budget = budget or DeltaBudget(directory, frozen.expires_at)
        if self.budget.deadline != frozen.expires_at:
            raise HarnessError("NATIVE_CONTROL_DEADLINE_CHANGED")
        self.client = NativeControlProtocol(client, self.budget)
        self.writer, self.reader, self.viewer = (
            DeltaAPI(api, self.budget) for api in (writer, reader, viewer)
        )
        self.stop_writer, self.stop_reader = (
            DeltaAPI(writer, self.budget, cleanup=True),
            DeltaAPI(reader, self.budget, cleanup=True),
        )
        self.stopper = PlanStopper(frozen.project_id)
        self.evidence = NativeControlEvidence(
            manifest_digest=canonical_digest(frozen.model_dump(mode="json")),
            collected_at=datetime.now(UTC),
        )

    def checkpoint(self, changes: JsonObject | None = None) -> None:
        payload = {
            **self.evidence.model_dump(mode="json"),
            **(changes or {}),
            "calls": [call.model_dump(mode="json") for call in self.client.receipts],
            "collected_at": datetime.now(UTC).isoformat(),
            "admitted_request_upper_bound": self.budget.requests,
            "admitted_tool_calls": self.budget.tools,
            "rejected_requests": self.budget.rejected_requests,
            "rejected_tool_calls": self.budget.rejected_tools,
        }
        self.evidence = NativeControlEvidence.model_validate(payload)
        write_json(self.directory / "evidence.json", self.evidence)

    async def propose(
        self,
    ) -> tuple[JsonObject, JsonObject, JsonObject, JsonObject, tuple[UUID, ...]]:
        project = str(self.frozen.project_id)
        before = await inventory(self.viewer, project, "workflows")
        if before or await inventory(self.viewer, project, "workflow-executions"):
            raise HarnessError("NATIVE_CONTROL_REQUIRES_FRESH_SYNTHETIC_PROJECT")
        request: JsonObject = {
            "request": {
                "project_id": project,
                "name": self.frozen.batch_key,
                "description": "隔离自测; 独立审核模式 ci_fixture; 不代表模型或真人验收",
                "definition": self.pack.definition,
            },
            "idempotency_key": self.frozen.batch_key + ":proposal",
        }
        proposal = await self.client.call(
            "flowtest.propose_control_workflow",
            request,
            scenario_id="ST-MCP-023",
            phase="native:proposal",
        )
        replay = await self.client.call(
            "flowtest.propose_control_workflow",
            request,
            scenario_id="ST-MCP-023",
            phase="native:replay",
        )
        pending = object_value(
            (await self.viewer.object("GET", f"/mcp/write/change-sets/{proposal['proposal_id']}"))[
                "data"
            ]
        )
        return request, proposal, replay, pending, before

    async def freeze(self) -> NativeControlFreeze:
        request, proposal, replay, pending, before = await self.propose()
        project = str(self.frozen.project_id)
        pending_workflows = await inventory(self.viewer, project, "workflows")
        pending_executions = await inventory(self.viewer, project, "workflow-executions")
        write_json(
            self.directory / "proposal-before-review.json",
            {"request": request, "proposal": proposal, "replay": replay, "pending": pending},
        )
        from scripts.selftest.native_control_verify import check_pending

        if check_pending(self.frozen, self.pack, request, proposal, replay, pending):
            raise HarnessError("NATIVE_CONTROL_PROPOSAL_REVIEW_MISMATCH")
        base = (
            f"/mcp/write/change-sets/{proposal['proposal_id']}/items/{proposal['item_id']}/accept"
        )
        accepted = object_value(
            (
                await self.writer.object(
                    "POST", base, {"note": "ci_fixture 独立审核; 仅物化草稿, 不自动发布或执行"}
                )
            )["data"]
        )
        items = objects_value(accepted["items"])
        if len(items) != 1:
            raise HarnessError("NATIVE_CONTROL_ACCEPT_ITEM_SET_CHANGED")
        workflow = text_value(items[0]["materialized_resource_id"])
        root = f"/projects/{project}/workflows/{workflow}"
        draft = await self.viewer.object("GET", root)
        refused = await export_refusal(self.writer, self.viewer, self.frozen, workflow, None)
        self.checkpoint({"exports": [refused.model_dump(mode="json")]})
        published = await self.writer.object(
            "POST", root + "/versions", {"change_note": "ci_fixture 显式发布原生4.0固定版本"}
        )
        second = await export_refusal(self.writer, self.viewer, self.frozen, workflow, 1)
        self.checkpoint(
            {"exports": [refused.model_dump(mode="json"), second.model_dump(mode="json")]}
        )
        case = await self.writer.object(
            "POST",
            f"/projects/{project}/test-cases",
            {
                "name": self.frozen.batch_key,
                "definition": {
                    "workflow_id": workflow,
                    "workflow_version": 1,
                    "environment_id": str(self.frozen.environment_id),
                    "runtime_variables": {},
                    "runtime_headers": {},
                },
            },
        )
        version = await self.writer.object(
            "POST",
            f"/projects/{project}/test-cases/{case['id']}/versions",
            {"change_note": "固定公开API Case版本"},
        )
        asset = NativePublishedCase(case=case, version=version)
        selection = await prepare_plan(
            self.writer,
            project_id=project,
            cases=(asset,),
            batch_key=self.frozen.batch_key,
            output_dir=self.directory,
        )
        suites = objects_value(
            await self.viewer.request(
                "GET", f"/projects/{project}/test-suites/{selection.suite_id}/versions"
            )
        )
        if len(suites) != 1:
            raise HarnessError("NATIVE_CONTROL_SUITE_VERSION_SET_CHANGED")
        plan = await self.viewer.object(
            "GET", f"/projects/{project}/test-plans/{selection.plan_id}"
        )
        if "webhook_secret" in plan:
            raise HarnessError("NATIVE_CONTROL_PUBLIC_PLAN_CONTRACT_CHANGED")
        result = NativeControlFreeze(
            request=request,
            proposal=proposal,
            replay=replay,
            pending=pending,
            accepted=accepted,
            draft=draft,
            published=published,
            case=asset,
            suite=suites[0],
            plan=plan,
            selection=selection,
            before_workflow_ids=before,
            pending_workflow_ids=pending_workflows,
            pending_execution_ids=pending_executions,
            before_execution_ids=await inventory(self.viewer, project, "workflow-executions"),
            frozen_at=datetime.now(UTC),
        )
        write_json(self.directory / "frozen-before-run.json", result)
        self.checkpoint({"frozen": result.model_dump(mode="json")})
        return result

    async def execute(self, frozen: NativeControlFreeze) -> None:
        self.stopper.arm(
            frozen.selection.plan_id, tuple(item.case_id for item in frozen.selection.cases)
        )
        write_json(self.directory / "plan-launch-intent.json", self.stopper.receipt)
        started = await launch_plan(
            self.writer, selection=frozen.selection, batch_key=self.frozen.batch_key
        )
        self.stopper.started(started.run_id)
        write_json(self.directory / "plan-launch-receipt.json", self.stopper.receipt)
        raw = await wait_plan(
            self.reader, str(self.frozen.project_id), str(started.run_id), self.frozen.expires_at
        )
        self.stopper.observe(raw)
        self.checkpoint({"plan_run": raw})
        items = objects_value(raw["items"])
        if len(items) != 1:
            raise HarnessError("NATIVE_CONTROL_PLAN_ITEM_SET_CHANGED")
        execution_id = text_value(items[0]["execution_id"])
        root = f"/ci/projects/{self.frozen.project_id}/workflow-executions/{execution_id}/evidence"
        evidence = await self.reader.object("GET", root)
        control = await self.reader.object(
            "GET", root + "/control-records?node_id=parallel&kind=branch&page=1&page_size=100"
        )
        details = [
            await self.viewer.object(
                "GET",
                f"/projects/{self.frozen.project_id}/workflow-executions/{execution_id}/control-records/branch/{branch.ordinal}?node_id=parallel",
            )
            for branch in self.pack.branches
        ]
        self.checkpoint(
            {
                "execution": normalize_execution(evidence).model_dump(mode="json"),
                "raw_execution": evidence,
                "control_page": control,
                "control_details": [detail for detail in details],
            }
        )

    async def run(self) -> NativeControlEvidence:
        if (self.directory / "manifest.json").exists():
            raise HarnessError("NATIVE_CONTROL_OUTPUT_EXISTS_NO_REPLAY")
        write_json(self.directory / "manifest.json", self.frozen)
        try:
            frozen = await self.freeze()
            from scripts.selftest.native_control_verify import check_freeze

            if check_freeze(self.frozen, self.pack, frozen):
                raise HarnessError("NATIVE_CONTROL_FROZEN_SOURCE_MISMATCH")
            await self.execute(frozen)
        except BaseException as error:
            self.checkpoint({"failure_code": ";".join(failure_codes(error))[:200]})
            raise
        finally:
            try:
                receipt = await self.stopper.stop(
                    self.stop_writer,
                    self.stop_reader,
                    deadline=datetime.now(UTC) + timedelta(seconds=10),
                )
                write_json(self.directory / "cleanup.json", receipt)
                self.checkpoint({"cleanup": receipt.model_dump(mode="json")})
            except (HarnessError, httpx.HTTPError):
                self.checkpoint({"failure_code": "NATIVE_CONTROL_CLEANUP_UNKNOWN"})
        return self.evidence
