"""Independent protocol verdicts; never equate HTTP 200 or isError=false with business success."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import Element, SubElement, tostring

from pydantic import Field, ValidationError
from scripts.selftest.contracts import Contract, Identity, canonical_digest
from scripts.selftest.io import HarnessError, JsonObject, read_json, write_json
from scripts.selftest.mcp_negative_contracts import (
    ActorGolden,
    ProtocolEvidence,
    ProtocolGolden,
    ProtocolManifest,
    ProtocolObservation,
    ProtocolPack,
    ProtocolScenario,
    ResultProjection,
    RpcId,
    RpcRequest,
)


class ProtocolFinding(Contract):
    code: Identity
    status: Literal["incomplete", "mismatched"]


class ScenarioVerdict(Contract):
    scenario_id: Identity
    verification_status: Literal["matched", "incomplete", "mismatched"]
    findings: tuple[ProtocolFinding, ...]


class ProtocolReport(Contract):
    batch_key: Identity
    exit_code: Literal[0, 1, 2]
    findings: tuple[ProtocolFinding, ...]
    scenarios: tuple[ScenarioVerdict, ...] = Field(max_length=50)
    trust: Literal["local_untrusted"] = "local_untrusted"


def finding(code: str, incomplete: bool = False) -> ProtocolFinding:
    return ProtocolFinding(code=code, status="incomplete" if incomplete else "mismatched")


def _projection(expected: ProtocolGolden, actual: ResultProjection) -> tuple[ProtocolFinding, ...]:
    fields = (
        "is_error",
        "business_code",
        "diagnostic_code",
        "rpc_error_code",
        "text_marker",
    )
    for field in fields:
        wanted, observed = getattr(expected, field), getattr(actual, field)
        if field == "is_error" and wanted is None:
            continue
        if wanted != observed:
            return (finding("PROTOCOL_RAW_RESULT_MISMATCH"),)
    if expected.trace_required and not actual.trace_present:
        return (finding("PROTOCOL_TRACE_MISSING", True),)
    if actual.item_count < expected.minimum_items or actual.project_ids != expected.project_ids:
        return (finding("PROTOCOL_PROJECT_OR_CATALOG_MISMATCH"),)
    if expected.organization_id is not None and (
        actual.organization_id != expected.organization_id
        or actual.effective_scopes != expected.effective_scopes
        or actual.runtime_profile != expected.runtime_profile
    ):
        return (finding("PROTOCOL_CONNECTION_IDENTITY_MISMATCH"),)
    return ()


def _group(expected: ProtocolGolden, actual: ProtocolObservation) -> tuple[ProtocolFinding, ...]:
    if len(expected.group) != len(actual.results):
        return (finding("PROTOCOL_PRINCIPAL_RESULT_MISSING", True),)
    for wanted, observed in zip(expected.group, actual.results, strict=True):
        if (
            observed.actor != wanted.actor
            or observed.is_error is not False
            or observed.business_code != wanted.business_code
            or observed.diagnostic_code != wanted.diagnostic_code
            or observed.project_ids != wanted.project_ids
            or (wanted.project_ids and (observed.total != 1 or observed.item_count != 1))
            or (wanted.business_code is not None and not observed.trace_present)
        ):
            return (finding("PROTOCOL_PRINCIPAL_ISOLATION_MISMATCH"),)
    return ()


def _wire_id(session: object, identity: RpcId | None) -> str:
    return str(session) + ":" + canonical_digest(identity)


def _request_binding(expected: ProtocolScenario, request: RpcRequest) -> bool:
    if expected.expected.tool_name is not None:
        return (
            request.method == "tools/call"
            and request.tool_name == expected.expected.tool_name
            and request.arguments_digest == expected.expected.arguments_digest
        )
    methods = {
        "modern": "tools/list",
        "legacy": "tools/list",
        "unsupported": "server/discover",
        "resources": "resources/read",
        "prompts": "prompts/get",
    }
    return request.method == methods.get(expected.operation)


def _wire(expected: ProtocolScenario, actual: ProtocolObservation) -> tuple[ProtocolFinding, ...]:
    requests = {_wire_id(row.session_id, row.id): row for row in actual.requests}
    responses = {_wire_id(row.session_id, row.id): row for row in actual.responses}
    if not requests or set(requests) != set(responses):
        return (finding("PROTOCOL_WIRE_RESPONSE_MISSING", True),)
    if len(requests) != len(actual.requests) or len(responses) != len(actual.responses):
        return (finding("PROTOCOL_RPC_ID_DUPLICATE"),)
    for result in actual.results:
        key = _wire_id(result.session_id, result.rpc_id)
        request, response = requests.get(key), responses.get(key)
        if request is None or response is None or not _request_binding(expected, request):
            return (finding("PROTOCOL_REQUEST_BINDING_MISMATCH"),)
        if expected.operation != "unsupported" and result.sdk_result_digest is None:
            return (finding("PROTOCOL_SDK_RESULT_DIGEST_MISSING", True),)
        if expected.operation != "legacy" and result.sdk_result_digest != result.result_digest:
            return (finding("PROTOCOL_SDK_WIRE_PROJECTION_MISMATCH"),)
        if (
            response.error_code != result.rpc_error_code
            or response.result_digest != result.result_digest
        ):
            return (finding("PROTOCOL_WIRE_RESULT_MISMATCH"),)
        if (
            not actual.started_at
            <= request.observed_at
            <= response.observed_at
            <= actual.completed_at
        ):
            return (finding("PROTOCOL_WIRE_TIME_MISMATCH"),)
    return ()


def _observed_asset_fields(actual: ProtocolObservation) -> tuple[ProtocolFinding, ...]:
    required = set(type(actual.assets).model_fields)
    if (
        actual.assets.model_fields_set != required
        or actual.before_assets.model_fields_set != required
    ):
        return (finding("PROTOCOL_ASSET_COUNTER_MISSING", True),)
    return ()


def _observed_tool_fields(
    expected: ProtocolScenario, actual: ProtocolObservation
) -> tuple[ProtocolFinding, ...]:
    if expected.operation in {"modern", "legacy", "unsupported", "resources", "prompts"}:
        return ()
    required = {
        "is_error",
        "business_code",
        "diagnostic_code",
        "text_marker",
        "project_ids",
        "total",
        "item_count",
        "organization_id",
        "effective_scopes",
        "runtime_profile",
        "trace_present",
        "result_digest",
    }
    if any(not required <= item.model_fields_set for item in actual.results):
        return (finding("PROTOCOL_TOOL_RESULT_FIELD_MISSING", True),)
    return ()


def scenario_findings(
    manifest: ProtocolManifest,
    expected: ProtocolScenario,
    actual: ProtocolObservation,
) -> tuple[ProtocolFinding, ...]:
    result: list[ProtocolFinding] = []
    if not actual.complete or actual.error_code is not None or not actual.results:
        return (finding("PROTOCOL_OBSERVATION_INCOMPLETE", True),)
    if (
        actual.transport,
        actual.actor,
        actual.sdk_version,
        actual.protocol_version,
    ) != (
        expected.transport,
        expected.actor,
        manifest.sdk_version,
        expected.expected.protocol_version,
    ):
        result.append(finding("PROTOCOL_IDENTITY_MISMATCH"))
    if expected.operation != "unsupported" and (
        actual.catalog_fingerprint != manifest.catalog_fingerprint
        or actual.tool_names != manifest.tool_names
        or len(actual.tool_names) != len(set(actual.tool_names))
    ):
        result.append(finding("PROTOCOL_CATALOG_MISMATCH"))
    if (
        actual.assets != expected.expected.assets
        or actual.before_assets != expected.expected.assets
    ):
        result.append(finding("PROTOCOL_UNEXPECTED_ASSET_SIDE_EFFECT"))
    if not manifest.created_at <= actual.started_at <= actual.completed_at <= manifest.expires_at:
        result.append(finding("PROTOCOL_OBSERVATION_TIME_MISMATCH"))
    result.extend(_observed_asset_fields(actual))
    result.extend(_observed_tool_fields(expected, actual))
    result.extend(_wire(expected, actual))
    if expected.expected.group:
        result.extend(_group(expected.expected, actual))
    elif len(actual.results) != 1:
        result.append(finding("PROTOCOL_RESULT_SET_MISMATCH"))
    else:
        result.extend(_projection(expected.expected, actual.results[0]))
    return tuple(result)


def _golden_arguments(
    manifest: ProtocolManifest, scenario: ProtocolScenario
) -> tuple[str, JsonObject]:
    if scenario.operation == "unknown_tool":
        return "flowtest.selftest_unknown", {}
    if scenario.operation == "bad_params":
        return "flowtest.list_projects", {"page": "bad"}
    if scenario.operation == "cross_org":
        return "flowtest.inspect_project", {"project_id": str(manifest.fixture.project_b)}
    if scenario.operation == "inspect":
        return "flowtest.inspect_connection", {"request": {}}
    if scenario.operation == "propose_denied":
        return "flowtest.propose_test_design", {
            "project_id": str(manifest.fixture.project_a),
            "title": "只读账号不得提案",
            "confidence": 1.0,
            "risk_level": "low",
            "idempotency_key": scenario.scenario_id,
            "dry_run": False,
            "design": {
                "intent": {
                    "key": "selftest.scope",
                    "objective": "拒绝超权限提案",
                    "acceptance_criteria": ["保持零副作用"],
                },
                "oracles": [
                    {
                        "id": "status",
                        "kind": "status",
                        "expression": "$.status",
                        "confidence": 1.0,
                        "expected": 200,
                    }
                ],
            },
        }
    return "flowtest.list_projects", {}


def _bound_golden(manifest: ProtocolManifest, scenario: ProtocolScenario) -> ProtocolGolden:
    expected = scenario.expected
    if scenario.operation not in {
        "modern",
        "legacy",
        "unsupported",
        "resources",
        "prompts",
    }:
        name, arguments = _golden_arguments(manifest, scenario)
        expected = expected.model_copy(
            update={"tool_name": name, "arguments_digest": canonical_digest(arguments)}
        )
    if scenario.operation in {"interleaved", "concurrent"}:
        expected = expected.model_copy(
            update={
                "group": (
                    ActorGolden(actor="reader_a", project_ids=(manifest.fixture.project_a,)),
                    ActorGolden(actor="reader_b", project_ids=(manifest.fixture.project_b,)),
                    ActorGolden(
                        actor="none",
                        project_ids=(),
                        business_code="MCP_AUTHENTICATION_REQUIRED",
                        diagnostic_code="AUTH_REQUIRED",
                    ),
                )
            }
        )
    if scenario.operation == "resources":
        expected = expected.model_copy(update={"project_ids": (manifest.fixture.project_a,)})
    if scenario.operation == "inspect":
        expected = expected.model_copy(update={"organization_id": manifest.fixture.organization_a})
    return expected


def _frozen_pack(manifest: ProtocolManifest, pack_path: Path) -> tuple[ProtocolFinding, ...]:
    raw = read_json(pack_path)
    pack = ProtocolPack.model_validate(raw)
    if canonical_digest(raw) != manifest.pack_digest:
        return (finding("PROTOCOL_TRUSTED_PACK_DIGEST_MISMATCH"),)
    if tuple(item.scenario_id for item in manifest.scenarios) != tuple(
        item.scenario_id for item in pack.scenarios
    ):
        return (finding("PROTOCOL_FROZEN_DENOMINATOR_MISMATCH"),)
    if (
        manifest.catalog_fingerprint != pack.catalog_fingerprint
        or manifest.tool_names != pack.tool_names
    ):
        return (finding("PROTOCOL_TRUSTED_CATALOG_MISMATCH"),)
    for actual, expected in zip(manifest.scenarios, pack.scenarios, strict=True):
        if actual.model_dump(exclude={"expected"}) != expected.model_dump(exclude={"expected"}):
            return (finding("PROTOCOL_FROZEN_SCENARIO_MISMATCH"),)
        if actual.expected != _bound_golden(manifest, expected):
            return (finding("PROTOCOL_GOLDEN_MUTATED"),)
    return ()


def _attempt_fields(evidence: ProtocolEvidence) -> tuple[ProtocolFinding, ...]:
    result: list[ProtocolFinding] = []
    if not {"rejected_http_requests", "rejected_tool_calls"} <= evidence.model_fields_set:
        result.append(finding("PROTOCOL_REJECTION_COUNTER_MISSING", True))
    requests = [request for scenario in evidence.scenarios for request in scenario.requests]
    identities = [_wire_id(request.session_id, request.id) for request in requests]
    if len(set(identities)) != len(identities):
        result.append(finding("PROTOCOL_RPC_RECEIPT_REUSED"))
    attempts = sum(request.method == "tools/call" for request in requests)
    if attempts > evidence.protocol_attempts:
        result.append(finding("PROTOCOL_TOOL_ATTEMPT_COUNT_MISMATCH"))
    if attempts < evidence.protocol_attempts:
        result.append(finding("PROTOCOL_TOOL_ATTEMPT_RECEIPTS_MISSING", True))
    return tuple(result)


def verify_protocol(
    manifest: ProtocolManifest,
    evidence: ProtocolEvidence,
    *,
    now: datetime | None = None,
    pack_path: Path | None = None,
) -> ProtocolReport:
    frozen = (
        pack_path
        or Path(__file__).resolve().parents[2] / "selftest/packs/mcp-negative-v1/pack.json"
    )
    findings = [*_frozen_pack(manifest, frozen), *_attempt_fields(evidence)]
    identity = ("batch_key", "nonce", "pack_digest", "source_digest", "trust")
    if any(getattr(manifest, field) != getattr(evidence, field) for field in identity):
        findings.append(finding("PROTOCOL_BATCH_IDENTITY_MISMATCH"))
    if (
        now or datetime.now(UTC)
    ) > manifest.expires_at or evidence.collected_at > manifest.expires_at:
        findings.append(finding("PROTOCOL_BATCH_EXPIRED", True))
    if evidence.rejected_http_requests:
        findings.append(finding("PROTOCOL_HTTP_BUDGET_EXCEEDED"))
    if evidence.rejected_tool_calls:
        findings.append(finding("PROTOCOL_TOOL_BUDGET_EXCEEDED"))
    if not evidence.cleanup_complete:
        findings.append(finding("PROTOCOL_FIXTURE_CLEANUP_INCOMPLETE", True))
    actual = {item.scenario_id: item for item in evidence.scenarios}
    required = [item.scenario_id for item in manifest.scenarios]
    if len(actual) != len(evidence.scenarios) or set(actual) - set(required):
        findings.append(finding("PROTOCOL_SCENARIO_SET_MISMATCH"))
    rows = []
    for wanted in manifest.scenarios:
        failures = (
            scenario_findings(manifest, wanted, actual[wanted.scenario_id])
            if wanted.scenario_id in actual
            else (finding("PROTOCOL_REQUIRED_SCENARIO_MISSING", True),)
        )
        status = (
            "incomplete"
            if any(item.status == "incomplete" for item in failures)
            else "mismatched"
            if failures
            else "matched"
        )
        rows.append(
            ScenarioVerdict(
                scenario_id=wanted.scenario_id,
                verification_status=status,
                findings=failures,
            )
        )
    statuses = {item.status for item in findings} | {
        failure.status for row in rows for failure in row.findings
    }
    code = 1 if "mismatched" in statuses else 2 if statuses else 0
    return ProtocolReport(
        batch_key=manifest.batch_key,
        exit_code=code,
        findings=tuple(findings),
        scenarios=tuple(rows),
    )


def write_reports(report: ProtocolReport, evidence: ProtocolEvidence, directory: Path) -> None:
    write_json(directory / "verification.json", report)
    verification = Element(
        "testsuite",
        name="protocol-independent-verification",
        tests=str(len(report.scenarios) + bool(report.findings)),
    )
    raw = Element("testsuite", name="protocol-raw-results", tests=str(len(evidence.scenarios)))
    if report.findings:
        case = SubElement(verification, "testcase", name="batch-global")
        SubElement(case, "failure").text = ",".join(item.code for item in report.findings)
    for scenario in report.scenarios:
        row = SubElement(verification, "testcase", name=scenario.scenario_id)
        if scenario.findings:
            SubElement(row, "failure").text = ",".join(item.code for item in scenario.findings)
    for observed in evidence.scenarios:
        row = SubElement(raw, "testcase", name=observed.scenario_id)
        if any(
            item.is_error or item.business_code or item.rpc_error_code for item in observed.results
        ):
            SubElement(row, "failure").text = "原始工具/业务/协议失败, 未改写为成功"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "verification.junit.xml").write_bytes(
        tostring(verification, encoding="utf-8", xml_declaration=True)
    )
    (directory / "execution.junit.xml").write_bytes(
        tostring(raw, encoding="utf-8", xml_declaration=True)
    )


def write_incomplete_reports(directory: Path, code: str) -> ProtocolReport:
    report = ProtocolReport(
        batch_key="invalid-input", exit_code=2, findings=(finding(code, True),), scenarios=()
    )
    write_json(directory / "verification.json", report)
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("execution", "verification"):
        root = Element("testsuite", name="protocol-incomplete", tests="1")
        SubElement(SubElement(root, "testcase", name="input-or-fixture"), "failure").text = code
        (directory / (name + ".junit.xml")).write_bytes(
            tostring(root, encoding="utf-8", xml_declaration=True)
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = ProtocolManifest.model_validate(read_json(args.manifest))
        evidence = ProtocolEvidence.model_validate(read_json(args.evidence))
        report = verify_protocol(manifest, evidence)
    except (ValidationError, HarnessError, OSError, ValueError):
        write_incomplete_reports(args.output, "PROTOCOL_CONTRACT_INVALID")
        return 2

    write_reports(report, evidence, args.output)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
