"""Draft public-API runtime fault driver; isolated ownership is mandatory.

This module does not import product services, repositories, models or executor internals.
Its oracle is the immutable expectations document, not the final successful attempt.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

import httpx
from pydantic import Field, JsonValue, TypeAdapter
from scripts.selftest.contracts import (
    Contract,
    FixtureBudgetReceipt,
    FixtureBudgetScope,
    FixtureJournal,
    Sha256,
    canonical_digest,
)
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    integer_value,
    object_value,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import (
    StackBinding,
    _docker,
    _verify_labels,
    verify_binding,
)
from scripts.selftest.namespace_conditions import read_namespace_condition
from scripts.selftest.profile_stack import ProfileProof

Terminal = Literal["passed", "failed", "cancelled", "quarantined"]
Status = Literal["queued", "running", "passed", "failed", "cancelled", "quarantined"]
Verification = Literal["matched", "mismatched", "incomplete", "error"]


class Golden(Contract):
    scenario_id: Literal["ST-RUN-001", "ST-RUN-002", "ST-RUN-003", "ST-RUN-005", "ST-RUN-006"]
    variant: str = Field(pattern=r"^[a-z][a-z-]{0,50}$")
    native_status: Terminal
    markers: tuple[str, ...] = Field(max_length=3)
    trigger: Literal["manual", "ci"] | None = None
    same_operation_ids: Literal[1] | None = None
    allowed_conflict: Literal["IDEMPOTENCY_IN_PROGRESS"] | None = None
    required_conflict: Literal["IDEMPOTENCY_KEY_REUSED"] | None = None
    stage: Literal["queued", "running"] | None = None
    force: bool = False
    skip_cleanup: bool = False
    observer_status: Literal["incomplete", "error"] | None = None
    observer_exit_code: Literal[2, 70] | None = None
    required_reason: str | None = None
    characterization_only: bool = False
    expected_api_version: Literal[1] | None = None
    expected_independent_status: Literal["blocked"] | None = None
    actual_environment_value: str | None = None

    @property
    def key(self) -> str:
        return self.scenario_id + ":" + self.variant


class Pack(Contract):
    schema_version: Literal["flowtest-runtime-fault-golden-v1"]
    pack_id: Literal["runtime-faults-v1"]
    pack_version: Literal["1.0.0-draft"]
    max_requests: Literal[100]
    max_runtime_seconds: Literal[600]
    variants: tuple[Golden, ...] = Field(min_length=15, max_length=15)


class Operation(Contract):
    id: UUID
    status: Status
    trigger: Literal["manual", "ci"] | None = None
    target_digest: Sha256 | None = None


class Snapshot(Contract):
    run: Operation
    execution_ids: tuple[UUID, ...] = Field(max_length=10)
    item_statuses: tuple[Status, ...] = Field(max_length=10)
    api_versions: tuple[int, ...] = Field(max_length=20)
    snapshot_digests: tuple[Sha256, ...] = Field(max_length=10)
    environment_digest: Sha256 | None = None


class ObserverResult(Contract):
    status: Literal["incomplete", "error"]
    exit_code: Literal[2, 70]
    reason_code: Literal["OBSERVER_DEADLINE_EXCEEDED", "OBSERVER_PROCESS_CRASHED"]
    observed_native_status: Status


class Observation(Contract):
    scenario_id: str
    variant: str
    operations: tuple[Operation, ...] = Field(max_length=20)
    final: Snapshot | None = None
    conflicts: tuple[str, ...] = Field(default=(), max_length=20)
    markers: tuple[str, ...] = Field(default=(), max_length=20)
    cancellation_stage: Literal["queued", "running"] | None = None
    observer: ObserverResult | None = None
    independent_status: Literal["complete", "blocked"] = "complete"
    reason_codes: tuple[str, ...] = Field(default=(), max_length=10)
    cleanup_status: Literal["completed", "pending", "failed", "needs_review"] = "pending"
    pending_observed: bool = False
    lost_response_after_send: bool = False
    request_count: int = Field(default=0, ge=0, le=100)
    first_wire_value: JsonValue = None
    budget: FixtureBudgetReceipt | None = None


class Finding(Contract):
    code: str
    message: str


class VariantReport(Contract):
    scenario_id: str
    variant: str
    status: Verification
    native_status: Status | None
    findings: tuple[Finding, ...] = Field(max_length=20)
    characterization_only: bool = False


def load_pack(path: Path) -> tuple[Pack, Sha256]:
    document = read_json(path)
    pack = Pack.model_validate(document)
    if len({item.key for item in pack.variants}) != 15:
        raise HarnessError("RUNTIME_FAULT_DUPLICATE_VARIANT")
    return pack, canonical_digest(document)


def _failure(code: str) -> Finding:
    return Finding(code=code, message=code)


def verify(golden: Golden, observed: Observation) -> VariantReport:
    findings: list[Finding] = []
    if (golden.scenario_id, golden.variant) != (observed.scenario_id, observed.variant):
        findings.append(_failure("RUNTIME_FAULT_IDENTITY_CHANGED"))
    if observed.final is None:
        findings.append(_failure("RUNTIME_FAULT_NATIVE_EVIDENCE_MISSING"))
    else:
        _verify_final(golden, observed, findings)
    _verify_protocol(golden, observed, findings)
    _verify_observer(golden, observed, findings)
    if observed.cleanup_status != "completed":
        findings.append(_failure("RUNTIME_FAULT_CLEANUP_NOT_CONFIRMED"))
    incomplete = any(
        item.code.endswith(("MISSING", "NOT_OBSERVED", "NOT_CONFIRMED")) for item in findings
    )
    status: Verification = "incomplete" if incomplete else "mismatched" if findings else "matched"
    return VariantReport(
        scenario_id=golden.scenario_id,
        variant=golden.variant,
        status=status,
        native_status=observed.final.run.status if observed.final else None,
        findings=tuple(findings),
        characterization_only=golden.characterization_only,
    )


def _verify_final(golden: Golden, observed: Observation, findings: list[Finding]) -> None:
    final = observed.final
    if final is None:
        raise HarnessError("RUNTIME_FAULT_NATIVE_EVIDENCE_MISSING")
    if final.run.status != golden.native_status:
        findings.append(_failure("RUNTIME_FAULT_NATIVE_STATUS_MISMATCH"))
    if any(
        status not in {"passed", "failed", "cancelled", "quarantined"}
        for status in final.item_statuses
    ):
        findings.append(_failure("RUNTIME_FAULT_NONTERMINAL_CHILD"))
    if golden.trigger and final.run.trigger != golden.trigger:
        findings.append(_failure("RUNTIME_FAULT_TRIGGER_MISMATCH"))
    if observed.markers != golden.markers:
        findings.append(_failure("RUNTIME_FAULT_WIRE_SEQUENCE_MISMATCH"))
    if golden.stage and observed.cancellation_stage != golden.stage:
        findings.append(_failure("RUNTIME_FAULT_REQUIRED_STAGE_NOT_OBSERVED"))
    if golden.expected_api_version is not None and (
        not final.api_versions or set(final.api_versions) != {golden.expected_api_version}
    ):
        findings.append(_failure("RUNTIME_FAULT_API_VERSION_MISMATCH"))
    if (
        golden.expected_independent_status
        and observed.independent_status != golden.expected_independent_status
    ):
        findings.append(_failure("RUNTIME_FAULT_DRIFT_NOT_BLOCKED"))
    _verify_environment(golden, observed, findings)
    _verify_attempts(golden, observed, findings)


def _verify_attempts(golden: Golden, observed: Observation, findings: list[Finding]) -> None:
    final = observed.final
    if final is None:
        return
    if len(final.item_statuses) != 1:
        findings.append(_failure("RUNTIME_FAULT_REQUIRED_CHILD_MISSING"))
    expected_executions = 0 if golden.variant == "queued" else 1
    if len(final.execution_ids) != expected_executions:
        findings.append(_failure("RUNTIME_FAULT_ATTEMPT_DENOMINATOR_MISMATCH"))


def _verify_environment(golden: Golden, observed: Observation, findings: list[Finding]) -> None:
    if (
        golden.actual_environment_value is not None
        and observed.first_wire_value != golden.actual_environment_value
    ):
        findings.append(_failure("RUNTIME_FAULT_ACTUAL_ENVIRONMENT_NOT_OBSERVED"))
    if (
        golden.required_reason
        and golden.observer_status is None
        and golden.required_reason not in observed.reason_codes
    ):
        findings.append(_failure("RUNTIME_FAULT_REQUIRED_REASON_MISSING"))


def _verify_protocol(golden: Golden, observed: Observation, findings: list[Finding]) -> None:
    if (
        golden.same_operation_ids is not None
        and len({item.id for item in observed.operations}) != 1
    ):
        findings.append(_failure("RUNTIME_FAULT_DUPLICATE_OPERATION"))
    allowed = {value for value in (golden.allowed_conflict, golden.required_conflict) if value}
    if set(observed.conflicts) - allowed:
        findings.append(_failure("RUNTIME_FAULT_UNEXPECTED_CONFLICT"))
    if golden.required_conflict and golden.required_conflict not in observed.conflicts:
        findings.append(_failure("RUNTIME_FAULT_REQUIRED_CONFLICT_NOT_OBSERVED"))
    if golden.variant == "concurrent" and not observed.pending_observed:
        findings.append(_failure("RUNTIME_FAULT_PENDING_NOT_OBSERVED"))
    if golden.variant == "lost-response" and not observed.lost_response_after_send:
        findings.append(_failure("RUNTIME_FAULT_LOST_RESPONSE_NOT_OBSERVED"))


def _verify_observer(golden: Golden, observed: Observation, findings: list[Finding]) -> None:
    if golden.observer_status is None:
        return
    child = observed.observer
    if child is None:
        findings.append(_failure("RUNTIME_FAULT_OBSERVER_EVIDENCE_MISSING"))
    elif (
        child.status != golden.observer_status
        or child.exit_code != golden.observer_exit_code
        or child.reason_code != golden.required_reason
        or child.observed_native_status != "running"
    ):
        findings.append(_failure("RUNTIME_FAULT_OBSERVER_RESULT_MISMATCH"))


def operation(raw: JsonObject) -> Operation:
    return Operation.model_validate(
        {
            "id": text_value(raw.get("run_id", raw.get("id"))),
            "status": raw["status"],
            "trigger": raw.get("trigger_type"),
        }
    )


async def launch_same_key(
    api: PublicAPI,
    path: str,
    key: str,
    *,
    payload: JsonObject | None = None,
) -> tuple[Operation | None, str | None]:
    raw = object_value(
        await api.request("POST", path, payload, idempotency_key=key, allow_status=(409,))
    )
    if "error" not in raw:
        return operation(raw), None
    code = text_value(object_value(raw["error"])["code"])
    if code not in {"IDEMPOTENCY_IN_PROGRESS", "IDEMPOTENCY_KEY_REUSED"}:
        raise HarnessError("RUNTIME_FAULT_UNEXPECTED_ERROR:" + code)
    return None, code


async def recover_same_key(
    api: PublicAPI,
    path: str,
    key: str,
    *,
    payload: JsonObject | None = None,
    attempts: int = 30,
) -> Operation:
    for _ in range(attempts):
        result, conflict = await launch_same_key(api, path, key, payload=payload)
        if result is not None:
            return result
        if conflict != "IDEMPOTENCY_IN_PROGRESS":
            raise HarnessError("RUNTIME_FAULT_RECOVERY_CONFLICT")
        await asyncio.sleep(0.1)
    raise HarnessError("RUNTIME_FAULT_IDEMPOTENCY_PENDING_NEEDS_REVIEW")


class DropCompletedResponse(httpx.AsyncBaseTransport):
    """An actual request is sent exactly once, then its response is intentionally lost."""

    def __init__(self, upstream: httpx.AsyncBaseTransport) -> None:
        self.upstream = upstream
        self.completed_and_dropped = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.upstream.handle_async_request(request)
        await response.aread()
        self.completed_and_dropped = True
        await response.aclose()
        raise httpx.ReadTimeout("RUNTIME_FAULT_INJECTED_RESPONSE_LOSS", request=request)

    async def aclose(self) -> None:
        await self.upstream.aclose()


class RuntimeGate(Protocol):
    def held(self) -> AbstractAsyncContextManager[None]: ...

    def resume(self) -> None: ...


class OwnedWorkers:
    """Fault injection only; no product state or DB is edited."""

    def __init__(self, binding: StackBinding, directory: Path) -> None:
        verify_binding(binding, directory)
        if binding.runtime_profile not in {"full", "compact"}:
            raise HarnessError("RUNTIME_FAULT_QUEUED_STAGE_UNAVAILABLE")
        proof = ProfileProof.model_validate(read_json(directory / "profile-proof.json"))
        self.binding = binding
        self.identities = tuple(
            item
            for item in proof.containers
            if item.role in {"runner-worker", "runner-worker-data"}
        )
        if len(self.identities) != (2 if binding.runtime_profile == "full" else 1):
            raise HarnessError("RUNTIME_FAULT_WORKER_OWNERSHIP_INCOMPLETE")
        self.paused = False

    def _check(self) -> None:
        for expected in self.identities:
            raw = object_value(json.loads(_docker(["inspect", expected.container_id]))[0])
            config = object_value(raw["Config"])
            _verify_labels(self.binding, object_value(config["Labels"]))
            if raw["Id"] != expected.container_id or raw["Image"] != expected.image_digest:
                raise HarnessError("RUNTIME_FAULT_WORKER_IDENTITY_CHANGED")

    def pause(self) -> None:
        self._check()
        _docker(["pause", *(item.container_id for item in self.identities)])
        self.paused = True

    def resume(self) -> None:
        if self.paused:
            self._check()
            _docker(["unpause", *(item.container_id for item in self.identities)])
            self.paused = False

    @asynccontextmanager
    async def held(self) -> AsyncIterator[None]:
        self.pause()
        try:
            yield
        finally:
            self.resume()


class JournalSummary(Contract):
    markers: tuple[str, ...]
    request_count: int = Field(ge=0, le=100)
    complete: bool
    epoch: str
    first_value: JsonValue = None
    budget: FixtureBudgetReceipt | None = None


async def read_journal(observer: PublicAPI, batch: str, scenario: str) -> JournalSummary:
    raw = await observer.object(
        "GET", f"/selftest/batches/{batch}/scenarios/{scenario}/journal?limit=100"
    )
    entries = objects_value(raw["entries"])
    complete = (
        not any(raw.get(key) for key in ("truncated", "expired", "epoch_changed"))
        and raw.get("next_sequence") is None
    )
    if raw["request_count"] != len(entries):
        complete = False
    return JournalSummary(
        markers=tuple(text_value(item["marker"]) for item in entries),
        request_count=integer_value(raw["request_count"]),
        complete=complete,
        epoch=text_value(raw["fixture_epoch"]),
        budget=FixtureBudgetReceipt.model_validate(raw["budget"]) if raw.get("budget") else None,
        first_value=object_value(entries[0]["request_body"]).get("value") if entries else None,
    )


async def wait_marker(
    observer: PublicAPI, batch: str, scenario: str, marker: str, deadline: datetime
) -> JournalSummary:
    for _ in range(300):
        current = await read_journal(observer, batch, scenario)
        if not current.complete:
            raise HarnessError("RUNTIME_FAULT_JOURNAL_INCOMPLETE")
        if marker in current.markers:
            return current
        if datetime.now(UTC) >= deadline:
            break
        await asyncio.sleep(0.05)
    raise HarnessError("RUNTIME_FAULT_MARKER_NOT_OBSERVED")


def uuid_values(value: object) -> tuple[UUID, ...]:
    if not isinstance(value, list):
        raise HarnessError("RUNTIME_FAULT_EXPECTED_ID_LIST")
    return tuple(UUID(text_value(item)) for item in value)


async def read_plan(reader: PublicAPI, project: UUID, run: UUID) -> Snapshot:
    raw = await reader.object(
        "GET", f"/ci/projects/{project}/test-plan-runs/{run}?page=1&page_size=100"
    )
    items = objects_value(raw["items"])
    if (
        raw.get("has_more") is not False
        or raw.get("truncated") is not False
        or raw["total"] != len(items)
    ):
        raise HarnessError("RUNTIME_FAULT_PLAN_EVIDENCE_INCOMPLETE")
    if any(
        item.get("attempts_complete") is not True
        or item["attempts"] != len(uuid_values(item["execution_ids"]))
        for item in items
    ):
        raise HarnessError("RUNTIME_FAULT_ATTEMPT_EVIDENCE_INCOMPLETE")
    executions = tuple(value for item in items for value in uuid_values(item["execution_ids"]))
    api_versions: list[int] = []
    snapshots: list[str] = []
    for execution in executions:
        detail = await reader.object(
            "GET", f"/ci/projects/{project}/workflow-executions/{execution}/evidence"
        )
        if detail.get("bindings_complete") is not True or detail.get("truncated") is not False:
            raise HarnessError("RUNTIME_FAULT_EXECUTION_EVIDENCE_INCOMPLETE")
        api_versions.extend(
            integer_value(item["api_version"]) for item in objects_value(detail["api_bindings"])
        )
        snapshots.append(text_value(detail["snapshot_digest"]))
    return Snapshot(
        run=operation(raw).model_copy(
            update={
                "target_digest": canonical_digest(
                    [item["target_snapshot_digest"] for item in items]
                )
            }
        ),
        execution_ids=executions,
        item_statuses=tuple(TypeAdapter(Status).validate_python(item["status"]) for item in items),
        api_versions=tuple(api_versions),
        snapshot_digests=tuple(snapshots),
    )


async def wait_terminal(
    reader: PublicAPI, project: UUID, run: UUID, deadline: datetime
) -> Snapshot:
    for _ in range(360):
        current = await read_plan(reader, project, run)
        terminal = {"passed", "failed", "cancelled", "quarantined"}
        if current.run.status in terminal and all(
            item in terminal for item in current.item_statuses
        ):
            return current
        if datetime.now(UTC) >= deadline:
            break
        await asyncio.sleep(0.25)
    raise HarnessError("RUNTIME_FAULT_NATIVE_NOT_TERMINAL")


class Assets(Contract):
    project_id: UUID
    environment_id: UUID
    api_id: UUID
    workflow_id: UUID
    workflow_version: int
    workflow_fingerprint: Sha256
    case_id: UUID
    case_version: int
    suite_id: UUID
    suite_version: int
    plan_id: UUID
    batch_key: str
    scenario_key: str
    skip_cleanup: bool
    pinned: bool
    frozen_environment_digest: Sha256


async def _create(
    api: PublicAPI, directory: Path, label: str, path: str, payload: JsonObject
) -> JsonObject:
    receipt = directory / "mutations" / (label + ".json")
    identity = canonical_digest({"path": path, "payload": payload})
    if receipt.exists():
        saved = read_json(receipt)
        if saved.get("digest") != identity or saved.get("status") != "completed":
            raise HarnessError("RUNTIME_FAULT_MUTATION_UNKNOWN_OR_CHANGED")
        return object_value(saved["response"])
    write_json(receipt, {"digest": identity, "status": "pending"})
    response = await api.object("POST", path, payload)
    # Responses can contain write-only webhook secrets; keep only fields needed below.
    safe = {key: value for key, value in response.items() if key != "webhook_secret"}
    write_json(receipt, {"digest": identity, "status": "completed", "response": safe})
    return safe


def _node(node_id: str, kind: str, config: JsonObject, *, cleanup: bool = False) -> JsonObject:
    return {
        "id": node_id,
        "type": kind,
        "name": node_id,
        "position": {"x": 0.0, "y": 0.0},
        "config": config,
        "capability_id": None,
        "capability_version": None,
        "configuration": None,
        "bindings": None,
        "phase": "cleanup" if cleanup else "main",
        "run_when": "always",
        "cleanup_for": ["first"] if cleanup else [],
        "best_effort": False,
        "cleanup_timeout_seconds": 30,
        "cleanup_retry_budget": 0,
    }


def frozen_graph(api_id: UUID, *, pinned: bool, skip_cleanup: bool) -> JsonObject:
    def request(marker: str, cleanup: bool = False) -> JsonObject:
        config: JsonObject = {
            "api_definition_id": str(api_id),
            "request_overrides": {
                "body": {
                    "kind": "json",
                    "value": {
                        "marker": marker,
                        "value": "{{fault_environment_marker}}" if marker == "first" else marker,
                        "branch": "",
                        "iteration_key": "",
                    },
                }
            },
        }
        if pinned:
            config["api_version"] = 1
        return _node(marker, "api", config, cleanup=cleanup)

    return {
        "schema_version": "4.0",
        "variables": {},
        "runtime_inputs": [],
        "nodes": [
            _node("start", "start", {}),
            request("first"),
            request("follow"),
            _node("end", "end", {}),
            request("cleanup", True),
        ],
        "edges": [
            {
                "id": source + "-" + target,
                "source": source,
                "target": target,
                "condition": None,
                "mappings": [],
            }
            for source, target in (
                ("start", "first"),
                ("first", "follow"),
                ("follow", "end"),
            )
        ],
        "regions": [],
        "settings": {
            "fail_fast": True,
            "concurrency": 1,
            "default_timeout_seconds": 15,
        },
        "run_policy": {
            "request_budget": 3,
            "max_runtime_seconds": 45,
            "cleanup_request_budget": 1,
            "force_cancel_skips_cleanup": skip_cleanup,
        },
    }


def api_request(batch: str, scenario: str, *, second: bool = False) -> JsonObject:
    return {
        "base_version": 1 if second else None,
        "method": "POST",
        "path": f"/selftest/{batch}/{scenario}/" + ("sequence" if second else "request"),
        "query_parameters": [],
        "headers": {},
        "variables": {},
        "body_kind": "json",
        "body": {"marker": "first", "value": None, "branch": "", "iteration_key": ""},
        "auth": {"kind": "none", "values": {}},
        "extraction_rules": [],
        "assertions": [],
    }


async def install(
    api: PublicAPI,
    *,
    project: UUID,
    service: UUID,
    fixture_url: str,
    batch: str,
    scenario: str,
    directory: Path,
    pinned: bool = True,
    skip_cleanup: bool = False,
) -> Assets:
    root = f"/projects/{project}"
    environment = await _create(
        api,
        directory,
        "environment",
        root + "/environments",
        {
            "name": batch + ":" + scenario,
            "base_url": fixture_url,
            "classification": "test",
            "variables": {"fault_environment_marker": "frozen-v1"},
            "headers": {},
        },
    )
    created = await _create(
        api,
        directory,
        "api",
        root + "/apis",
        {
            "name": batch + ":" + scenario,
            "service_id": str(service),
            "request": api_request(batch, scenario),
        },
    )
    await _create(
        api,
        directory,
        "service-endpoint",
        root + f"/environments/{environment['id']}/service-endpoints",
        {
            "service_id": str(service),
            "variant": "default",
            "base_url": fixture_url,
        },
    )
    api_id = UUID(text_value(object_value(created["definition"])["id"]))
    graph = frozen_graph(api_id, pinned=pinned, skip_cleanup=skip_cleanup)
    expected_published = frozen_graph(api_id, pinned=True, skip_cleanup=skip_cleanup)
    if object_value(created["version"])["version"] != 1:
        raise HarnessError("RUNTIME_FAULT_INITIAL_API_VERSION_CHANGED")
    write_json(
        directory / "publication-binding.json",
        {
            "kind": "publication_pins_current_api",
            "input_api_version": 1 if pinned else None,
            "published_api_version": 1,
            "api_id": str(api_id),
            "input_graph_digest": canonical_digest(graph),
            "expected_published_graph_digest": canonical_digest(expected_published),
        },
    )
    workflow = await _create(
        api,
        directory,
        "workflow",
        root + "/workflows/native-import",
        {
            "format_version": "flowtest-workflow-native-v1",
            "name": batch + ":" + scenario,
            "description": "冻结运行边界基准",
            "definition": graph,
        },
    )
    workflow_id = UUID(text_value(workflow["id"]))
    published = await _create(
        api,
        directory,
        "workflow-publish",
        root + f"/workflows/{workflow_id}/versions",
        {},
    )
    if canonical_digest(published["definition"]) != canonical_digest(expected_published):
        raise HarnessError("RUNTIME_FAULT_PUBLISHED_GRAPH_CHANGED")
    case = await _create(
        api,
        directory,
        "case",
        root + "/test-cases",
        {
            "name": batch + ":" + scenario,
            "definition": {
                "workflow_id": str(workflow_id),
                "workflow_version": published["version"],
                "environment_id": environment["id"],
                "runtime_variables": {},
                "runtime_headers": {},
            },
        },
    )
    case_id = UUID(text_value(case["id"]))
    case_version = await _create(
        api, directory, "case-publish", root + f"/test-cases/{case_id}/versions", {}
    )
    suite = await _create(
        api,
        directory,
        "suite",
        root + "/test-suites",
        {
            "name": batch + ":" + scenario,
            "definition": {
                "items": [
                    {
                        "test_case_id": str(case_id),
                        "test_case_version": case_version["version"],
                    }
                ]
            },
        },
    )
    suite_id = UUID(text_value(suite["id"]))
    suite_version = await _create(
        api, directory, "suite-publish", root + f"/test-suites/{suite_id}/versions", {}
    )
    plan = await _create(
        api,
        directory,
        "plan",
        root + "/test-plans",
        {
            "name": batch + ":" + scenario,
            "items": [
                {
                    "target_type": "suite",
                    "target_id": str(suite_id),
                    "target_version": suite_version["version"],
                    "max_retries": 0,
                }
            ],
        },
    )
    result = Assets(
        project_id=project,
        environment_id=UUID(text_value(environment["id"])),
        api_id=api_id,
        workflow_id=workflow_id,
        workflow_version=integer_value(published["version"]),
        workflow_fingerprint=text_value(published["fingerprint"]),
        case_id=case_id,
        case_version=integer_value(case_version["version"]),
        suite_id=suite_id,
        suite_version=integer_value(suite_version["version"]),
        plan_id=UUID(text_value(plan["id"])),
        batch_key=batch,
        scenario_key=scenario,
        skip_cleanup=skip_cleanup,
        pinned=pinned,
        frozen_environment_digest=canonical_digest(environment),
    )
    write_json(directory / "assets.json", result)
    return result


async def configure(
    observer: PublicAPI,
    assets: Assets,
    digest: Sha256,
    *,
    slow: bool,
    scope: FixtureBudgetScope | None = None,
) -> None:
    policy = scope or FixtureBudgetScope(
        parent_batch_key=assets.batch_key,
        nonce=secrets.token_hex(16),
        limit=100,
        expires_at=(datetime.now(UTC) + timedelta(seconds=600)).timestamp(),
    )
    remaining = int(policy.expires_at - datetime.now(UTC).timestamp())
    if remaining < 1 or remaining > 600:
        raise HarnessError("RUNTIME_FAULT_FIXTURE_BUDGET_EXPIRED")
    await observer.request(
        "PUT",
        f"/selftest/batches/{assets.batch_key}/scenarios/{assets.scenario_key}",
        {
            "nonce": policy.nonce,
            "fixture_digest": digest,
            "ttl_seconds": remaining,
            "budget_scope": policy.model_dump(mode="json"),
            "max_entries": 20,
            "max_bytes": 32768,
            "response_statuses": [200],
            "response_body": {"actual": 1, "code": 0, "value": None},
            "delay_ms": 5000 if slow else 0,
        },
    )


async def cancel_plan(writer: PublicAPI, reader: PublicAPI, assets: Assets, run: UUID) -> Snapshot:
    await writer.request(
        "POST",
        f"/projects/{assets.project_id}/test-plan-runs/{run}/cancel",
        allow_status=(409,),
    )
    return await wait_terminal(
        reader, assets.project_id, run, datetime.now(UTC) + timedelta(seconds=60)
    )


async def concurrent_launch(
    api: PublicAPI, path: str, key: str
) -> tuple[tuple[Operation, ...], tuple[str, ...]]:
    responses = await asyncio.gather(*(launch_same_key(api, path, key) for _ in range(6)))
    conflicts = tuple(conflict for _, conflict in responses if conflict is not None)
    operations = tuple(result for result, _ in responses if result is not None)
    resolved = await recover_same_key(api, path, key)
    return (*operations, resolved), conflicts


async def observer_process(
    *,
    base_url: str,
    read_token: str,
    assets: Assets,
    run: UUID,
    directory: Path,
    crash: bool,
) -> ObserverResult:
    import sys

    arguments = [
        sys.executable,
        "-m",
        "scripts.selftest.runtime_fault_observer",
        "--output",
        str(directory),
        "--deadline",
        "0.1",
    ]
    if crash:
        arguments.append("--crash")
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    auth = json.dumps(
        {
            "url": base_url,
            "token": read_token,
            "project_id": str(assets.project_id),
            "run_id": str(run),
        }
    ).encode()
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(auth), timeout=10)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise HarnessError("RUNTIME_FAULT_OBSERVER_PROCESS_HUNG") from None
    if stdout or stderr:
        # Do not persist arbitrary child output; the typed receipts are the only evidence.
        write_json(
            directory / "observer-process.json",
            {"exit_code": process.returncode, "unexpected_output": True},
        )
        raise HarnessError("RUNTIME_FAULT_OBSERVER_UNEXPECTED_OUTPUT")
    if crash:
        if process.returncode != 70:
            raise HarnessError("RUNTIME_FAULT_OBSERVER_CRASH_NOT_OBSERVED")
        saved = Snapshot.model_validate(read_json(directory / "observer-last.json"))
        return ObserverResult(
            status="error",
            exit_code=70,
            reason_code="OBSERVER_PROCESS_CRASHED",
            observed_native_status=saved.run.status,
        )
    if process.returncode != 2:
        raise HarnessError("RUNTIME_FAULT_OBSERVER_DEADLINE_NOT_OBSERVED")
    return ObserverResult.model_validate(read_json(directory / "observer-result.json"))


@dataclass(frozen=True, repr=False)
class LossClient:
    api: PublicAPI
    witness: DropCompletedResponse


@dataclass(frozen=True, repr=False)
class RuntimeClients:
    writer: PublicAPI
    ci: PublicAPI
    reader: PublicAPI
    observer: PublicAPI
    base_url: str
    read_token: str
    response_loss_factory: Callable[[], LossClient] | None = None


class VariantRuntime:
    def __init__(
        self,
        golden: Golden,
        assets: Assets,
        clients: RuntimeClients,
        workers: RuntimeGate,
        directory: Path,
        *,
        fixture_nonce: str | None = None,
        fixture_digest: str | None = None,
        fixture_deadline: datetime | None = None,
    ) -> None:
        self.golden, self.assets, self.clients = golden, assets, clients
        self.workers, self.directory = workers, directory
        self.fixture_nonce, self.fixture_digest = fixture_nonce, fixture_digest
        self.fixture_deadline = fixture_deadline
        self.management_read_admitted = 0
        self.namespace_delete_status: Literal["not_attempted", "unknown", "completed"] = (
            "not_attempted"
        )
        self.operations: tuple[Operation, ...] = ()
        self.conflicts: tuple[str, ...] = ()
        self.run_id: UUID | None = None
        self.execution_id: UUID | None = None
        self.final: Snapshot | None = None
        self.stage: Literal["queued", "running"] | None = None
        self.child: ObserverResult | None = None
        self.dropped = False
        self.independent_status: Literal["complete", "blocked"] = "complete"
        self.reasons: tuple[str, ...] = ()
        self.cleanup_status: Literal["completed", "pending", "failed", "needs_review"] = "pending"

    @property
    def path(self) -> str:
        return f"/projects/{self.assets.project_id}/test-plans/{self.assets.plan_id}/runs"

    @property
    def key(self) -> str:
        return self.assets.batch_key + ":" + self.golden.variant

    def known_run(self) -> UUID:
        if self.run_id is None:
            raise HarnessError("RUNTIME_FAULT_LAUNCH_RESULT_UNKNOWN")
        return self.run_id

    async def execute(self) -> Observation:
        wire: JournalSummary | None = None
        try:
            await self.launch()
            if self.golden.stage == "running":
                await self.cancel_running()
            if self.final is None:
                self.final = await wait_terminal(
                    self.clients.reader,
                    self.assets.project_id,
                    self.known_run(),
                    datetime.now(UTC) + timedelta(seconds=75),
                )
            wire = await read_journal(
                self.clients.observer,
                self.assets.batch_key,
                self.assets.scenario_key,
            )
            if not wire.complete:
                raise HarnessError("RUNTIME_FAULT_JOURNAL_INCOMPLETE")
            write_json(self.directory / "journal-summary.json", wire)
        finally:
            await self.cleanup()
        return Observation(
            scenario_id=self.golden.scenario_id,
            variant=self.golden.variant,
            operations=self.operations,
            final=self.final,
            conflicts=self.conflicts,
            markers=wire.markers if wire else (),
            cancellation_stage=self.stage,
            observer=self.child,
            independent_status=self.independent_status,
            reason_codes=self.reasons,
            cleanup_status=self.cleanup_status,
            pending_observed="IDEMPOTENCY_IN_PROGRESS" in self.conflicts,
            lost_response_after_send=self.dropped,
            request_count=wire.request_count if wire else 0,
            first_wire_value=wire.first_value if wire else None,
            budget=wire.budget if wire else None,
        )

    async def launch(self) -> None:
        handlers = {
            "queued": self.queued,
            "unpinned-control": self.drift,
            "pinned-old-api": self.drift,
            "environment-drift": self.drift,
            "changed-payload": self.changed_payload,
            "concurrent": self.concurrent,
            "lost-response": self.response_loss,
        }
        await handlers.get(self.golden.variant, self.basic)()

    async def basic(self) -> None:
        client = self.clients.ci if self.golden.variant == "ci" else self.clients.writer
        path = "/ci" + self.path if self.golden.variant == "ci" else self.path
        run = await recover_same_key(client, path, self.key)
        self.operations, self.run_id = (run,), run.id
        if self.golden.variant == "same-key":
            repeat = await recover_same_key(client, path, self.key)
            self.operations = (*self.operations, repeat)

    async def queued(self) -> None:
        async with self.workers.held():
            await self.basic()
            before = await read_plan(self.clients.reader, self.assets.project_id, self.known_run())
            if before.run.status != "queued" or before.execution_ids:
                raise HarnessError("RUNTIME_FAULT_QUEUED_STAGE_NOT_OBSERVED")
            self.stage = "queued"
            self.final = await cancel_plan(
                self.clients.writer,
                self.clients.reader,
                self.assets,
                self.known_run(),
            )

    async def drift(self) -> None:
        async with self.workers.held():
            await self.basic()
            before = await read_plan(self.clients.reader, self.assets.project_id, self.known_run())
            if before.run.status != "queued" or before.execution_ids:
                raise HarnessError("RUNTIME_FAULT_DRIFT_QUEUE_NOT_OBSERVED")
            await _introduce_drift(self.clients.writer, self.assets, self.golden, self.directory)
            if self.golden.variant == "environment-drift":
                self.independent_status = "blocked"
                self.reasons = ("ENVIRONMENT_SNAPSHOT_DRIFT",)

    async def concurrent(self) -> None:
        self.operations, self.conflicts = await concurrent_launch(
            self.clients.writer,
            self.path,
            self.key,
        )
        self.run_id = self.operations[0].id

    async def response_loss(self) -> None:
        factory = self.clients.response_loss_factory
        if factory is None:
            raise HarnessError("RUNTIME_FAULT_LOSS_TRANSPORT_UNAVAILABLE")
        lossy = factory()
        try:
            await lossy.api.object("POST", self.path, idempotency_key=self.key)
        except httpx.ReadTimeout:
            self.dropped = lossy.witness.completed_and_dropped
        finally:
            await lossy.api.close()
        run = await recover_same_key(self.clients.writer, self.path, self.key)
        self.operations, self.run_id = (run,), run.id

    async def changed_payload(self) -> None:
        path = (
            f"/ci/projects/{self.assets.project_id}/workflows/{self.assets.workflow_id}/executions"
        )
        payload: JsonObject = {
            "environment_id": str(self.assets.environment_id),
            "version": self.assets.workflow_version,
            "runtime_variables": {"fault_variant": "original"},
            "runtime_headers": {},
        }
        first = await recover_same_key(self.clients.ci, path, self.key, payload=payload)
        self.execution_id = first.id
        repeated = await recover_same_key(self.clients.ci, path, self.key, payload=payload)
        changed = deepcopy(payload)
        changed["runtime_variables"] = {"fault_variant": "changed"}
        unexpected, conflict = await launch_same_key(
            self.clients.ci, path, self.key, payload=changed
        )
        self.operations = (first, repeated, *((unexpected,) if unexpected else ()))
        self.conflicts = (conflict,) if conflict else ()
        self.final = await wait_workflow(
            self.clients.reader,
            self.assets.project_id,
            first.id,
            datetime.now(UTC) + timedelta(seconds=60),
        )

    async def cancel_running(self) -> None:
        run = self.known_run()
        await wait_marker(
            self.clients.observer,
            self.assets.batch_key,
            self.assets.scenario_key,
            "first",
            datetime.now(UTC) + timedelta(seconds=30),
        )
        self.stage = "running"
        if self.golden.observer_status:
            try:
                self.child = await observer_process(
                    base_url=self.clients.base_url,
                    read_token=self.clients.read_token,
                    assets=self.assets,
                    run=run,
                    directory=self.directory,
                    crash=self.golden.variant == "crash-watchdog",
                )
            finally:
                self.final = await cancel_plan(
                    self.clients.writer,
                    self.clients.reader,
                    self.assets,
                    run,
                )
        elif self.golden.force:
            active = await read_plan(self.clients.reader, self.assets.project_id, run)
            if len(active.execution_ids) != 1:
                raise HarnessError("RUNTIME_FAULT_CANCEL_EXECUTION_AMBIGUOUS")
            await self.clients.writer.object(
                "POST",
                f"/projects/{self.assets.project_id}/workflow-executions/{active.execution_ids[0]}/cancel",
                {
                    "force": True,
                    "reason": "owned selftest runtime policy characterization",
                },
            )
        else:
            self.final = await cancel_plan(
                self.clients.writer,
                self.clients.reader,
                self.assets,
                run,
            )

    async def cleanup(self) -> None:
        try:
            await self._stop_known_execution()
            if self.final is None:
                self.cleanup_status = "needs_review"
                return
            await self._remove_namespace()
        except (HarnessError, httpx.HTTPError):
            self.cleanup_status = "failed"
            raise
        finally:
            write_json(
                self.directory / "cleanup.json",
                {
                    "status": self.cleanup_status,
                    "run_id": str(self.run_id) if self.run_id else None,
                    "execution_id": str(self.execution_id) if self.execution_id else None,
                    "namespace_delete_status": self.namespace_delete_status,
                    "management_read_admitted": self.management_read_admitted,
                },
            )

    async def _remove_namespace(self) -> None:
        self.cleanup_status = "needs_review"
        if self.fixture_nonce is None or self.fixture_digest is None:
            return
        receipt = self.directory / "cleanup.json"
        prior = self._prior_namespace_delete(receipt)
        if prior is not None:
            self.namespace_delete_status = prior
            if prior == "completed":
                self.cleanup_status = "completed"
            return
        try:
            condition = await read_namespace_condition(
                self.clients.observer,
                self.assets.batch_key,
                self.assets.scenario_key,
                nonce=self.fixture_nonce,
                fixture_digest=self.fixture_digest,
                wait_for_inactive=self.fixture_deadline is not None,
                deadline=self.fixture_deadline,
                reserve_request=self._reserve_management_read,
            )
        except HarnessError as error:
            if str(error).startswith("SELFTEST_HTTP_"):
                raise
            return
        if condition is None:
            self.cleanup_status = "completed"
            return
        self.namespace_delete_status = "unknown"
        write_json(
            receipt,
            {
                "status": "needs_review",
                "run_id": str(self.run_id) if self.run_id else None,
                "execution_id": str(self.execution_id) if self.execution_id else None,
                "namespace_delete_status": "unknown",
            },
        )
        try:
            await self.clients.observer.request(
                "DELETE",
                f"/selftest/batches/{self.assets.batch_key}/scenarios/{self.assets.scenario_key}",
                condition.body(),
            )
        except (HarnessError, httpx.HTTPError):
            return
        self.namespace_delete_status = "completed"
        self.cleanup_status = "completed"

    def _reserve_management_read(self) -> None:
        # Management GET admissions are separate from Mock side-effect budget.
        if self.management_read_admitted >= 12 or (
            self.fixture_deadline is not None and datetime.now(UTC) >= self.fixture_deadline
        ):
            raise HarnessError("RUNTIME_FAULT_CLEANUP_READ_BUDGET_EXHAUSTED")
        self.management_read_admitted += 1

    @staticmethod
    def _prior_namespace_delete(receipt: Path) -> Literal["unknown", "completed"] | None:
        if not receipt.exists():
            return None
        try:
            prior = read_json(receipt).get("namespace_delete_status")
        except (OSError, ValueError, HarnessError):
            return "unknown"
        if prior == "completed":
            return "completed"
        return "unknown" if prior == "unknown" else None

    async def _stop_known_execution(self) -> None:
        if self.final is not None:
            return
        if self.run_id is not None:
            self.final = await cancel_plan(
                self.clients.writer,
                self.clients.reader,
                self.assets,
                self.run_id,
            )
        elif self.execution_id is not None:
            await self.clients.writer.request(
                "POST",
                f"/projects/{self.assets.project_id}/workflow-executions/{self.execution_id}/cancel",
            )
            self.final = await wait_workflow(
                self.clients.reader,
                self.assets.project_id,
                self.execution_id,
                datetime.now(UTC) + timedelta(seconds=60),
            )


async def _introduce_drift(
    writer: PublicAPI, assets: Assets, golden: Golden, directory: Path
) -> None:
    root = f"/projects/{assets.project_id}"
    if golden.variant == "environment-drift":
        changed = await writer.object(
            "PATCH",
            root + f"/environments/{assets.environment_id}",
            {"variables": {"fault_environment_marker": "changed-v2"}},
        )
        if canonical_digest(changed) == assets.frozen_environment_digest:
            raise HarnessError("RUNTIME_FAULT_ENVIRONMENT_DRIFT_NOT_OBSERVED")
        write_json(
            directory / "environment-drift.json",
            {
                "before_digest": assets.frozen_environment_digest,
                "after_digest": canonical_digest(changed),
            },
        )
    else:
        changed = await _create(
            writer,
            directory,
            "api-v2",
            root + f"/apis/{assets.api_id}/versions",
            api_request(assets.batch_key, assets.scenario_key, second=True),
        )
        if changed["version"] != 2:
            raise HarnessError("RUNTIME_FAULT_API_V2_NOT_CREATED")


async def wait_workflow(
    reader: PublicAPI, project: UUID, execution: UUID, deadline: datetime
) -> Snapshot:
    for _ in range(300):
        detail = await reader.object(
            "GET", f"/ci/projects/{project}/workflow-executions/{execution}/evidence"
        )
        if detail["status"] in {"passed", "failed", "cancelled"}:
            if detail.get("bindings_complete") is not True or detail.get("truncated") is not False:
                raise HarnessError("RUNTIME_FAULT_EXECUTION_EVIDENCE_INCOMPLETE")
            return Snapshot.model_validate(
                {
                    "run": {"id": str(execution), "status": detail["status"]},
                    "execution_ids": [str(execution)],
                    "item_statuses": [detail["status"]],
                    "api_versions": [
                        item["api_version"] for item in objects_value(detail["api_bindings"])
                    ],
                    "snapshot_digests": [detail["snapshot_digest"]],
                }
            )
        if datetime.now(UTC) >= deadline:
            break
        await asyncio.sleep(0.2)
    raise HarnessError("RUNTIME_FAULT_EXECUTION_NOT_TERMINAL")


class RuntimeBuilds(Contract):
    candidate: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    fixture: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class FrozenRuntimeBatch(Contract):
    schema_version: Literal["flowtest-runtime-fault-batch-v1"] = "flowtest-runtime-fault-batch-v1"
    batch_key: str = Field(pattern=r"^runtime-[0-9a-f]{20}$")
    pack_digest: Sha256
    driver_digest: Sha256
    expected_variants: tuple[Golden, ...] = Field(min_length=15, max_length=15)
    builds: RuntimeBuilds
    source_digest: Sha256
    profile: Literal["full", "compact", "standalone"]
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    created_at: datetime
    deadline: datetime


class StandaloneGateWitness(Contract):
    scenario_key: str
    project_id: UUID
    workflow_id: UUID
    held_at: datetime
    completed_at: datetime
    at_hold: FixtureJournal
    settled: FixtureJournal
    executions: tuple[Snapshot, ...] = Field(min_length=4, max_length=4)
    slot_limit: Literal[4] = 4


class RuntimePackReport(Contract):
    pack_digest: Sha256
    expected_count: Literal[15] = 15
    completed_count: int = Field(ge=0, le=15)
    verdict: Literal["passed", "blocked"]
    exit_code: Literal[0, 2]
    run001_same_frozen_plan_distinct_runs: bool
    request_count: int = Field(ge=0)
    runtime_profile: Literal["full", "compact", "standalone"]
    standalone_gates: tuple[StandaloneGateWitness, ...] = Field(default=(), max_length=4)
    reason_codes: tuple[str, ...] = Field(default=(), max_length=10)
    budget: FixtureBudgetReceipt | None = None
    provenance: Literal["local_untrusted"] = "local_untrusted"
    complete_release_acceptance: Literal[False] = False
    scenarios: tuple[VariantReport, ...] = Field(min_length=15, max_length=15)


def initial_reports(pack: Pack) -> tuple[VariantReport, ...]:
    return tuple(
        VariantReport(
            scenario_id=item.scenario_id,
            variant=item.variant,
            status="incomplete",
            native_status=None,
            findings=(Finding(code="NOT_RUN", message="未执行"),),
            characterization_only=item.characterization_only,
        )
        for item in pack.variants
    )


def run001_relation(values: tuple[Observation, ...]) -> bool:
    selected = tuple(item for item in values if item.scenario_id == "ST-RUN-001")
    if len(selected) != 2:
        return False
    first, second = selected
    if first.final is None or second.final is None:
        return False
    return (
        first.final.run.id != second.final.run.id
        and first.final.run.target_digest is not None
        and first.final.run.target_digest == second.final.run.target_digest
        and first.final.run.trigger == "manual"
        and second.final.run.trigger == "ci"
    )


def driver_digest(directory: Path) -> Sha256:
    names = (
        "scripts/selftest/runtime_faults.py",
        "scripts/selftest/run_runtime_faults.py",
        "scripts/selftest/runtime_fault_observer.py",
        "scripts/selftest/standalone_runtime_gate.py",
        "selftest/packs/runtime-faults-v1/expectations.json",
    )
    return canonical_digest(
        {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in names}
    )
