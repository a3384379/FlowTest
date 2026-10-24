"""Run all draft variants only against a verified, owned Full/Compact profile."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from xml.etree.ElementTree import Element, SubElement, tostring

import httpx
from pydantic import ValidationError
from scripts.selftest.bootstrap import BootstrapResult, bootstrap
from scripts.selftest.contracts import FixtureBudgetScope
from scripts.selftest.io import (
    HarnessError,
    PublicAPI,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import (
    ROOT,
    StackBinding,
    private_environment,
    verify_binding,
)
from scripts.selftest.runtime_faults import (
    Assets,
    DropCompletedResponse,
    FrozenRuntimeBatch,
    LossClient,
    Observation,
    OwnedWorkers,
    Pack,
    RuntimeBuilds,
    RuntimeClients,
    RuntimeGate,
    RuntimePackReport,
    StandaloneGateWitness,
    VariantReport,
    VariantRuntime,
    configure,
    driver_digest,
    initial_reports,
    install,
    load_pack,
    run001_relation,
    verify,
)


@dataclass
class Progress:
    reports: tuple[VariantReport, ...]
    observations: tuple[Observation, ...] = ()
    gates: tuple[StandaloneGateWitness, ...] = ()

    def record(self, index: int, observed: Observation, report: VariantReport) -> None:
        self.reports = (*self.reports[:index], report, *self.reports[index + 1 :])
        self.observations = (*self.observations, observed)

    def result(self, frozen: FrozenRuntimeBatch) -> RuntimePackReport:
        relation = run001_relation(self.observations)
        from scripts.selftest.standalone_runtime_gate import gate_findings

        gate_requests = sum(row.settled.request_count for row in self.gates)
        requests = sum(item.request_count for item in self.observations) + gate_requests
        reasons = (
            *budget_findings(frozen, self.observations, gate_requests),
            *gate_findings(frozen, self.gates),
        )
        if datetime.now(UTC) > frozen.deadline:
            reasons = (*reasons, "RUNTIME_FAULT_BATCH_DEADLINE")
        complete = (
            all(item.status == "matched" for item in self.reports)
            and relation
            and requests <= 100
            and not reasons
            and len(self.observations) == len(self.reports) == 15
        )
        return RuntimePackReport(
            pack_digest=frozen.pack_digest,
            completed_count=len(self.observations),
            verdict="passed" if complete else "blocked",
            exit_code=0 if complete else 2,
            run001_same_frozen_plan_distinct_runs=relation,
            request_count=requests,
            runtime_profile=frozen.profile,
            reason_codes=reasons,
            budget=self.observations[-1].budget if self.observations else None,
            scenarios=self.reports,
            standalone_gates=self.gates,
        )


def budget_findings(
    frozen: FrozenRuntimeBatch, observations: tuple[Observation, ...], gate_requests: int = 0
) -> tuple[str, ...]:
    if not observations:
        return ("RUNTIME_FAULT_FIXTURE_BUDGET_MISSING",)
    previous = 0
    epochs = set()
    for observed in observations:
        budget = observed.budget
        if budget is None:
            return ("RUNTIME_FAULT_FIXTURE_BUDGET_MISSING",)
        if (
            budget.parent_batch_key != frozen.batch_key
            or budget.nonce != frozen.nonce
            or budget.limit != 100
            or budget.expires_at != frozen.deadline.timestamp()
            or budget.fixture_digest != frozen.pack_digest
            or budget.rejected_count
            or budget.admitted_count < previous + observed.request_count
            or budget.admitted_count > 100
        ):
            return ("RUNTIME_FAULT_FIXTURE_BUDGET_MISMATCH",)
        previous = budget.admitted_count
        epochs.add(budget.registration_epoch)
    if (
        len(epochs) != 1
        or previous != sum(item.request_count for item in observations) + gate_requests
    ):
        return ("RUNTIME_FAULT_FIXTURE_BUDGET_COUNT_MISMATCH",)
    return ()


def write_junit(output: Path, report: RuntimePackReport) -> None:
    """Keep actual native outcomes and independent golden checks in separate fixed suites."""
    for role in ("execution", "verification"):
        suite = Element("testsuite", name="runtime-faults-" + role, tests="15")
        for scenario in report.scenarios:
            case = SubElement(
                suite, "testcase", classname=scenario.scenario_id, name=scenario.variant
            )
            if role == "execution":
                status = scenario.native_status or "NOT_RUN"
                SubElement(case, "system-out").text = "native_status=" + status
                if status == "failed":
                    SubElement(case, "failure", message="native_status=failed")
                elif status != "passed":
                    SubElement(case, "skipped", message="native_status=" + status)
            elif scenario.status != "matched":
                message = ",".join(item.code for item in scenario.findings)
                SubElement(case, "failure", message=scenario.status + ":" + message)
        (output / (role + ".junit.xml")).write_bytes(
            tostring(suite, encoding="utf-8", xml_declaration=True)
        )


def freeze(binding: StackBinding, pack: Pack, digest: str) -> FrozenRuntimeBatch:
    return FrozenRuntimeBatch.model_validate(
        {
            "batch_key": "runtime-" + uuid4().hex[:20],
            "pack_digest": digest,
            "driver_digest": driver_digest(ROOT),
            "expected_variants": [item.model_dump(mode="json") for item in pack.variants],
            "builds": RuntimeBuilds(
                candidate=binding.candidate_image_digest,
                fixture=binding.fixture_image_digest,
            ).model_dump(mode="json"),
            "source_digest": binding.source_digest,
            "profile": binding.runtime_profile,
            "nonce": binding.nonce,
            "created_at": datetime.now(UTC),
            "deadline": datetime.now(UTC) + timedelta(seconds=600),
        }
    )


def lossy_factory(binding: StackBinding, result: BootstrapResult) -> Callable[[], LossClient]:
    def create() -> LossClient:
        witness = DropCompletedResponse(httpx.AsyncHTTPTransport(trust_env=False))
        api = PublicAPI(
            binding.runner_url,
            result.credentials.reviewer_token,
            str(result.installation.organization_id),
            transport=witness,
        )
        return LossClient(api, witness)

    return create


async def run_variants(
    binding: StackBinding,
    result: BootstrapResult,
    frozen: FrozenRuntimeBatch,
    pack: Pack,
    output: Path,
    clients: RuntimeClients,
    workers: RuntimeGate,
    progress: Progress,
) -> None:
    shared: Assets | None = None
    for index, golden in enumerate(pack.variants):
        if driver_digest(ROOT) != frozen.driver_digest:
            raise HarnessError("RUNTIME_FAULT_DRIVER_CHANGED_AFTER_FREEZE")
        if datetime.now(UTC) >= frozen.deadline:
            raise HarnessError("RUNTIME_FAULT_BATCH_DEADLINE")
        phase = output / (golden.scenario_id + "-" + golden.variant)
        phase.mkdir()
        if golden.variant == "ci" and shared is not None:
            assets = shared
            write_json(phase / "assets.json", assets)
        else:
            assets = await install(
                clients.writer,
                project=result.installation.project_id,
                service=result.installation.fixture_service_id,
                fixture_url=binding.fixture_internal_url,
                batch=frozen.batch_key,
                scenario=golden.scenario_id + "-" + golden.variant,
                directory=phase,
                pinned=golden.variant != "unpinned-control",
                skip_cleanup=golden.skip_cleanup,
            )
            if golden.variant == "manual":
                shared = assets
        await configure(
            clients.observer,
            assets,
            frozen.pack_digest,
            slow=golden.stage == "running",
            scope=FixtureBudgetScope(
                parent_batch_key=frozen.batch_key,
                nonce=frozen.nonce,
                limit=100,
                expires_at=frozen.deadline.timestamp(),
            ),
        )
        runtime = VariantRuntime(
            golden,
            assets,
            clients,
            workers,
            phase,
            fixture_nonce=frozen.nonce,
            fixture_digest=frozen.pack_digest,
            fixture_deadline=frozen.deadline,
        )
        observed = await runtime.execute()
        from scripts.selftest.standalone_runtime_gate import StandaloneRuntimeGate

        if isinstance(workers, StandaloneRuntimeGate):
            progress.gates = workers.witnesses
        report = verify(golden, observed)
        write_json(phase / "observation.json", observed)
        write_json(phase / "verification.json", report)
        progress.record(index, observed, report)
        write_json(output / "verification.json", progress.result(frozen))
    write_junit(output, progress.result(frozen))


def observer_clients(
    binding: StackBinding,
    result: BootstrapResult,
    mock_management_token: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[PublicAPI, PublicAPI]:
    reader = PublicAPI(
        binding.runner_url,
        result.credentials.observer_token,
        transport=transport,
    )
    fixture = PublicAPI(
        binding.observer_url,
        mock_management_token,
        api_prefix="",
        transport=transport,
    )
    return reader, fixture


async def execute(
    binding: StackBinding,
    directory: Path,
    output: Path,
    pack: Pack,
    frozen: FrozenRuntimeBatch,
    progress: Progress,
) -> None:
    result = await bootstrap(binding, directory)
    installation, credentials = result.installation, result.credentials
    writer = PublicAPI(
        binding.runner_url,
        credentials.reviewer_token,
        str(installation.organization_id),
    )
    private = private_environment(directory)
    reader, observer = observer_clients(
        binding,
        result,
        private["FLOWTEST_SELFTEST_OBSERVER_TOKEN"],
    )
    ci = None
    token_id = None
    workers: RuntimeGate | None = None
    try:
        token = await writer.object(
            "POST",
            f"/projects/{installation.project_id}/service-tokens",
            {
                "name": frozen.batch_key,
                "scopes": ["execute:test-plan", "execute:workflow"],
                "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
            },
        )
        token_id = text_value(token["id"])
        ci = PublicAPI(
            binding.runner_url,
            text_value(token["token"]),
            str(installation.organization_id),
        )
        clients = RuntimeClients(
            writer,
            ci,
            reader,
            observer,
            binding.runner_url,
            credentials.observer_token,
            lossy_factory(binding, result),
        )
        if binding.runtime_profile == "standalone":
            from scripts.selftest.standalone_runtime_gate import StandaloneRuntimeGate

            workers = StandaloneRuntimeGate(
                binding,
                directory,
                output,
                frozen,
                clients,
                installation.project_id,
                installation.fixture_service_id,
            )
        else:
            workers = OwnedWorkers(binding, directory)
        await run_variants(binding, result, frozen, pack, output, clients, workers, progress)
    finally:
        if workers is not None:
            workers.resume()
        if token_id is not None:
            await writer.request(
                "DELETE",
                f"/projects/{installation.project_id}/service-tokens/{token_id}",
            )
        await writer.close()
        await reader.close()
        await observer.close()
        if ci is not None:
            await ci.close()


async def main(directory: Path, output: Path) -> int:
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    verify_binding(binding, directory)
    if output.exists():
        raise HarnessError("RUNTIME_FAULT_OUTPUT_MUST_BE_NEW")
    pack, digest = load_pack(ROOT / "selftest/packs/runtime-faults-v1/expectations.json")
    frozen = freeze(binding, pack, digest)
    output.mkdir(parents=True)
    progress = Progress(initial_reports(pack))
    write_json(output / "manifest.json", frozen)
    write_json(output / "verification.json", progress.result(frozen))
    write_junit(output, progress.result(frozen))
    try:
        await execute(binding, directory, output, pack, frozen, progress)
    except (HarnessError, httpx.HTTPError, ValidationError) as error:
        safe = str(error).split(":")[0] if isinstance(error, HarnessError) else type(error).__name__
        write_json(output / "failure.json", {"status": "blocked", "code": safe[:100]})
    report = progress.result(frozen)
    write_json(output / "verification.json", report)
    write_junit(output, report)
    return report.exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.directory, args.output_dir)))
