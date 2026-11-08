"""Read back actual MCP-created proposals; model output is never source authority."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import Field, model_validator
from scripts.selftest.contracts import ApiSource, Contract, OracleBinding, Sha256, canonical_digest
from scripts.selftest.host_contracts import (
    HostGeneratedDesign,
    HostModelSummary,
    ReviewedWorkflowBinding,
)
from scripts.selftest.host_gateway import BoundedGateway, ToolExchange, business_success
from scripts.selftest.host_integration_sources import HostIntegrationSource, integration_source
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    object_value,
    objects_value,
    text_value,
)

from app.domain.test_design import TestDesignDocument, fingerprint_design
from app.domain.test_design_compilation import CompileTestDesignResponse
from app.engine.contracts import WorkflowDefinition
from app.schemas.flow_spec import FlowSpecChangeSetDetailResponse, FlowSpecVisualProposalResponse
from app.schemas.test_assets import PublishedTestCaseDefinition


class FrozenHostSource(Contract):
    proposal_id: UUID
    proposal_fingerprint: Sha256
    project_id: UUID
    scenario_id: str = Field(min_length=1, max_length=120)
    api_source: ApiSource
    design_fingerprint: Sha256
    compilation_fingerprint: Sha256
    oracle_bindings: tuple[OracleBinding, ...] = Field(min_length=1, max_length=500)
    native_definition: WorkflowDefinition
    environment_id: UUID
    api_sources: tuple[ApiSource, ...] = Field(min_length=1, max_length=100)
    combined_design: TestDesignDocument
    generated_design: HostGeneratedDesign | None = None
    compilation: CompileTestDesignResponse | None = None
    integration: HostIntegrationSource | None = None
    source_snapshot_digest: Sha256
    frozen_at: datetime

    @model_validator(mode="after")
    def source_kind(self) -> FrozenHostSource:
        single = self.generated_design is not None and self.compilation is not None
        if single == (self.integration is not None):
            raise ValueError("one exact compilation source is required")
        if self.api_source != self.api_sources[0]:
            raise ValueError("primary source must belong to exact ordered source set")
        if fingerprint_design(self.combined_design) != self.design_fingerprint:
            raise ValueError("combined design fingerprint changed")
        return self


class FrozenHostCase(Contract):
    proposal_id: UUID
    item_id: UUID
    proposal_fingerprint: Sha256
    workflow_id: UUID
    workflow_version: int = Field(ge=1, strict=True)
    environment_id: UUID
    definition_digest: Sha256
    source_snapshot_digest: Sha256
    definition: PublishedTestCaseDefinition


def data(exchange: ToolExchange) -> JsonObject:
    structured = object_value(exchange.result.structured_content)
    return object_value(structured.get("data", structured))


def proposal_exchanges(
    gateway: BoundedGateway, summary: HostModelSummary
) -> tuple[ToolExchange, ...]:
    names = (
        {"flowtest.propose_flow_draft", "flowtest.propose_simple_flow"}
        if summary.phase == "workflow"
        else {"flowtest.propose_test_design"}
    )
    values = tuple(
        item for item in gateway.exchanges if item.name in names and business_success(item.result)
    )
    identifiers = tuple(
        UUID(text_value(data(item).get("change_set_id" if summary.phase == "workflow" else "id")))
        for item in values
    )
    if (
        summary.status != "waiting_for_review"
        or not identifiers
        or len(set(identifiers)) != len(identifiers)
        or set(identifiers) != set(summary.proposal_ids)
    ):
        raise HarnessError("HOST_MODEL_PROPOSAL_RECEIPT_MISMATCH")
    return values


def _normalized(value: WorkflowDefinition | JsonObject) -> JsonObject:
    return object_value(
        WorkflowDefinition.model_validate(value).model_dump(mode="json", exclude_none=True)
    )


def _compiled_sources(
    gateway: BoundedGateway, expected: WorkflowDefinition
) -> tuple[HostGeneratedDesign, CompileTestDesignResponse, str, tuple[OracleBinding, ...]]:
    candidates = []
    for exchange in gateway.exchanges:
        if exchange.name != "flowtest.compile_test_design" or not business_success(exchange.result):
            continue
        compiled = CompileTestDesignResponse.model_validate(data(exchange))
        for scenario in compiled.scenarios:
            if scenario.executable_payload and _normalized(
                scenario.executable_payload.native_definition
            ) == _normalized(expected):
                candidates.append((compiled, scenario))
    if len(candidates) != 1:
        raise HarnessError("HOST_COMPILED_WORKFLOW_SOURCE_AMBIGUOUS")
    compiled, scenario = candidates[0]
    designs = tuple(
        HostGeneratedDesign.model_validate(data(exchange))
        for exchange in gateway.exchanges
        if exchange.name == "flowtest.generate_test_design"
        and business_success(exchange.result)
        and data(exchange).get("fingerprint") == compiled.design_fingerprint
    )
    if not designs or any(item != designs[0] for item in designs):
        raise HarnessError("HOST_GENERATED_DESIGN_SOURCE_MISSING")
    source, design = compiled.resolved_sources, designs[0]
    if design.origin is None or (
        source.api_definition_id != design.origin.api_definition_id
        or source.api_version != design.origin.api_version
        or source.contract_fingerprint != design.origin.contract_fingerprint
    ):
        raise HarnessError("HOST_DESIGN_ORIGIN_CHANGED")
    bindings = tuple(
        OracleBinding(
            oracle_id=item.oracle_id,
            node_id=item.node_id,
            expression=item.normalized_expression,
            expected_value_digest=item.expected_value_fingerprint,
            assertion_name="workflow_assertion",
        )
        for item in scenario.oracle_bindings
    )
    if not bindings or compiled.readiness != "ready":
        raise HarnessError("HOST_COMPILED_ORACLES_MISSING")
    return design, compiled, scenario.scenario_id, bindings


def _source_fields(
    gateway: BoundedGateway, visual: FlowSpecVisualProposalResponse
) -> dict[str, object]:
    if visual.integration_plan is not None:
        integration, oracles = integration_source(gateway, visual)
        sources = tuple(item.api_source for item in integration.operations)
        reference = integration.plan.target_environment.source_ref
        if not reference.startswith("environment://"):
            raise HarnessError("HOST_INTEGRATION_ENVIRONMENT_REQUIRED")
        environment = UUID(reference.removeprefix("environment://"))
        if environment not in gateway.authorization.environment_ids:
            raise HarnessError("HOST_INTEGRATION_ENVIRONMENT_NOT_AUTHORIZED")
        return {
            "scenario_id": "integration_lifecycle",
            "api_source": sources[0],
            "api_sources": sources,
            "environment_id": environment,
            "combined_design": integration.combined_design,
            "design_fingerprint": integration.combined_design_fingerprint,
            "compilation_fingerprint": integration.compilation.flow_spec_fingerprint,
            "oracle_bindings": oracles,
            "integration": integration,
        }
    design, compilation, scenario, oracles = _compiled_sources(gateway, visual.proposed_definition)
    source = compilation.resolved_sources
    api = ApiSource(
        project_id=gateway.authorization.project_id,
        api_definition_id=source.api_definition_id,
        api_version=source.api_version,
        contract_fingerprint=source.contract_fingerprint,
    )
    return {
        "scenario_id": scenario,
        "api_source": api,
        "api_sources": (api,),
        "environment_id": source.environment_id,
        "combined_design": design.design,
        "design_fingerprint": compilation.design_fingerprint,
        "compilation_fingerprint": compilation.compilation_fingerprint,
        "oracle_bindings": oracles,
        "generated_design": design,
        "compilation": compilation,
    }


async def freeze_workflows(
    api: PublicAPI,
    gateway: BoundedGateway,
    summary: HostModelSummary,
) -> tuple[FrozenHostSource, ...]:
    values = []
    for exchange in proposal_exchanges(gateway, summary):
        result = data(exchange)
        if result.get("dry_run") is not False or result.get("status") != "draft":
            raise HarnessError("HOST_REAL_DRAFT_PROPOSAL_REQUIRED")
        identifier = UUID(text_value(result.get("change_set_id")))
        project = gateway.authorization.project_id
        visual = FlowSpecVisualProposalResponse.model_validate(
            await api.object(
                "GET", f"/projects/{project}/flow-specs/change-sets/{identifier}/visual-proposal"
            )
        )
        proposal = visual.proposal
        if (
            proposal.project_id != project
            or proposal.review_status != "pending"
            or proposal.applied_at is not None
            or proposal.target_workflow_id is not None
            or proposal.proposal_origin != "mcp"
        ):
            raise HarnessError("HOST_PROPOSAL_NOT_FRESH_PENDING")
        if proposal.source_fingerprint != result.get("flow_spec_fingerprint"):
            raise HarnessError("HOST_PROPOSAL_FINGERPRINT_CHANGED")
        source_fields = _source_fields(gateway, visual)
        values.append(
            FrozenHostSource.model_validate(
                {
                    "proposal_id": identifier,
                    "proposal_fingerprint": proposal.source_fingerprint,
                    "project_id": project,
                    **source_fields,
                    "native_definition": visual.proposed_definition,
                    "source_snapshot_digest": canonical_digest(
                        proposal.model_dump(
                            mode="json",
                            exclude={
                                "review_status",
                                "reviewed_at",
                                "reviewed_by_id",
                                "applied_at",
                                "updated_at",
                                "materialized_workflow_id",
                                "status",
                            },
                        )
                    ),
                    "frozen_at": datetime.now(UTC),
                }
            )
        )
    return tuple(values)


async def reviewed_workflows(
    api: PublicAPI,
    sources: tuple[FrozenHostSource, ...],
    *,
    reviewer_ids: tuple[UUID, ...],
) -> tuple[ReviewedWorkflowBinding, ...]:
    values = []
    for source in sources:
        base = f"/projects/{source.project_id}"
        proposal = await api.object("GET", base + f"/flow-specs/change-sets/{source.proposal_id}")
        frozen = FlowSpecChangeSetDetailResponse.model_validate(proposal)
        immutable = frozen.model_dump(
            mode="json",
            exclude={
                "review_status",
                "reviewed_at",
                "reviewed_by_id",
                "applied_at",
                "updated_at",
                "materialized_workflow_id",
                "status",
            },
        )
        if canonical_digest(immutable) != source.source_snapshot_digest:
            raise HarnessError("HOST_REVIEW_IMMUTABLE_SOURCE_CHANGED")
        if proposal.get("source_fingerprint") != source.proposal_fingerprint:
            raise HarnessError("HOST_REVIEW_SOURCE_CHANGED")
        if proposal.get("review_status") == "rejected":
            raise HarnessError("HOST_HUMAN_REVIEW_REJECTED")
        identifier = proposal.get("materialized_workflow_id")
        if (
            proposal.get("review_status") != "accepted"
            or not proposal.get("reviewed_by_id")
            or not proposal.get("applied_at")
            or not identifier
        ):
            raise HarnessError("HOST_WAITING_FOR_HUMAN_REVIEW")
        if proposal.get("reviewed_by_id") not in {str(value) for value in reviewer_ids}:
            raise HarnessError("HOST_REVIEWER_NOT_AUTHORIZED")
        workflow = await api.object("GET", base + f"/workflows/{identifier}")
        versions = objects_value(
            await api.request("GET", base + f"/workflows/{identifier}/versions")
        )
        selected = [
            item for item in versions if item.get("version") == workflow.get("current_version")
        ]
        if len(selected) != 1:
            raise HarnessError("HOST_WAITING_FOR_HUMAN_PUBLICATION")
        if _normalized(object_value(selected[0]["definition"])) != _normalized(
            source.native_definition
        ):
            raise HarnessError("HOST_PUBLISHED_WORKFLOW_DEFINITION_CHANGED")
        values.append(
            ReviewedWorkflowBinding.model_validate(
                {
                    "workflow_id": identifier,
                    "version": selected[0]["version"],
                    "fingerprint": selected[0]["fingerprint"],
                }
            )
        )
    return tuple(values)


async def freeze_cases(
    api: PublicAPI,
    gateway: BoundedGateway,
    summary: HostModelSummary,
    *,
    sources: tuple[FrozenHostSource, ...],
) -> tuple[FrozenHostCase, ...]:
    if len(sources) != len(gateway.reviewed_workflows):
        raise HarnessError("HOST_CASE_DESIGN_BINDINGS_MISSING")
    designs = {
        binding.workflow_id: source.design_fingerprint
        for source, binding in zip(sources, gateway.reviewed_workflows, strict=True)
    }
    values = []
    for exchange in proposal_exchanges(gateway, summary):
        result = data(exchange)
        identifier = UUID(text_value(result.get("id")))
        detail = object_value(
            (await api.object("GET", f"/mcp/write/change-sets/{identifier}"))["data"]
        )
        if (
            detail.get("project_id") != str(gateway.authorization.project_id)
            or detail.get("source_fingerprint") != result.get("source_fingerprint")
            or detail.get("applied_at")
        ):
            raise HarnessError("HOST_CASE_PROPOSAL_SOURCE_CHANGED")
        proposed = objects_value(exchange.arguments.get("test_cases"))
        design = fingerprint_design(
            TestDesignDocument.model_validate(exchange.arguments.get("design"))
        )
        items = [
            item for item in objects_value(detail["items"]) if item.get("item_type") == "test_case"
        ]
        if not items or len(items) != len(proposed):
            raise HarnessError("HOST_CASE_PROPOSAL_ITEMS_CHANGED")
        for item, argument in zip(items, proposed, strict=True):
            definition = PublishedTestCaseDefinition.model_validate(
                object_value(item["proposed_content"])["definition"]
            )
            expected = PublishedTestCaseDefinition.model_validate(argument["definition"])
            if designs.get(definition.workflow_id) != design:
                raise HarnessError("HOST_CASE_GENERATED_DESIGN_CHANGED")
            if (
                item.get("review_status") != "pending"
                or item.get("materialized_resource_id")
                or definition != expected
                or definition.runtime_headers
                or definition.runtime_variables
            ):
                raise HarnessError("HOST_CASE_PROPOSAL_NOT_FRESH_PENDING")
            values.append(
                FrozenHostCase(
                    proposal_id=identifier,
                    item_id=UUID(text_value(item["id"])),
                    proposal_fingerprint=text_value(detail["source_fingerprint"]),
                    workflow_id=definition.workflow_id,
                    workflow_version=definition.workflow_version,
                    environment_id=definition.environment_id,
                    definition=definition,
                    definition_digest=canonical_digest(
                        definition.model_dump(mode="json", exclude_none=True)
                    ),
                    source_snapshot_digest=canonical_digest(
                        {
                            "id": item["id"],
                            "item_type": item["item_type"],
                            "action": item["action"],
                            "proposed_content": item["proposed_content"],
                        }
                    ),
                )
            )
    expected_set = {(item.workflow_id, item.version) for item in gateway.reviewed_workflows}
    actual = [(item.workflow_id, item.workflow_version) for item in values]
    if len(actual) != len(set(actual)) or set(actual) != expected_set:
        raise HarnessError("HOST_CASE_PUBLISHED_WORKFLOW_SET_CHANGED")
    return tuple(values)
