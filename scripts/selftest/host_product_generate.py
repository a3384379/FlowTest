"""Callable H bridge: actual model-selected MCP calls, independent review, then pinned assets."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from mcp import ClientSession
from mcp.types import CallToolResult, Tool
from pydantic import TypeAdapter
from scripts.selftest.bootstrap import BootstrapResult
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.host_attempts import AttemptStore
from scripts.selftest.host_contracts import HostAttemptResult
from scripts.selftest.host_controller import HostController
from scripts.selftest.host_gateway import BoundedGateway
from scripts.selftest.host_launch import HostDeployment, HostReadiness, VerifiedGrant, readiness
from scripts.selftest.host_materialized import HostMaterialization, HostSelection
from scripts.selftest.host_product_bridge import publish_materialized, publish_pending
from scripts.selftest.host_prompts import (
    HostTask,
    SkillBundle,
    case_prompt,
    read_skill,
    workflow_prompt,
)
from scripts.selftest.host_quality import QualityAttempt, quality_report
from scripts.selftest.host_quality_history import QualityHistory
from scripts.selftest.host_runtime_config import HostRuntimeConfig, approved_runtime
from scripts.selftest.host_sources import reviewed_workflows
from scripts.selftest.io import HarnessError, JsonObject, PublicAPI, read_json, write_json
from scripts.selftest.local_stack import StackBinding
from scripts.selftest.run import _protocol

from app.core.self_tests import SelfTestPrincipal
from app.schemas.self_tests import AgentTaskResponse


class SessionUpstream:
    def __init__(self, session: ClientSession) -> None:
        self.session = session

    async def call_tool(self, name: str, arguments: JsonObject) -> CallToolResult:
        return await self.session.call_tool(name, arguments=arguments, read_timeout_seconds=45)


def _binding(
    task: AgentTaskResponse, config: HostRuntimeConfig, directory: Path
) -> tuple[VerifiedGrant, HostDeployment, HostTask]:
    grant, deployment, frozen_task = approved_runtime(config, directory)
    batch = task.batch
    if (
        batch is None
        or batch.generation_mode != "host_llm_mcp"
        or grant.authorization.project_id != task.project_id
        or grant.authorization.batch_key != batch.batch_key
        or grant.authorization.policy_digest != batch.policy_digest
        or grant.authorization.budget.maximum_tool_calls > task.budget.max_tool_calls
        or grant.authorization.budget.wall_seconds > task.budget.timeout_seconds
    ):
        raise HarnessError("HOST_PRODUCT_AUTHORIZATION_TASK_MISMATCH")
    server_before = (
        None if task.frozen_manifest is None else task.frozen_manifest.assisted_before_batch_id
    )
    signed_before = None if frozen_task.assisted is None else frozen_task.assisted.before_batch_id
    if server_before != signed_before:
        raise HarnessError("HOST_ASSISTED_FROZEN_BEFORE_BATCH_CHANGED")
    required = {(item.scenario_id, item.variant_key) for item in batch.required_scenario_set}
    if {(item.scenario_id, item.variant_key) for item in frozen_task.selections} != required:
        raise HarnessError("HOST_PRODUCT_REQUIRED_SET_CHANGED")
    return grant, deployment, frozen_task


async def _review_pause(
    controller: HostController, machine: PublicAPI, task: AgentTaskResponse, *, case: bool
) -> None:
    from scripts.selftest.host_sources import FrozenHostCase, FrozenHostSource

    sources = TypeAdapter(tuple[FrozenHostSource, ...]).validate_json(
        (controller.directory / "workflow-sources.json").read_bytes()
    )
    cases = (
        TypeAdapter(tuple[FrozenHostCase, ...]).validate_json(
            (controller.directory / "case-sources.json").read_bytes()
        )
        if case
        else ()
    )
    await publish_pending(
        machine,
        controller.reader,
        task,
        tool_count=len(controller.gateway.receipts),
        workflows=sources,
        cases=cases,
    )


async def generate_task(
    machine: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    *,
    task: AgentTaskResponse,
    stack: StackBinding,
    boot: BootstrapResult,
    directory: Path,
    config: HostRuntimeConfig,
    resume_known_review: bool = False,
    quality_root: Path | None = None,
    quality_verifier: SelfTestPrincipal | None = None,
) -> HostMaterialization | HostReadiness:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    grant, deployment, frozen_task = _binding(task, config, directory)
    write_json(directory / "host-quality.json", quality_report(frozen_task.quality_taskset, ()))
    status = readiness(grant, deployment)
    if status.status != "ready":
        write_json(
            directory / "host-not-run.json",
            {"status": status.status, "reason_codes": list(status.reason_codes)},
        )
        return status
    if frozen_task.assisted is not None:
        return await _generate_assisted(
            machine,
            reader,
            observer,
            task=task,
            frozen_task=frozen_task,
            grant=grant,
            config=config,
            directory=directory,
            quality_root=quality_root,
            quality_verifier=quality_verifier,
        )
    store = AttemptStore(directory / "attempts")
    prior = store.read(grant) if store.path(grant.authorization.authorization_id).exists() else None
    if prior is not None and (
        not resume_known_review
        or prior.state not in {"waiting_workflow_review", "waiting_case_review"}
    ):
        raise HarnessError("HOST_ATTEMPT_REPLAY_OR_UNKNOWN_STATE")
    attempt = prior.attempt_id if prior else uuid4()
    if quality_root is None or quality_verifier is None:
        raise HarnessError("HOST_QUALITY_HISTORY_CONFIGURATION_REQUIRED")
    history = QualityHistory.for_task(
        quality_root, grant, frozen_task.quality_taskset, quality_verifier
    )
    history.reserve(grant, attempt)
    write_json(directory / "host-quality.json", history.report())
    skill = read_skill(config.skill_directory)
    batch = task.batch
    if batch is None:
        raise HarnessError("HOST_PRODUCT_BATCH_REQUIRED")
    async with _protocol(
        stack, "stdio", boot.credentials.mcp_token, batch.batch_key, directory / "upstream"
    ) as client:
        catalog = TypeAdapter(tuple[Tool, ...]).validate_python(
            read_json(directory / "upstream" / "mcp-catalog.json")["tools"]
        )
        gateway = BoundedGateway(
            authorization=grant.authorization,
            attempt_id=attempt,
            phase="workflow",
            catalog=catalog,
            upstream=SessionUpstream(client.session),
            directory=directory,
            deadline=batch.deadline,
        )
        controller = HostController(
            grant=grant,
            deployment=deployment,
            store=store,
            gateway=gateway,
            reader=reader,
            directory=directory,
        )
        try:
            await _run_model_phases(
                controller, machine, task, frozen_task, skill, resume_known_review=prior is not None
            )
        finally:
            _record_attempt_quality(controller, frozen_task, history)
        protocol = client.session.protocol_version
        if protocol is None:
            raise HarnessError("HOST_MCP_PROTOCOL_VERSION_MISSING")
        materialized = await _wait_materialized(controller, frozen_task.selections, protocol)
    await _prepare_product(machine, observer, task, materialized, directory)
    return materialized


async def _run_model_phases(
    controller: HostController,
    machine: PublicAPI,
    task: AgentTaskResponse,
    frozen_task: HostTask,
    skill: SkillBundle,
    *,
    resume_known_review: bool,
) -> None:
    from scripts.selftest.host_sources import FrozenHostSource

    if resume_known_review:
        controller.gateway.restore_receipts()
        record = controller.store.read(controller.grant)
        if record.state == "waiting_case_review":
            sources = TypeAdapter(tuple[FrozenHostSource, ...]).validate_json(
                (controller.directory / "workflow-sources.json").read_bytes()
            )
            bindings = await reviewed_workflows(
                controller.reader, sources, reviewer_ids=controller.grant.authorization.reviewer_ids
            )
            controller.gateway.begin_case_phase(bindings)
            return
    else:
        result = await controller.start(
            attempt_id=controller.gateway.attempt_id,
            prompt=workflow_prompt(frozen_task, skill, controller.grant),
        )
        _waiting(result)
    await _review_pause(controller, machine, task, case=False)
    await _wait_workflows(controller)
    sources = TypeAdapter(tuple[FrozenHostSource, ...]).validate_json(
        (controller.directory / "workflow-sources.json").read_bytes()
    )
    bindings = await reviewed_workflows(
        controller.reader, sources, reviewer_ids=controller.grant.authorization.reviewer_ids
    )
    result = await controller.resume_after_workflow_review(
        prompt=case_prompt(frozen_task, skill, controller.grant, sources, bindings)
    )
    _waiting(result)
    await _review_pause(controller, machine, task, case=True)


def _record_attempt_quality(
    controller: HostController, task: HostTask, history: QualityHistory
) -> None:
    if not any(
        (controller.directory / phase / "process.json").exists() for phase in ("workflow", "case")
    ):
        return
    record = controller.store.read(controller.grant)
    attempts = tuple(
        QualityAttempt(
            task_id=item.scenario_id,
            variant_key=item.variant_key,
            attempt_id=record.attempt_id,
            ordinal=1,
            review_mode=controller.grant.authorization.review_mode,
            evidence_digest=canonical_digest(record.model_dump(mode="json")),
            source_complete=False if record.state == "error" else None,
        )
        for item in task.selections
    )
    report = (
        history.finish(controller.grant, record.attempt_id, attempts, failed=True)
        if record.state == "error"
        else history.report()
    )
    write_json(controller.directory / "host-quality.json", report)


def _waiting(result: HostAttemptResult | HostReadiness) -> None:
    if isinstance(result, HostReadiness):
        raise HarnessError(result.reason_codes[0])
    if result.status != "waiting_for_review":
        raise HarnessError(
            result.reason_codes[0] if result.reason_codes else "HOST_GENERATION_NOT_READY"
        )


async def _wait_workflows(controller: HostController) -> None:
    from scripts.selftest.host_sources import FrozenHostSource

    sources = TypeAdapter(tuple[FrozenHostSource, ...]).validate_json(
        (controller.directory / "workflow-sources.json").read_bytes()
    )
    while datetime.now(UTC) < controller.gateway.deadline:
        try:
            await reviewed_workflows(
                controller.reader, sources, reviewer_ids=controller.grant.authorization.reviewer_ids
            )
            return
        except HarnessError as error:
            if str(error) != "HOST_WAITING_FOR_HUMAN_REVIEW":
                raise
        await asyncio.sleep(1)
    raise HarnessError("HOST_DEADLINE_EXCEEDED")


async def _wait_materialized(
    controller: HostController, selections: tuple[HostSelection, ...], protocol: str
) -> HostMaterialization:
    while datetime.now(UTC) < controller.gateway.deadline:
        try:
            result = await controller.materialize_after_case_review(
                selections=selections, transport="stdio", protocol_version=protocol
            )
            if isinstance(result, HostReadiness):
                raise HarnessError(result.reason_codes[0])
            return result
        except HarnessError as error:
            if str(error) != "HOST_WAITING_FOR_CASE_REVIEW":
                raise
        await asyncio.sleep(1)
    raise HarnessError("HOST_DEADLINE_EXCEEDED")


async def _prepare_product(
    machine: PublicAPI,
    observer: PublicAPI,
    task: AgentTaskResponse,
    materialized: HostMaterialization,
    directory: Path,
) -> None:
    from scripts.selftest.host_product_prepare import (
        configure_fixtures,
        freeze_product_expectations,
    )

    scope, epoch = await configure_fixtures(observer, task, materialized)
    ready = await publish_materialized(
        machine, task, materialized=materialized, directory=directory
    )
    freeze_product_expectations(task, ready, materialized, scope, epoch, directory)


async def _generate_assisted(
    machine: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    *,
    task: AgentTaskResponse,
    frozen_task: HostTask,
    grant: VerifiedGrant,
    config: HostRuntimeConfig,
    directory: Path,
    quality_root: Path | None,
    quality_verifier: SelfTestPrincipal | None,
) -> HostMaterialization:
    from scripts.selftest.host_assisted import materialize_assisted

    if quality_root is None or quality_verifier is None:
        raise HarnessError("HOST_QUALITY_HISTORY_CONFIGURATION_REQUIRED")
    history = QualityHistory.for_task(
        quality_root, grant, frozen_task.quality_taskset, quality_verifier
    )
    attempt_id = uuid4()
    history.reserve(grant, attempt_id, assisted=True)
    write_json(directory / "host-quality.json", history.report())
    try:
        result = await materialize_assisted(
            reader,
            task=task,
            frozen_task=frozen_task,
            grant=grant,
            config=config,
            directory=directory,
            attempt_id=attempt_id,
        )
        await _prepare_product(machine, observer, task, result, directory)
        return result
    except (HarnessError, OSError, ValueError, httpx.HTTPError, asyncio.CancelledError):
        records = tuple(
            QualityAttempt(
                task_id=item.scenario_id,
                variant_key=item.variant_key,
                attempt_id=attempt_id,
                ordinal=1,
                evidence_digest=grant.digest,
                review_mode=grant.authorization.review_mode,
                generation_kind="assisted",
                source_complete=False,
            )
            for item in frozen_task.selections
        )
        write_json(
            directory / "host-quality.json", history.finish(grant, attempt_id, records, failed=True)
        )
        raise
