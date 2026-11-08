"""Frozen API P0 variants through ordinary native Case/Suite/Plan execution."""

from __future__ import annotations

import asyncio
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field
from scripts.selftest.bootstrap import Installation
from scripts.selftest.contracts import (
    Builds,
    Contract,
    RequiredDisposal,
    TargetDisposalReceipt,
    canonical_digest,
)
from scripts.selftest.fixed_baseline import CorePack, load_core_pack
from scripts.selftest.io import (
    HarnessError,
    PublicAPI,
    object_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import StackBinding, _verify_removed
from scripts.selftest.native_api_pack import NativeAPIResult, _bind, execute_native_api_pack
from scripts.selftest.verify import verify_batch, write_report

PACK = Path(__file__).resolve().parents[2] / "selftest/packs/supplemental-api-v1"


class SupplementalActors(Contract):
    nonmember_id: UUID
    nonmember_email: str
    cross_id: UUID
    cross_email: str
    cross_organization_id: UUID


class SupplementalCoverage(Contract):
    scenario_id: str
    acceptance_id: str
    scope: Literal["native_case_suite_plan_run"]
    raw_status: Literal["passed"]


class SupplementalCoverageDocument(Contract):
    schema_version: Literal["flowtest-supplemental-coverage-v1"]
    scenarios: tuple[SupplementalCoverage, ...] = Field(min_length=1, max_length=50)
    scope: Literal["selected_native_variants_only"]
    claim_all_api001_variants_complete: Literal[False]


class SupplementalExclusion(Contract):
    acceptance_id: str
    variant_key: str
    status: Literal["unsupported_in_current_profile_budget"]
    reason: str


class SupplementalExclusions(Contract):
    schema_version: Literal["flowtest-supplemental-exclusions-v1"]
    items: tuple[SupplementalExclusion, ...] = Field(min_length=1, max_length=10)


def load_supplemental_api_pack(
    installation: Installation,
    batch_key: str,
    actors: SupplementalActors,
    binding: StackBinding,
    directory: Path = PACK,
) -> CorePack:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,70}", batch_key) is None:
        raise HarnessError("SELFTEST_SUPPLEMENTAL_BATCH_KEY_INVALID")
    pack = load_core_pack(directory)
    if (
        pack.manifest.pack_id != "supplemental-api-v1"
        or installation.binding_nonce != binding.nonce
    ):
        raise HarnessError("SELFTEST_SUPPLEMENTAL_PACK_OR_OWNERSHIP_MISMATCH")
    coverage = SupplementalCoverageDocument.model_validate(read_json(directory / "coverage.json"))
    exclusions = SupplementalExclusions.model_validate(read_json(directory / "exclusions.json"))
    if tuple(row.scenario_id for row in coverage.scenarios) != pack.manifest.scenario_ids:
        raise HarnessError("SELFTEST_SUPPLEMENTAL_COVERAGE_SET_MISMATCH")
    bindings = {
        "00000000-0000-4000-8000-000000000001": str(installation.target_project_id),
        "00000000-0000-4000-8000-000000000002": str(installation.target_organization_id),
        "$BATCH": batch_key,
        "$B_EMAIL": installation.target_email,
        "$NONMEMBER_EMAIL": actors.nonmember_email,
        "$CROSS_EMAIL": actors.cross_email,
        "$CROSS_ORG": str(actors.cross_organization_id),
    }
    bound = CorePack.model_validate(_bind(pack.model_dump(mode="json"), bindings))
    expected = tuple(
        row.model_copy(update={"fixture_batch_key": f"{batch_key}-phase-{index + 1}"})
        for index, row in enumerate(bound.expectations)
    )
    disposal = RequiredDisposal(
        project_name=binding.project_name,
        target_container_id=binding.target_container_id,
        target_volume=binding.target_volume,
        target_image=binding.candidate_image_digest,
        binding_nonce=binding.nonce,
    )
    expected = (
        expected[0].model_copy(
            update={
                "expected": expected[0].expected.model_copy(update={"required_disposal": disposal})
            }
        ),
        *expected[1:],
    )
    return bound.model_copy(
        update={
            "expectations": expected,
            "digest": canonical_digest(
                {
                    "core_manifest_digest": pack.digest,
                    "coverage": coverage.model_dump(mode="json"),
                    "exclusions": exclusions.model_dump(mode="json"),
                }
            ),
        }
    )


