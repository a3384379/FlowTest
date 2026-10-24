"""Owned public-API product journeys using ordinary users and separate real H/O processes."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from scripts.selftest.bootstrap import bootstrap
from scripts.selftest.io import HarnessError, JsonObject, object_value, read_json, write_json
from scripts.selftest.local_stack import ROOT, StackBinding
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.product_agent_client import (
    ProductAgentConfig,
    agent_api,
    keep_lease,
    lease_body,
)
from scripts.selftest.product_setup import setup
from scripts.selftest.security_boundary_http import BoundaryAPI

from app.schemas.self_tests import (
    AgentTaskResponse,
    BatchResponse,
    InstallationResponse,
    VerificationReceipt,
    VerificationScenario,
)


@dataclass(frozen=True, repr=False)
class ProductWorld:
    stack: StackBinding
    directory: Path
    state: Path
    config: ProductAgentConfig
    user: BoundaryAPI
    viewer: BoundaryAPI
    machine: BoundaryAPI
    budget: ProtocolHttpBudget
    deadline: datetime

    @property
    def root(self) -> str:
        return f"/projects/{self.config.project_id}/self-tests"

    async def close(self) -> None:
        await asyncio.gather(self.user.close(), self.viewer.close(), self.machine.close())


async def prepare_world(directory: Path, state: Path, deadline: datetime) -> ProductWorld:
    config = await setup(directory, state)
    stack = StackBinding.model_validate(read_json(directory / "stack.json"))
    boot = await bootstrap(stack, directory, credential_role="observer")
    budget = ProtocolHttpBudget(state / "private-budget.sqlite3", stack.nonce, deadline.timestamp())
    organization = str(boot.installation.organization_id)
    return ProductWorld(
        stack,
        directory,
        state,
        config,
        BoundaryAPI(
            stack.runner_url, budget, deadline, boot.credentials.reviewer_token, organization
        ),
        BoundaryAPI(
            stack.runner_url, budget, deadline, boot.credentials.capture_viewer_token, organization
        ),
        BoundaryAPI(stack.runner_url, budget, deadline, config.observer.token(), organization),
        budget,
        deadline,
    )


def _agent_arguments(world: ProductWorld, role: str, claimed: UUID | None) -> list[str]:
    if claimed is not None:
        if role != "observer":
            raise HarnessError("PRODUCT_BOUNDARY_CLAIMED_OBSERVER_REQUIRED")
        return [
            sys.executable,
            "-m",
            "scripts.selftest.product_boundary_common",
            "--directory",
            str(world.directory),
            "--state",
            str(world.state),
            "--claimed",
            str(claimed),
        ]
    return [
        sys.executable,
        "-m",
        "scripts.selftest.product_agent",
        "--directory",
        str(world.directory),
        "--state-directory",
        str(world.state / "tasks"),
        "--config",
        str(world.state / "agent-config.json"),
        "--role",
        role,
        "--review-mode",
        "ci_fixture",
        "--once",
        "--timeout-seconds",
        "600",
    ]


async def agent(world: ProductWorld, role: str, *, claimed: UUID | None = None) -> None:
    index = len(tuple(world.state.glob("private-" + role + "-*.log")))
    log = world.state / f"private-{role}-{index}.log"
    descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        child = await asyncio.create_subprocess_exec(
            *_agent_arguments(world, role, claimed),
            cwd=ROOT,
            stdout=output,
            stderr=output,
        )
    try:
        remaining = max(1.0, (world.deadline - datetime.now(world.deadline.tzinfo)).total_seconds())
        status = await asyncio.wait_for(child.wait(), remaining)
    except (TimeoutError, asyncio.CancelledError):
        if child.returncode is None:
            child.terminate()
        try:
            await asyncio.wait_for(child.wait(), 5)
        except TimeoutError:
            child.kill()
            await child.wait()
        raise
    if status:
        raise HarnessError("PRODUCT_BOUNDARY_AGENT_FAILED:" + role)


async def install(
    world: ProductWorld, template: str, key: str
) -> tuple[InstallationResponse, JsonObject]:
    request: JsonObject = {"template_id": template, "binding_id": str(world.config.binding.id)}
    preview = await world.user.object("POST", world.root + "/installations/preview", request)
    if preview["can_apply"] is not True:
        raise HarnessError("PRODUCT_BOUNDARY_PREVIEW_NOT_READY")
    payload = {
        **request,
        "preview_fingerprint": preview["fingerprint"],
        "preview_expires_at": preview["expires_at"],
    }
    installed = await world.user.object(
        "POST", world.root + "/installations", payload, idempotency_key=key
    )
    write_json(world.state / f"private-install-request-{template}.json", payload)
    await agent(world, "harness")
    ready = InstallationResponse.model_validate(
        await world.user.object(
            "GET",
            world.root + "/installations/" + str(installed["id"]),
        )
    )
    if ready.status != "ready":
        raise HarnessError("PRODUCT_BOUNDARY_INSTALLATION_NOT_READY")
    return ready, payload


async def fixed_run(
    world: ProductWorld, installation: InstallationResponse, key: str
) -> BatchResponse:
    batch = BatchResponse.model_validate(
        await world.user.object(
            "POST",
            world.root + f"/installations/{installation.id}/runs",
            {"budget": {"timeout_seconds": 600, "max_requests": 500, "max_tool_calls": 100}},
            idempotency_key=key,
        )
    )
    await agent(world, "harness")
    await agent(world, "observer")
    result = BatchResponse.model_validate(
        await world.user.object("GET", world.root + f"/runs/{batch.id}")
    )
    if (
        result.phase,
        result.verdict,
        result.sealed_verdict,
        result.evidence_integrity,
        result.cleanup_status,
    ) != (
        "completed",
        "passed",
        "passed",
        "complete",
        "completed",
    ):
        raise HarnessError("PRODUCT_BOUNDARY_NATIVE_BATCH_NOT_PASSED")
    return result


def verification_receipt(world: ProductWorld, batch: BatchResponse) -> VerificationReceipt:
    from scripts.selftest.contracts import VerificationReport

    directory = world.state / "tasks" / str(batch.id)
    task = AgentTaskResponse.model_validate(read_json(directory / "private-lease.json"))
    report = VerificationReport.model_validate(read_json(directory / "verification.json"))
    return VerificationReceipt(
        **lease_body(task).model_dump(),
        manifest_digest=batch.manifest_digest,
        resource_digest=batch.resource_digest,
        policy_digest=batch.policy_digest,
        builds=batch.builds,
        batch_verdict=report.batch_verdict,
        evidence_integrity=report.evidence_integrity,
        batch_reason_codes=tuple(row.code for row in report.findings),
        cleanup_status=batch.cleanup_status,
        scenarios=tuple(
            VerificationScenario(
                scenario_id=row.scenario_id,
                variant_key=row.variant_key,
                observed_status=row.observed_status,
                verification_status=row.verification_status,
                reason_codes=tuple(item.code for item in row.findings),
                evidence_refs=batch.artifacts[1:3],
            )
            for row in report.scenarios
        ),
        artifacts=batch.artifacts,
    )


async def replay_receipt(
    world: ProductWorld, batch: BatchResponse, receipt: VerificationReceipt
) -> JsonObject:
    return await world.machine.object(
        "POST",
        f"/ci/projects/{batch.project_id}/self-test-runs/{batch.id}/verification",
        object_value(receipt.model_dump(mode="json")),
    )


async def observe_claimed(directory: Path, state: Path, identifier: UUID) -> None:
    from scripts.selftest.io import PublicAPI
    from scripts.selftest.product_agent import _observe, load_runtime
    from scripts.selftest.product_evidence import TaskEvidenceReader

    stack = StackBinding.model_validate(read_json(directory / "stack.json"))
    config_path = state / "agent-config.json"
    config = ProductAgentConfig.model_validate(read_json(config_path))
    runtime, boot = load_runtime(config_path, "observer", stack)
    config.verify(stack, boot)
    task = AgentTaskResponse.model_validate(
        read_json(state / "tasks" / str(identifier) / "private-lease.json")
    )
    machine = agent_api(stack, config.observer)
    reader = TaskEvidenceReader(stack.runner_url, config.observer.token(), task)
    writer = PublicAPI(stack.runner_url, "")
    observer = PublicAPI(stack.observer_url, runtime.fixture_management_token, api_prefix="")
    try:
        async with keep_lease(machine, task):
            await _observe(
                machine,
                writer,
                reader,
                observer,
                task=task,
                stack=stack,
                boot=boot,
                directory=state / "tasks" / str(identifier),
                host_config=None,
            )
    finally:
        await asyncio.gather(machine.close(), reader.close(), writer.close(), observer.close())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="以已授权独立O租约完成采证; 不调用模型")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--claimed", type=UUID, required=True)
    args = parser.parse_args()
    asyncio.run(observe_claimed(args.directory, args.state, args.claimed))
