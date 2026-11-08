"""Authorize only negative recursion metadata on the exact owned B API, with depth still one."""

import json
from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

from scripts.selftest.io import HarnessError, write_json
from scripts.selftest.local_stack import (
    _binding,
    _compose,
    _replace_private_environment,
    private_environment,
    verify_binding,
)
from scripts.selftest.product_boundary_common import ProductWorld
from scripts.selftest.profile_stack import ProfileProof

from app.core.self_tests import SelfTestBinding


def target_binding(world: ProductWorld) -> SelfTestBinding:
    return world.config.binding.model_copy(
        update={
            "id": uuid5(NAMESPACE_URL, "negative-recursion:" + world.stack.nonce),
            "name": "禁止递归的夹具负向绑定",
            "allowed_project_ids": (world.config.binding.target_project_id,),
            "runner_instance_id": "fixture-" + world.stack.nonce,
            "target_instance_id": "forbidden-next-" + world.stack.nonce,
        }
    )


def configure_target(world: ProductWorld) -> ProductWorld:
    original, directory = world.stack, world.directory
    verify_binding(original, directory)
    private = private_environment(directory)
    private["FLOWTEST_SELFTEST_TARGET_BINDINGS"] = json.dumps(
        [target_binding(world).model_dump(mode="json")],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    _replace_private_environment(directory / "private.env", private)
    arguments = [
        "up",
        "--detach",
        "--no-deps",
        "--force-recreate",
        "--wait",
        "--wait-timeout",
        "120",
        "target",
    ]
    if original.runtime_profile == "standalone":
        _compose(
            original.project_name,
            directory / "private.env",
            arguments,
            timeout=180,
            log_path=world.state / "target-configure.log",
        )
        current = _binding(
            original.project_name, original.nonce, private, directory / "private.env"
        )
    else:
        from scripts.selftest.profile_stack import _compose as compose_profile
        from scripts.selftest.profile_stack import _freeze

        proof = ProfileProof.model_validate_json((directory / "profile-proof.json").read_bytes())
        compose_profile(
            directory, original.project_name, proof.runtime_profile, arguments, timeout=180
        )
        current = _freeze(
            directory,
            original,
            original.project_name,
            original.nonce,
            proof.runtime_profile,
            proof.dependencies,
            private,
        )
        after = ProfileProof.model_validate_json((directory / "profile-proof.json").read_bytes())
        if tuple(row for row in proof.containers if row.role != "target") != tuple(
            row for row in after.containers if row.role != "target"
        ):
            raise HarnessError("PRODUCT_BOUNDARY_TARGET_RECONFIGURED_OTHER_RESOURCES")
    if original.model_dump(exclude={"target_container_id"}) != current.model_dump(
        exclude={"target_container_id"}
    ):
        raise HarnessError("PRODUCT_BOUNDARY_TARGET_BUILD_OR_IDENTITY_CHANGED")
    verify_binding(current, directory)
    write_json(directory / "stack.json", current)
    write_json(
        world.state / "target-negative-configuration.json",
        {
            "purpose": "recursion_negative_only",
            "fixture_depth": 1,
            "before_container_id": original.target_container_id,
            "after_container_id": current.target_container_id,
            "binding_id": str(target_binding(world).id),
        },
    )
    return replace(world, stack=current)