async def _activate(
    target_url: str, email: str, initial: str, active: str, *, expected_password_change: bool
) -> None:
    public = PublicAPI(target_url)
    authenticated: PublicAPI | None = None
    try:
        login = await public.object("POST", "/auth/login", {"email": email, "password": initial})
        if object_value(login["user"])["requires_password_change"] is not expected_password_change:
            raise HarnessError("SELFTEST_SUPPLEMENTAL_NEW_ACTOR_STATE_MISMATCH")
        authenticated = PublicAPI(target_url, text_value(login["access_token"]))
        await authenticated.request(
            "POST", "/auth/change-password", {"current_password": initial, "new_password": active}
        )
    finally:
        if authenticated is not None:
            await authenticated.close()
        await public.close()


async def _actor(
    target: PublicAPI,
    api: PublicAPI,
    installation: Installation,
    binding: StackBinding,
    *,
    batch: str,
    kind: str,
    organization: UUID,
) -> tuple[UUID, str]:
    email = f"{batch[:50]}-{kind}@example.com"
    initial, active = secrets.token_urlsafe(30), secrets.token_urlsafe(30)
    target.set_organization(str(organization))
    user = await target.object(
        "POST", "/users", {"email": email, "password": initial, "display_name": "原生权限独立身份"}
    )
    identifier = UUID(text_value(user["id"]))
    await target.object(
        "PUT",
        f"/organizations/{organization}/members/{identifier}",
        {"user_id": str(identifier), "role": "member"},
    )
    await _activate(
        binding.target_url,
        email,
        initial,
        active,
        expected_password_change=binding.runtime_profile != "standalone",
    )
    await api.object(
        "PUT",
        f"/projects/{installation.project_id}/secrets",
        {
            "name": "SELFTEST_B_NONMEMBER_PASSWORD"
            if kind == "nonmember"
            else "SELFTEST_B_CROSS_PASSWORD",
            "value": active,
        },
    )
    return identifier, email


async def provision_supplemental_actors(
    api: PublicAPI,
    target: PublicAPI,
    installation: Installation,
    binding: StackBinding,
    batch: str,
    output: Path,
) -> SupplementalActors:
    organization = installation.target_organization_id
    if organization is None or installation.binding_nonce != binding.nonce:
        raise HarnessError("SELFTEST_SUPPLEMENTAL_TARGET_SCOPE_MISSING")
    try:
        nonmember, nonmember_email = await _actor(
            target,
            api,
            installation,
            binding,
            batch=batch,
            kind="nonmember",
            organization=organization,
        )
        cross_org = await target.object(
            "POST",
            "/organizations",
            {"name": "原生跨组织拒绝", "slug": "p0-" + secrets.token_hex(8)},
        )
        cross_organization = UUID(text_value(cross_org["id"]))
        cross, cross_email = await _actor(
            target,
            api,
            installation,
            binding,
            batch=batch,
            kind="cross",
            organization=cross_organization,
        )
    finally:
        target.set_organization(str(organization))
    actors = SupplementalActors(
        nonmember_id=nonmember,
        nonmember_email=nonmember_email,
        cross_id=cross,
        cross_email=cross_email,
        cross_organization_id=cross_organization,
    )
    write_json(output / "owned-actor-ids.json", actors)
    return actors


