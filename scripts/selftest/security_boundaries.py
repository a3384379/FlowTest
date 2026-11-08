"""Five real security probes in fresh owned projects, with mandatory target disposal."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
from scripts.selftest.boundary_pack import load_boundary_pack
from scripts.selftest.boundary_reporting import write_boundary_junit
from scripts.selftest.contracts import TargetDisposalReceipt
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.local_stack import StackBinding, _verify_removed
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.security_boundary_checks import manual_report, sentinel_exports, trust_denials
from scripts.selftest.security_boundary_contracts import (
    SECURITY_SCENARIOS,
    BoundaryEvidence,
    BoundaryManifest,
    BoundaryResult,
)
from scripts.selftest.security_boundary_setup import security_actors
from scripts.selftest.verify_security_boundaries import verify_security_boundaries


async def execute_security_boundaries(
    *,
    binding: StackBinding,
    bootstrap_token: str,
    batch_key: str,
    output_dir: Path,
    deadline: datetime,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BoundaryResult:
    remaining = (deadline - datetime.now(UTC)).total_seconds() if deadline.tzinfo else -1
    if not 0 < remaining <= 600 or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,55}", batch_key):
        raise HarnessError("SELFTEST_SECURITY_BATCH_OR_DEADLINE_INVALID")
    if (output_dir / "manifest.json").exists():
        raise HarnessError("SELFTEST_SECURITY_NEW_ATTEMPT_REQUIRED")
    manifest = BoundaryManifest(
        pack_digest=load_boundary_pack("security-boundaries-v1", SECURITY_SCENARIOS).digest,
        project_name=binding.project_name,
        nonce=binding.nonce,
        profile=binding.runtime_profile,
        source_digest=binding.source_digest,
        target_container_id=binding.target_container_id,
        target_image=binding.candidate_image_digest,
        target_volume=binding.target_volume,
        created_at=datetime.now(UTC),
        deadline=deadline,
    )
    write_json(output_dir / "manifest.json", manifest)
    budget = ProtocolHttpBudget(
        output_dir / "private-budget.sqlite3", binding.nonce, deadline.timestamp()
    )
    async with security_actors(
        binding, bootstrap_token, batch_key, budget, deadline, transport=transport
    ) as actors:
        owner = await trust_denials(actors, editor=False, deadline=deadline)
        editor = await trust_denials(actors, editor=True, deadline=deadline)
        report = await manual_report(actors)
        write_only, redaction = await sentinel_exports(actors, batch_key)
        admitted, rejected = budget.counts()
        evidence = BoundaryEvidence(
            manifest_digest=manifest.digest,
            identities=actors.identity,
            scenarios=(owner, editor, report, write_only, redaction),
            http_attempts=admitted,
            rejected_attempts=rejected,
            cleanup_status="pending",
            collected_at=datetime.now(UTC),
        )
    provisional = BoundaryResult(
        manifest=manifest, evidence=evidence, batch_verdict="blocked", exit_code=2, reason_codes=()
    )
    return _persist(provisional, output_dir)


def _persist(result: BoundaryResult, directory: Path) -> BoundaryResult:
    reasons = verify_security_boundaries(result)
    result = result.model_copy(
        update={
            "batch_verdict": "blocked" if reasons else "passed",
            "exit_code": 2 if reasons else 0,
            "reason_codes": reasons,
        }
    )
    write_json(directory / "evidence.json", result.evidence)
    write_json(directory / "result.json", result)
    write_boundary_junit(
        directory,
        tuple(item.scenario_id for item in result.evidence.scenarios),
        reasons,
        purpose=result.manifest.purpose,
    )

    return result


def finalize_security_boundaries(
    result: BoundaryResult,
    *,
    binding: StackBinding,
    stack_directory: Path,
    output_dir: Path,
) -> BoundaryResult:
    stored = StackBinding.model_validate(read_json(stack_directory / "stack.json"))
    ownership = read_json(stack_directory / "ownership.json")
    cleanup = read_json(stack_directory / "cleanup.json")
    manifest = result.manifest
    if (
        stored != binding
        or ownership != {"project_name": binding.project_name, "nonce": binding.nonce}
        or cleanup != {"project_name": binding.project_name, "status": "completed"}
        or manifest.project_name != binding.project_name
        or manifest.nonce != binding.nonce
        or manifest.target_container_id != binding.target_container_id
        or manifest.target_image != binding.candidate_image_digest
        or manifest.target_volume != binding.target_volume
    ):
        raise HarnessError("SELFTEST_SECURITY_DISPOSAL_IDENTITY_MISMATCH")
    _verify_removed(binding.project_name)
    if result.evidence.cleanup_status == "completed":
        return _persist(result, output_dir)
    before = output_dir / "evidence.pre-disposal.json"
    if not before.exists():
        write_json(before, result.evidence)
    receipt = TargetDisposalReceipt(
        project_name=binding.project_name,
        target_container_id=binding.target_container_id,
        target_volume=binding.target_volume,
        target_image=binding.candidate_image_digest,
        binding_nonce=binding.nonce,
        removed_at=datetime.now(UTC),
        containers_absent=True,
        volumes_absent=True,
        networks_absent=True,
    )
    evidence = result.evidence.model_copy(
        update={"cleanup_status": "completed", "target_disposal": receipt}
    )
    return _persist(result.model_copy(update={"evidence": evidence}), output_dir)
