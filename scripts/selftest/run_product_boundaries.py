"""Real public product lifecycle with separate H/O; no model or trusted CI promotion."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from xml.etree.ElementTree import Element, parse, tostring

from scripts.selftest.contracts import (
    BatchEvidence,
    BatchManifest,
    Builds,
    RequiredDisposal,
    TargetDisposalReceipt,
    canonical_digest,
)
from scripts.selftest.io import HarnessError, object_value, read_json, write_json
from scripts.selftest.local_stack import ROOT, StackBinding, _verify_removed, verify_binding
from scripts.selftest.product_boundary_actions import (
    batch_snapshot,
    begin_batch,
    installation_checks,
    overlapping_batches,
    response_receipt,
    seal_checks,
)
from scripts.selftest.product_boundary_common import (
    ProductWorld,
    agent,
    prepare_world,
    verification_receipt,
)
from scripts.selftest.product_boundary_contracts import (
    ProductBoundaryEvidence,
    ProductBoundaryManifest,
    ProductBoundaryObservation,
    ProductBoundaryReport,
    ProductNativeProof,
)
from scripts.selftest.product_boundary_preflight import (
    installation_refusals,
    recursion_and_isolation,
)
from scripts.selftest.product_boundary_retention import (
    cleanup_proof,
    namespace_statuses,
    retention_checks,
)
from scripts.selftest.product_boundary_scopes import claim_and_check_scope, read_scope_checks
from scripts.selftest.product_boundary_target import configure_target
from scripts.selftest.product_boundary_verify import load_pack
from scripts.selftest.run import _verifier_digest
from scripts.selftest.security_boundary_http import BoundaryAPI

from app.schemas.self_tests import BatchResponse, InstallationResponse


def observe(output: Path) -> ProductBoundaryReport:
    result = subprocess.run(  # noqa: S603 -- fixed O module with authority-free environment
        [sys.executable, "-m", "scripts.selftest.product_boundary_verify", "--output", str(output)],
        cwd=ROOT,
        timeout=45,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT)},
        capture_output=True,
        check=False,
    )
    if result.returncode not in {0, 2}:
        failure = output / ("private-o-failure-" + uuid4().hex + ".log")
        failure.write_bytes(result.stderr)
        failure.chmod(0o600)
        raise HarnessError("PRODUCT_BOUNDARY_OBSERVER_PROCESS_FAILED")
    report = ProductBoundaryReport.model_validate(read_json(output / "verification.json"))
    if report.exit_code != result.returncode:
        raise HarnessError("PRODUCT_BOUNDARY_OBSERVER_EXIT_CHANGED")
    return report


def manifest(world: ProductWorld, started: datetime) -> ProductBoundaryManifest:
    pack = load_pack()
    return ProductBoundaryManifest(
        pack_digest=canonical_digest(pack.model_dump(mode="json")),
        source_digest=world.stack.source_digest,
        builds=Builds.model_validate(world.config.binding.builds.model_dump()),
        profile=world.stack.runtime_profile,
        expected_keys=tuple(row.key for row in pack.scenarios),
        project_id=world.config.project_id,
        project_name=world.stack.project_name,
        ownership_nonce=world.stack.nonce,
        created_at=started,
        deadline=world.deadline,
        disposal=RequiredDisposal(
            project_name=world.stack.project_name,
            target_container_id=world.stack.runner_container_id,
            target_volume=world.stack.runner_volume,
            target_image=world.stack.candidate_image_digest,
            binding_nonce=world.stack.nonce,
        ),
    )


async def native_batches(
    world: ProductWorld, installation: InstallationResponse, output: Path
) -> tuple[tuple[BatchResponse, BatchResponse], tuple[ProductBoundaryObservation, ...]]:
    original = await overlapping_batches(world, installation)
    refreshed = [
        BatchResponse.model_validate(await world.user.object("GET", world.root + f"/runs/{row.id}"))
        for row in original
    ]
    first, second = refreshed
    _, scope = await claim_and_check_scope(world, second, first)
    await agent(world, "observer")
    await agent(world, "observer", claimed=second.id)
    batches = [
        BatchResponse.model_validate(await world.user.object("GET", world.root + f"/runs/{row.id}"))
        for row in original
    ]
    snapshots = tuple([await batch_snapshot(world, row.id) for row in batches])
    suite = Element("testsuites")
    for batch in batches:
        source = world.state / "tasks" / str(batch.id) / "execution.junit.xml"
        suite.append(parse(source).getroot())  # noqa: S314 -- own independent O-generated fixed XML
    (output / "execution.junit.xml").write_bytes(
        tostring(suite, encoding="utf-8", xml_declaration=True)
    )
    rows = tuple(
        ProductBoundaryObservation(key=key, batches=snapshots, observed_at=datetime.now(UTC))
        for key in ("new_run", "two_batch_isolation")
    )
    return (batches[0], batches[1]), (*rows, scope)


async def cancelled(
    world: ProductWorld, installation: InstallationResponse
) -> ProductBoundaryObservation:
    batch = await begin_batch(world, installation, "product-boundary-cancel")
    current = BatchResponse.model_validate(
        await world.user.object("POST", world.root + f"/runs/{batch.id}/cancel")
    )
    return ProductBoundaryObservation(
        key="cancel_cleanup",
        batches=(await batch_snapshot(world, current.id),),
        namespace_statuses=await namespace_statuses(world, current),
        observed_at=datetime.now(UTC),
    )


async def expired(
    world: ProductWorld, batch: BatchResponse, sealed: BatchResponse
) -> ProductBoundaryObservation:
    receipt = verification_receipt(world, sealed)
    await asyncio.sleep(max(0, (batch.deadline - datetime.now(UTC)).total_seconds()) + 0.05)
    path = f"/ci/projects/{batch.project_id}/self-test-runs/{batch.id}/verification"
    response = await world.machine.probe(
        "POST", path, object_value(receipt.model_dump(mode="json"))
    )
    api = BoundaryAPI(
        world.stack.runner_url, world.budget, world.deadline, world.config.harness.token()
    )
    try:
        watchdog = await api.probe(
            "POST",
            f"/agent/projects/{batch.project_id}/self-tests/runs/{batch.id}/watchdog",
            {
                "manifest_digest": batch.manifest_digest,
                "binding_fingerprint": canonical_digest(
                    world.config.binding.model_dump(mode="json")
                ),
            },
        )
    finally:
        await api.close()
    return ProductBoundaryObservation(
        key="nonce_expiry",
        requests=(
            response_receipt("expired_receipt", response),
            response_receipt("watchdog", watchdog),
        ),
        batches=(await batch_snapshot(world, batch.id),),
        namespace_statuses=await namespace_statuses(world, batch),
        observed_at=datetime.now(UTC),
    )


def save(
    world: ProductWorld,
    frozen: ProductBoundaryManifest,
    output: Path,
    observations: tuple[ProductBoundaryObservation, ...],
    batches: tuple[BatchResponse, ...],
) -> None:
    order = {key: index for index, key in enumerate(frozen.expected_keys)}
    admitted, rejected = world.budget.counts()
    native = tuple(
        ProductNativeProof(
            manifest=BatchManifest.model_validate(
                read_json(world.state / "tasks" / str(row.id) / "manifest.json")
            ),
            evidence=BatchEvidence.model_validate(
                read_json(world.state / "tasks" / str(row.id) / "evidence.json")
            ),
        )
        for row in batches
    )
    write_json(
        output / "evidence.json",
        ProductBoundaryEvidence(
            manifest_digest=canonical_digest(frozen.model_dump(mode="json")),
            native=native,
            observations=tuple(sorted(observations, key=lambda row: order[row.key])),
            http_attempts=admitted,
            rejected_attempts=rejected,
            collected_at=datetime.now(UTC),
        ),
    )


async def journey(world: ProductWorld, frozen: ProductBoundaryManifest, output: Path) -> None:
    installed, observations = await installation_checks(world)
    save(world, frozen, output, observations, ())
    batches, native_rows = await native_batches(world, installed, output)
    observations += native_rows
    save(world, frozen, output, observations, batches)
    expiring = await begin_batch(world, installed, "product-boundary-expiry", seconds=30)
    for rows in (
        await read_scope_checks(world, batches[0]),
        await seal_checks(world, batches[0]),
        await installation_refusals(world, installed),
        await recursion_and_isolation(world),
    ):
        observations += rows
        save(world, frozen, output, observations, batches)
    observations += (await cleanup_proof(world, batches[0]), await cancelled(world, installed))
    observations += (await expired(world, expiring, batches[0]),)
    save(world, frozen, output, observations, batches)
    observations += await retention_checks(world, batches[0])
    save(world, frozen, output, observations, batches)


async def run(directory: Path, output: Path) -> ProductBoundaryReport:
    started = datetime.now(UTC)
    world = await prepare_world(
        directory, output / "private-state", started + timedelta(seconds=600)
    )
    try:
        world = await asyncio.to_thread(configure_target, world)
        verify_binding(world.stack, directory)
        frozen = manifest(world, started)
        write_json(output / "manifest.json", frozen)
        save(world, frozen, output, (), ())
        async with asyncio.timeout(max(1, (world.deadline - datetime.now(UTC)).total_seconds())):
            await journey(world, frozen, output)
        return observe(output)
    finally:
        await world.close()


def finalize(directory: Path, output: Path) -> ProductBoundaryReport:
    stack = StackBinding.model_validate(read_json(directory / "stack.json"))
    frozen = ProductBoundaryManifest.model_validate(read_json(output / "manifest.json"))
    evidence = ProductBoundaryEvidence.model_validate(read_json(output / "evidence.json"))
    if (
        read_json(directory / "ownership.json")
        != {"project_name": stack.project_name, "nonce": stack.nonce}
        or read_json(directory / "cleanup.json")
        != {"project_name": stack.project_name, "status": "completed"}
        or frozen.disposal.binding_nonce != stack.nonce
        or frozen.disposal.target_container_id != stack.runner_container_id
        or frozen.source_digest != stack.source_digest
        or frozen.builds.verifier != _verifier_digest(stack.runtime_profile)
    ):
        raise HarnessError("PRODUCT_BOUNDARY_FINAL_IDENTITY_CHANGED")
    _verify_removed(stack.project_name)
    receipt = TargetDisposalReceipt(
        **frozen.disposal.model_dump(),
        removed_at=datetime.now(UTC),
        containers_absent=True,
        volumes_absent=True,
        networks_absent=True,
    )
    if not (output / "evidence.pre-disposal.json").exists():
        write_json(output / "evidence.pre-disposal.json", evidence)
    write_json(output / "evidence.json", evidence.model_copy(update={"disposal": receipt}))
    return observe(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="真实产品非模型边界验收; 独立O保留固定分母")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--finalize-disposable", action="store_true")
    args = parser.parse_args()
    if args.finalize_disposable:
        report = finalize(args.directory, args.output)
    else:
        args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        report = asyncio.run(run(args.directory, args.output))
    print(json.dumps(report.model_dump(mode="json")))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