async def execute_supplemental_api_pack(
    api: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    *,
    capture_reader: PublicAPI,
    target_reader: PublicAPI,
    target_provisioner: PublicAPI,
    installation: Installation,
    batch_key: str,
    nonce: str,
    fixture_digest: str,
    builds: Builds,
    output_dir: Path,
    deadline: datetime | None = None,
    binding: StackBinding,
) -> NativeAPIResult:
    started = datetime.now(UTC)
    expires = (
        min(deadline, started + timedelta(seconds=600))
        if deadline
        else started + timedelta(seconds=600)
    )
    write_json(
        output_dir / "setup-intent.json",
        {
            "batch_key": batch_key,
            "nonce": nonce,
            "binding_nonce": binding.nonce,
            "created_at": started.isoformat(),
            "deadline": expires.isoformat(),
            "cleanup": "exact_owned_target_disposal_required",
        },
    )
    async with asyncio.timeout(max(0, (expires - datetime.now(UTC)).total_seconds())):
        actors = await provision_supplemental_actors(
            api, target_provisioner, installation, binding, batch_key, output_dir
        )
        pack = load_supplemental_api_pack(installation, batch_key, actors, binding)
        write_json(output_dir / "frozen-exclusions.json", read_json(PACK / "exclusions.json"))
        return await execute_native_api_pack(
            api,
            reader,
            observer,
            capture_reader=capture_reader,
            target_reader=target_reader,
            installation=installation,
            batch_key=batch_key,
            nonce=nonce,
            fixture_digest=fixture_digest,
            builds=builds,
            output_dir=output_dir,
            deadline=expires,
            binding=binding,
            pack=pack,
        )


def finalize_supplemental_cleanup(
    result: NativeAPIResult, *, binding: StackBinding, stack_directory: Path, output_dir: Path
) -> NativeAPIResult:
    stored = StackBinding.model_validate(read_json(stack_directory / "stack.json"))
    if (
        stored.model_dump(exclude={"runner_container_id"})
        != binding.model_dump(exclude={"runner_container_id"})
        or read_json(stack_directory / "ownership.json")
        != {"project_name": binding.project_name, "nonce": binding.nonce}
        or read_json(stack_directory / "cleanup.json")
        != {"project_name": binding.project_name, "status": "completed"}
    ):
        raise HarnessError("SELFTEST_SUPPLEMENTAL_DISPOSAL_OWNERSHIP_MISMATCH")
    _verify_removed(binding.project_name)
    now = datetime.now(UTC)
    observations = []
    changed = False
    for expected, actual in zip(result.manifest.scenarios, result.evidence.scenarios, strict=True):
        required = expected.expected.required_disposal
        if required is not None:
            wanted = RequiredDisposal(
                project_name=binding.project_name,
                target_container_id=binding.target_container_id,
                target_volume=binding.target_volume,
                target_image=binding.candidate_image_digest,
                binding_nonce=binding.nonce,
            )
            if actual.scenario_id != expected.scenario_id or required != wanted:
                raise HarnessError("SELFTEST_SUPPLEMENTAL_DISPOSAL_BINDING_MISMATCH")
            receipt = actual.target_disposal
            if receipt is None:
                changed = True
            actual = actual.model_copy(
                update={
                    "target_disposal": receipt
                    or TargetDisposalReceipt(
                        **wanted.model_dump(),
                        removed_at=now,
                        containers_absent=True,
                        volumes_absent=True,
                        networks_absent=True,
                    )
                }
            )
        observations.append(actual)
    if not (output_dir / "evidence.pre-disposal.json").exists():
        write_json(output_dir / "evidence.pre-disposal.json", result.evidence)
    evidence = result.evidence.model_copy(
        update={
            "scenarios": tuple(observations),
            "collected_at": now if changed else result.evidence.collected_at,
        }
    )
    report = verify_batch(result.manifest, evidence)
    write_json(output_dir / "evidence.json", evidence)
    write_report(report, output_dir)
    return NativeAPIResult(result.manifest, evidence, report, result.phases)
