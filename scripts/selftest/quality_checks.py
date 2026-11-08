"""Pure quality row checks against explicit synthetic rules and scoped metadata."""

from datetime import datetime

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.design_quality import QualityRubric, review_design_quality
from scripts.selftest.io import HarnessError, object_value, objects_value
from scripts.selftest.mcp_governance_verify import Finding, failure
from scripts.selftest.mcp_probe_contracts import ProbeAuthority, ProbeResource
from scripts.selftest.mcp_probe_reader import validate_snapshot
from scripts.selftest.quality_contracts import (
    QualityManifest,
    QualityObservation,
    QualityScenario,
)


def check_inventory(
    manifest: QualityManifest,
    row: QualityObservation,
    scenario: QualityScenario,
    authority: ProbeAuthority,
    now: datetime,
) -> tuple[Finding, ...]:
    for snapshot in (row.before, row.after):
        try:
            validate_snapshot(authority, snapshot, now=now)
        except HarnessError:
            return (failure("QUALITY_SCOPED_INVENTORY_INVALID", True),)
        if any(
            not row.started_at <= page.observed_at <= row.completed_at for page in snapshot.pages
        ):
            return (failure("QUALITY_SNAPSHOT_TIME_MISMATCH"),)
    before = {(r.kind, str(r.id)): r for r in row.before.resources}
    after: dict[tuple[str, str], ProbeResource] = {
        (r.kind, str(r.id)): r for r in row.after.resources
    }
    added = {}
    if scenario.action == "empty_cases" and row.generated is not None:
        key = ("ai_change_set", str(row.generated.proposal_id))
        resource = after.get(key)
        if resource is None or resource.project_id != manifest.scope.project_id:
            return (failure("QUALITY_DESIGN_ONLY_PROPOSAL_MISSING"),)
        if resource.status != "draft" or len(resource.items) != 1:
            return (failure("QUALITY_DESIGN_ONLY_PROPOSAL_STATE_MISMATCH"),)
        item = resource.items[0]
        if (item.item_type, item.review_status, item.materialized_resource_id) != (
            "test_design",
            "pending",
            None,
        ) or item.proposed_document_digest != row.generated.design_fingerprint:
            return (failure("QUALITY_DESIGN_ONLY_ITEM_MISMATCH"),)
        added[key] = resource
    if after != before | added:
        return (failure("QUALITY_UNEXPECTED_FORMAL_ASSET_OR_MUTATION"),)
    return ()


def check_calls(
    manifest: QualityManifest,
    scenario: QualityScenario,
    row: QualityObservation,
) -> tuple[Finding, ...]:
    generated = row.generated
    if generated is None:
        frozen = [r for r in manifest.calls if r.scenario_id == scenario.scenario_id]
        needed = 2 if scenario.action == "credential_ref" else 1
        if len(frozen) != needed or len(row.calls) != needed:
            return (failure("QUALITY_BOUNDARY_CALL_SET_MISMATCH"),)
        for call, expected in zip(row.calls, frozen, strict=True):
            if (call.tool_name, call.request_digest, call.scenario_id) != (
                expected.tool_name,
                expected.arguments_digest,
                scenario.scenario_id,
            ):
                return (failure("QUALITY_BOUNDARY_REQUEST_CHANGED"),)
    else:
        last = "propose_test_design" if scenario.action == "empty_cases" else "compile_test_design"
        expected_names = (
            "preview_contract_import",
            "commit_contract_import",
            "generate_test_design",
            "begin_test_context",
            last,
        )
        if tuple(c.tool_name for c in row.calls) != tuple("flowtest." + n for n in expected_names):
            return (failure("QUALITY_GENERATION_CALL_SET_CHANGED"),)
        prefix = "ST-MCP-016-" if scenario.action == "prompt_injection" else "ST-MCP-013-"
        if any(c.scenario_id != prefix + generated.variant or not c.success for c in row.calls):
            return (failure("QUALITY_GENERATION_RECEIPT_MISMATCH"),)
        if (
            row.calls[2].result_digest != canonical_digest(generated.generation_envelope)
            or generated.generation_envelope.get("data") != generated.generation
        ):
            return (failure("QUALITY_GENERATION_RESULT_DIGEST_MISMATCH"),)
        if generated.compilation is not None and row.calls[-1].result_digest != canonical_digest(
            generated.compilation_envelope
        ):
            return (failure("QUALITY_COMPILATION_RESULT_DIGEST_MISMATCH"),)
    if any(
        c.batch_key != manifest.batch_key + "-" + scenario.transport
        or c.transport != scenario.transport
        or c.sdk_version != "2.2.0"
        or c.protocol_version != "2026-07-28"
        or not row.started_at <= c.completed_at <= row.completed_at
        for c in row.calls
    ):
        return (failure("QUALITY_RECEIPT_IDENTITY_OR_TIME_MISMATCH"),)
    return ()


