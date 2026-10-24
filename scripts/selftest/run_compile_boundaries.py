"""Pure compiler deployment probe on the owned product wave, with no target execution."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.selftest.bootstrap import bootstrap
from scripts.selftest.compile_boundary_collect import actors, collect
from scripts.selftest.compile_boundary_contracts import (
    CompileBoundaryEvidence,
    CompileBoundaryManifest,
    CompileBoundaryReport,
)
from scripts.selftest.compile_boundary_verify import keys
from scripts.selftest.contracts import TargetDisposalReceipt, canonical_digest
from scripts.selftest.draft_boundary_collect import collect_drafts
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.local_stack import ROOT, StackBinding, _verify_removed, verify_binding
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.product_agent_client import ProductAgentConfig
from scripts.selftest.product_boundary_common import ProductWorld
from scripts.selftest.product_boundary_contracts import ProductBoundaryManifest
from scripts.selftest.run import _verifier_digest
from scripts.selftest.security_boundary_http import BoundaryAPI


def observe(output: Path) -> CompileBoundaryReport:
    child = subprocess.run(  # noqa: S603 -- fixed credential-free O module
        [sys.executable, "-m", "scripts.selftest.compile_boundary_verify", "--output", str(output)],
        cwd=ROOT,
        timeout=30,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT)},
        capture_output=True,
        check=False,
    )
    if child.returncode not in {0, 2}:
        path = output / "private-o-failure.log"
        path.write_bytes(child.stderr)
        path.chmod(0o600)
        raise HarnessError("COMPILE_BOUNDARY_O_FAILED")
    report = CompileBoundaryReport.model_validate(read_json(output / "verification.json"))
    if report.exit_code != child.returncode:
        raise HarnessError("COMPILE_BOUNDARY_O_RECEIPT_CHANGED")
    return report


async def run(directory: Path, product: Path, output: Path) -> CompileBoundaryReport:
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    stack = StackBinding.model_validate(read_json(directory / "stack.json"))
    verify_binding(stack, directory)
    state = product / "private-state"
    config = ProductAgentConfig.model_validate(read_json(state / "agent-config.json"))
    boot = await bootstrap(stack, directory, credential_role="observer")
    config.verify(stack, boot)
    started = datetime.now(UTC)
    deadline = started + timedelta(seconds=600)
    budget = ProtocolHttpBudget(
        output / "private-budget.sqlite3", stack.nonce, deadline.timestamp()
    )
    organization = str(boot.installation.organization_id)
    world = ProductWorld(
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
    try:
        issued = await actors(world)
        parent = ProductBoundaryManifest.model_validate(read_json(product / "manifest.json"))
        frozen = CompileBoundaryManifest(
            product=parent,
            project_id=config.project_id,
            foreign_project_id=issued.foreign,
            expected_keys=keys(),
            verifier_digest=_verifier_digest(stack.runtime_profile),
            created_at=started,
            deadline=deadline,
            disposal=parent.disposal,
        )
        write_json(output / "manifest.json", frozen)
        observations = await collect(world, issued, output)
        drafts = await collect_drafts(world, issued, observations, output)
        http, rejected = budget.counts()
        tool, rejected_tools = budget.tool_counts()
        write_json(
            output / "evidence.json",
            CompileBoundaryEvidence(
                manifest_digest=canonical_digest(frozen.model_dump(mode="json")),
                observations=observations,
                drafts=drafts,
                http_attempts=http,
                tool_attempts=tool,
                rejected_attempts=rejected + rejected_tools,
                collected_at=datetime.now(UTC),
            ),
        )
        return observe(output)
    finally:
        await world.close()


def finalize(directory: Path, output: Path) -> CompileBoundaryReport:
    stack = StackBinding.model_validate(read_json(directory / "stack.json"))
    frozen = CompileBoundaryManifest.model_validate(read_json(output / "manifest.json"))
    evidence = CompileBoundaryEvidence.model_validate(read_json(output / "evidence.json"))
    if (
        read_json(directory / "ownership.json")
        != {"project_name": stack.project_name, "nonce": stack.nonce}
        or read_json(directory / "cleanup.json")
        != {"project_name": stack.project_name, "status": "completed"}
        or frozen.verifier_digest != _verifier_digest(stack.runtime_profile)
        or frozen.disposal.target_container_id != stack.runner_container_id
        or frozen.disposal.binding_nonce != stack.nonce
    ):
        raise HarnessError("COMPILE_BOUNDARY_FINAL_IDENTITY_CHANGED")
    _verify_removed(stack.project_name)
    disposal = TargetDisposalReceipt(
        **frozen.disposal.model_dump(),
        removed_at=datetime.now(UTC),
        containers_absent=True,
        volumes_absent=True,
        networks_absent=True,
    )
    if not (output / "evidence.pre-disposal.json").exists():
        write_json(output / "evidence.pre-disposal.json", evidence)
    write_json(output / "evidence.json", evidence.model_copy(update={"disposal": disposal}))
    return observe(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="真实SDK纯编译; 无模型或业务执行")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--finalize-disposable", action="store_true")
    args = parser.parse_args()
    report = (
        finalize(args.directory, args.output)
        if args.finalize_disposable
        else asyncio.run(run(args.directory, args.product, args.output))
    )
    print(json.dumps(report.model_dump(mode="json")))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
