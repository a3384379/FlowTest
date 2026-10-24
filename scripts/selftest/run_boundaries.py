"""Owned target CLI for public security, installation recovery and real JWT expiry."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.selftest.auth_expiry import LoginCredentials, execute_auth_expiry
from scripts.selftest.bootstrap import _active_password
from scripts.selftest.boundary_verify import BoundaryPack, BoundaryReport, write_report
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.initialization_boundaries import (
    execute_initialization_boundaries,
    finalize_initialization_boundaries,
)
from scripts.selftest.initialization_contracts import INIT_SCENARIOS, InitializationResult
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    object_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import ROOT, StackBinding, private_environment, verify_binding
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.run import _verifier_digest
from scripts.selftest.security_boundaries import (
    execute_security_boundaries,
    finalize_security_boundaries,
)
from scripts.selftest.security_boundary_contracts import SECURITY_SCENARIOS, BoundaryResult
from scripts.selftest.security_boundary_http import BoundaryAPI
from scripts.selftest.target_auth_policy import TargetAuthPolicy


async def _login(
    binding: StackBinding, directory: Path, budget: ProtocolHttpBudget, deadline: datetime
) -> str:
    private = private_environment(directory)
    password = private["FLOWTEST_SELFTEST_TARGET_PASSWORD"]
    api = BoundaryAPI(binding.target_url, budget, deadline)
    try:
        payload: JsonObject = {"email": "selftest-b@example.com", "password": password}
        login = object_value(await api.request("POST", "/auth/login", payload, allow_status=(401,)))
        if "access_token" not in login:
            password = _active_password(password)
            payload["password"] = password
            login = await api.object("POST", "/auth/login", payload)
        if object_value(login["user"])["requires_password_change"] is True:
            api_token = BoundaryAPI(
                binding.target_url, budget, deadline, text_value(login["access_token"])
            )
            try:
                await api_token.request(
                    "POST",
                    "/auth/change-password",
                    {"current_password": password, "new_password": _active_password(password)},
                )
            finally:
                await api_token.close()
            payload["password"] = _active_password(password)
            login = await api.object("POST", "/auth/login", payload)
        return text_value(login["access_token"])
    finally:
        await api.close()


def observe(pack: BoundaryPack, output: Path) -> BoundaryReport:
    raw = read_json(output / "result.json")
    identifiers = (
        SECURITY_SCENARIOS
        if pack == "security"
        else INIT_SCENARIOS
        if pack == "initialization"
        else ("ST-SECURITY-access-expired",)
    )
    pending = BoundaryReport(
        pack=pack,
        result_digest=canonical_digest(raw),
        manifest_digest=canonical_digest(raw["manifest"]),
        scenario_ids=identifiers,
        reason_codes=("BOUNDARY_OBSERVER_PROCESS_UNAVAILABLE",),
        exit_code=2,
    )
    destination = output / "independent-o"
    write_report(pending, destination)
    command = [
        sys.executable,
        "-m",
        "scripts.selftest.boundary_verify",
        "--pack",
        pack,
        "--result",
        str(output / "result.json"),
        "--output",
        str(destination),
    ]
    try:
        child = subprocess.run(  # noqa: S603 -- fixed trusted O module and typed paths
            command,
            cwd=ROOT,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(ROOT),
                "PYTHONUNBUFFERED": "1",
            },
            capture_output=True,
            timeout=30,
            check=False,
        )
        report = BoundaryReport.model_validate(read_json(destination / "verification.json"))
        if (
            report.pack,
            report.result_digest,
            report.manifest_digest,
            report.scenario_ids,
            report.exit_code,
        ) != (pack, pending.result_digest, pending.manifest_digest, identifiers, child.returncode):
            raise HarnessError("BOUNDARY_OBSERVER_RECEIPT_MISMATCH")
    except (OSError, ValueError, subprocess.SubprocessError, HarnessError):
        report = pending
    write_report(report, output)
    return report


async def execute(pack: BoundaryPack, directory: Path, output: Path) -> BoundaryReport:
    if output.exists():
        raise HarnessError("SELFTEST_BOUNDARY_OUTPUT_EXISTS_NO_REPLAY")
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    verify_binding(binding, directory)
    deadline = datetime.now(UTC) + timedelta(seconds=600)
    output.mkdir(mode=0o700, parents=True)
    write_json(
        output / "frozen-stack.json",
        {
            "binding": binding.model_dump(mode="json"),
            "verifier": _verifier_digest(binding.runtime_profile),
        },
    )
    if pack == "auth-expiry":
        policy = TargetAuthPolicy.model_validate(read_json(directory / "target-auth-policy.json"))
        budget = ProtocolHttpBudget(
            output / "private-budget.sqlite3", binding.nonce, deadline.timestamp()
        )
        private = private_environment(directory)
        await execute_auth_expiry(
            binding=binding,
            policy=policy,
            login=LoginCredentials(
                "selftest-b@example.com", private["FLOWTEST_SELFTEST_TARGET_PASSWORD"]
            ),
            budget=budget,
            output_dir=output,
            deadline=deadline,
        )
    else:
        budget_path = output / (
            "private-worker-state/shared-budget.sqlite3"
            if pack == "initialization"
            else "private-budget.sqlite3"
        )
        budget = ProtocolHttpBudget(budget_path, binding.nonce, deadline.timestamp())
        token = await _login(binding, directory, budget, deadline)
        driver = (
            execute_security_boundaries if pack == "security" else execute_initialization_boundaries
        )
        await driver(
            binding=binding,
            bootstrap_token=token,
            batch_key="boundary-" + secrets.token_hex(8),
            output_dir=output,
            deadline=deadline,
        )
    return observe(pack, output)


def finalize(pack: BoundaryPack, directory: Path, output: Path) -> BoundaryReport:
    if pack == "auth-expiry":
        raise HarnessError("SELFTEST_AUTH_EXPIRY_HAS_NO_DISPOSAL_FINALIZER")
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    if read_json(output / "frozen-stack.json") != {
        "binding": binding.model_dump(mode="json"),
        "verifier": _verifier_digest(binding.runtime_profile),
    }:
        raise HarnessError("SELFTEST_BOUNDARY_STACK_OR_VERIFIER_CHANGED")
    raw = read_json(output / "result.json")
    if pack == "security":
        finalize_security_boundaries(
            BoundaryResult.model_validate(raw),
            binding=binding,
            stack_directory=directory,
            output_dir=output,
        )
    else:
        finalize_initialization_boundaries(
            InitializationResult.model_validate(raw),
            binding=binding,
            stack_directory=directory,
            output_dir=output,
        )
    return observe(pack, output)


def main() -> int:
    parser = argparse.ArgumentParser(description="专用目标初始化/安全/认证过期边界自测; 不调用模型")
    parser.add_argument(
        "--pack", choices=("security", "initialization", "auth-expiry"), required=True
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--finalize-disposable", action="store_true")
    args = parser.parse_args()
    report = (
        finalize(args.pack, args.directory, args.output)
        if args.finalize_disposable
        else asyncio.run(execute(args.pack, args.directory, args.output))
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