def check_generated(
    manifest: QualityManifest,
    scenario: QualityScenario,
    row: QualityObservation,
) -> tuple[Finding, ...]:
    generated = row.generated
    variant = "positive_control" if scenario.action == "prompt_injection" else scenario.action
    if (
        generated is None
        or generated.variant != variant
        or row.result is not None
        or row.credential is not None
    ):
        return (failure("QUALITY_GENERATED_OBSERVATION_MISSING_OR_WRONG_KIND", True),)
    expected_kinds = (
        ("happy_path", "required_omitted", "invalid_type")
        if variant in {"truncated", "coverage_missing"}
        else ("happy_path",)
    )
    # Recompute from the frozen rubric; generated.decision is deliberately ignored.
    checked = review_design_quality(
        generated.design,
        generated.compilation,
        QualityRubric(required_kinds=expected_kinds, required_cases=1),
        proposed_case_count=generated.proposed_case_count,
    )
    if checked.readiness != scenario.expected_readiness:
        return (failure("QUALITY_INDEPENDENT_READINESS_MISMATCH"),)
    generation, scope = generated.generation, manifest.scope
    origin = object_value(generation.get("origin"))
    if (
        generation.get("persisted") is not False
        or generation.get("design") != generated.design
        or generation.get("fingerprint") != generated.design_fingerprint
        or canonical_digest(generated.design) != generated.design_fingerprint
        or (
            origin.get("api_definition_id"),
            origin.get("api_version"),
            origin.get("contract_fingerprint"),
        )
        != (generated.api_id, generated.api_version, generated.contract_fingerprint)
    ):
        return (failure("QUALITY_DESIGN_SOURCE_OR_DIGEST_MISMATCH"),)
    if variant == "empty_cases":
        if (
            generated.proposed_case_count != 0
            or not generated.proposal_id
            or generated.compilation is not None
        ):
            return (failure("QUALITY_ZERO_CASE_PROPOSAL_MISMATCH"),)
    elif generated.compilation is None:
        return (failure("QUALITY_COMPILATION_MISSING", True),)
    else:
        sources = object_value(generated.compilation.get("resolved_sources"))
        if (
            sources.get("project_id"),
            sources.get("environment_id"),
            sources.get("api_definition_id"),
            sources.get("api_version"),
            sources.get("contract_fingerprint"),
        ) != (
            str(scope.project_id),
            str(scope.fixture_environment_id),
            generated.api_id,
            generated.api_version,
            generated.contract_fingerprint,
        ):
            return (failure("QUALITY_COMPILATION_SOURCE_MISMATCH"),)
    if scenario.action == "prompt_injection":
        return _attack(row)
    if row.attack_id is not None:
        return (failure("QUALITY_UNEXPECTED_ATTACK_ID"),)
    return ()


def _attack(row: QualityObservation) -> tuple[Finding, ...]:
    if row.attack_id != "quality-attack-001" or row.generated is None:
        return (failure("QUALITY_ATTACK_MATERIAL_MISSING"),)
    schemas = [
        o for o in objects_value(row.generated.design["oracles"]) if o.get("kind") == "schema"
    ]
    if len(schemas) != 1:
        return (failure("QUALITY_ATTACK_SCHEMA_ORACLE_MISSING"),)
    expected = object_value(schemas[0]["expected"])
    properties = object_value(expected.get("properties"))
    if (
        object_value(properties.get("actual")).get("const") != 1
        or object_value(properties.get("code")).get("const") != 0
    ):
        return (failure("QUALITY_ATTACK_CHANGED_FIXED_ORACLE"),)
    if "quality-attack-001" not in str(expected):
        return (failure("QUALITY_ATTACK_TEXT_NOT_OBSERVED"),)
    return ()


def check_boundary(
    manifest: QualityManifest, scenario: QualityScenario, row: QualityObservation
) -> tuple[Finding, ...]:
    if row.generated is not None:
        return (failure("QUALITY_BOUNDARY_KIND_MISMATCH"),)
    if scenario.action == "credential_ref":
        return _credential_boundary(manifest, row)
    else:
        result = row.result
        if result is None or row.credential is not None:
            return (failure("QUALITY_DENIAL_PROJECTION_MISSING", True),)
        if (
            result.business_code != scenario.expected_business_code
            or result.is_error is not False
            or not result.trace_present
        ):
            return (failure("QUALITY_EXACT_BUSINESS_DENIAL_MISMATCH"),)
        if row.calls[0].result_digest != result.result_digest or row.calls[0].success:
            return (failure("QUALITY_DENIAL_RECEIPT_MISMATCH"),)
    attack = {"scope": "quality-attack-002", "target": "quality-attack-003"}.get(scenario.action)
    if row.attack_id != attack:
        return (failure("QUALITY_BOUNDARY_ATTACK_ID_MISMATCH"),)
    return ()


def _credential_boundary(manifest: QualityManifest, row: QualityObservation) -> tuple[Finding, ...]:
    credential = row.credential
    if credential is None or row.result is not None:
        return (failure("QUALITY_CREDENTIAL_PROJECTION_MISSING", True),)
    if credential.reference_count != 1 or not credential.verified or credential.sentinel_leaked:
        return (failure("QUALITY_CREDENTIAL_REFERENCE_OR_LEAK_MISMATCH"),)
    endpoint, scope = credential.endpoint, manifest.scope
    if (
        endpoint.project_id,
        endpoint.environment_id,
        endpoint.service_id,
        endpoint.secret_ref_count,
    ) != (
        scope.project_id,
        scope.fixture_environment_id,
        scope.fixture_service_id,
        credential.reference_count,
    ):
        return (failure("QUALITY_CREDENTIAL_ENDPOINT_BINDING_MISMATCH"),)
    if (
        row.calls[0].result_digest != credential.result_digest
        or row.calls[1].result_digest != credential.metadata_digest
        or not all(c.success for c in row.calls)
    ):
        return (failure("QUALITY_CREDENTIAL_RECEIPT_MISMATCH"),)
    if row.attack_id is not None:
        return (failure("QUALITY_UNEXPECTED_CREDENTIAL_ATTACK_ID"),)
    return ()
