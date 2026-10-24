"""Synthetic DTO builder for oracle mutation tests; never deployed acceptance proof."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from scripts.selftest.contracts import Builds, canonical_digest
from scripts.selftest.io import read_json
from scripts.selftest.mcp_fault_contracts import (
    DispatchReceipt,
    FaultEvidence,
    FaultManifest,
    FaultObservation,
    FaultPack,
    FaultResult,
    FrameReceipt,
    FrozenCall,
    InactiveFixture,
    ProcessIdentity,
    ProcessRemovalProof,
)
from scripts.selftest.mcp_fault_http import forwarded_frame
from scripts.selftest.mcp_fault_setup import PACK_PATH, arguments
from scripts.selftest.mcp_negative_contracts import RpcRequest, RpcResponse
from scripts.selftest.mcp_probe_contracts import (
    ProbeAuthority,
    ProbeDesign,
    ProbeFixture,
    ProbeItem,
    ProbeOracle,
    ProbePage,
    ProbeResource,
    ProbeSnapshot,
    probe_kinds,
    snapshot_digest,
)
from scripts.selftest.mcp_probe_evidence import DisposalReceipt, StackSnapshot


def snapshot(authority, rows, at):
    ordered = tuple(sorted(rows, key=lambda row: (row.kind, str(row.id))))
    return ProbeSnapshot(
        pages=(
            ProbePage(
                probe_id=authority.probe_id,
                purpose="mcp_governance_negative",
                execution_scope="governance_negative_only",
                provenance="local_untrusted",
                binding_id=authority.binding_id,
                binding_fingerprint=authority.binding_fingerprint,
                manifest_digest=authority.manifest_digest,
                source_digest=authority.source_digest,
                runtime_profile=authority.runtime_profile,
                builds=authority.builds,
                covered_projects=authority.fixtures,
                covered_kinds=tuple(sorted(probe_kinds())),
                items=ordered,
                total=len(ordered),
                next_cursor=None,
                has_more=False,
                complete=True,
                reason_codes=(),
                snapshot_digest=snapshot_digest(authority, ordered),
                observed_at=at,
                expires_at=authority.expires_at,
            ),
        )
    )


def proposal(manifest, pack, identifier):
    design = ProbeDesign(
        document_digest=pack.normalized_design_digest,
        intent_key_digest=canonical_digest("synthetic.governance"),
        objective_digest=canonical_digest("合成治理验证, 不执行发布运行"),
        oracles=(
            ProbeOracle(
                id="status",
                kind="status",
                expression_digest=canonical_digest("$.status"),
                operator="equals",
                expected_digest=canonical_digest(200),
            ),
        ),
    )
    return ProbeResource(
        kind="ai_change_set",
        id=identifier,
        project_id=manifest.project_id,
        status="draft",
        fingerprint=pack.proposed_source_fingerprint,
        created_by_id=manifest.owner_user_id,
        actor_type="service_account",
        items=(
            ProbeItem(
                id=uuid4(),
                item_type="test_design",
                action="create",
                review_status="pending",
                reviewed_by_id=None,
                materialized_resource_type=None,
                materialized_resource_id=None,
                proposed_document_digest=pack.normalized_design_digest,
                design=design,
            ),
        ),
    )


def unit_evidence():
    import hashlib

    raw = read_json(PACK_PATH)
    pack = FaultPack.model_validate(raw)
    start = datetime.now(UTC) - timedelta(seconds=180)
    project, owner, writer, creator, machine = (uuid4() for _ in range(5))
    stack = StackSnapshot(
        schema_version="flowtest-selftest-binding-v1",
        project_name="flowtest-selftest-" + "1" * 12,
        nonce="2" * 32,
        runtime_profile="standalone",
        runner_url="http://127.0.0.1:40001",
        target_url="http://127.0.0.1:40002",
        observer_url="http://127.0.0.1:40003",
        target_internal_url="http://target:8000",
        fixture_internal_url="http://mock-target:8080",
        private_subnet="172.18.0.0/24",
        candidate_image="candidate",
        candidate_image_digest="sha256:" + "a" * 64,
        fixture_image="fixture",
        fixture_image_digest="sha256:" + "b" * 64,
        source_digest="c" * 64,
        candidate_source=None,
        dependency_digest="d" * 64,
        runner_container_id="e" * 64,
        target_container_id="f" * 64,
        observer_container_id="0" * 64,
        runner_volume="owned-a",
        target_volume="owned-b",
    )
    manifest = FaultManifest(
        batch_key="synthetic-oracle-unit",
        nonce=uuid4().hex,
        pack_digest=canonical_digest(raw),
        source_digest=stack.source_digest,
        created_at=start,
        expires_at=start + timedelta(seconds=600),
        project_id=project,
        owner_user_id=owner,
        writer_machine_id=writer,
        inactive_creator_id=creator,
        inactive_machine_id=machine,
        scenarios=pack.scenarios,
        calls=tuple(
            FrozenCall(
                scenario_id=row.scenario_id,
                tool_name=arguments(project, "synthetic-oracle-unit", row)[0],
                arguments_digest=canonical_digest(
                    arguments(project, "synthetic-oracle-unit", row)[1]
                ),
            )
            for row in pack.scenarios
        ),
    )
    authority = ProbeAuthority(
        probe_id=manifest.nonce,
        binding_id=uuid4(),
        binding_fingerprint=canonical_digest(
            stack.model_dump(mode="json", exclude={"runner_container_id"})
        ),
        manifest_digest=canonical_digest(manifest.model_dump(mode="json")),
        source_digest=stack.source_digest,
        runtime_profile="standalone",
        builds=Builds(
            runner=stack.candidate_image_digest,
            target=stack.candidate_image_digest,
            fixture="b" * 64,
            verifier="g" * 64,
        ),
        fixtures=(
            ProbeFixture(project_id=project, organization_id=uuid4()),
            ProbeFixture(project_id=uuid4(), organization_id=uuid4()),
        ),
        owner_user_id=owner,
        reviewer_user_id=uuid4(),
        machine_account_ids=(writer, machine),
        issued_at=start,
        expires_at=manifest.expires_at,
    )
    resources, rows = [], []
    for index, scenario in enumerate(pack.scenarios):
        at = start + timedelta(seconds=5 * index)
        before = snapshot(authority, resources, at)
        name, body = arguments(project, manifest.batch_key, scenario)
        session, nonce = uuid4(), uuid4().hex
        frames = (
            {"jsonrpc": "2.0", "id": 0, "method": "server/discover", "params": {}},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": name, "arguments": body},
            },
        )
        requests = tuple(
            RpcRequest(
                session_id=session,
                id=i,
                method=frame["method"],
                tool_name=name if i == 2 else None,
                arguments_digest=canonical_digest(body) if i == 2 else None,
                observed_at=at + timedelta(seconds=1),
            )
            for i, frame in enumerate(frames)
        )
        result_hash = canonical_digest({"synthetic-unit-result": index})
        responses = [
            RpcResponse(
                session_id=session,
                id=i,
                result_digest=result_hash,
                observed_at=at + timedelta(seconds=2),
            )
            for i in (0, 1)
        ]
        expected = scenario.expected
        result = FaultResult(
            trace_present=expected.trace_required,
            complete=expected.sdk_complete,
            rpc_error_code=expected.rpc_error_code,
            transport_error=expected.transport_error,
            tool_error=expected.tool_error,
            business_code=expected.business_code,
            text_marker=expected.text_marker,
            result_digest=result_hash if expected.sdk_complete else None,
        )
        if expected.sdk_complete or scenario.fault in {"bad_json", "bad_version"}:
            responses.append(
                RpcResponse(
                    session_id=session,
                    id=2,
                    result_digest=result_hash if expected.sdk_complete else None,
                    error_code=expected.rpc_error_code,
                    observed_at=at + timedelta(seconds=2),
                )
            )
        identifier = uuid4() if expected.mutation_count else None
        if identifier is not None:
            resources.append(proposal(manifest, pack, identifier))
        process = ProcessIdentity(nonce=nonce, pid=index + 1000, start_ticks=str(index + 100))
        sent = forwarded_frame(frames[2], scenario.fault)
        dispatch = DispatchReceipt(
            nonce=nonce,
            observed_at=at + timedelta(seconds=2),
            request_id=2,
            tool_name=name,
            arguments_digest=canonical_digest(body),
            sdk_frame_digest=canonical_digest(frames[2]),
            forwarded_digest=hashlib.sha256(sent).hexdigest(),
            forwarded_bytes=len(sent),
            forwarded_count=1,
            response_digest=canonical_digest({"synthetic-unit-envelope": index}),
            response_result_digest=result_hash if expected.sdk_complete else None,
            response_id=None if scenario.fault in {"bad_json", "bad_version"} else 2,
            server_http_status=expected.server_http_status,
            server_rpc_error=expected.server_rpc_error,
            proposal_id=identifier,
            fault_applied=True,
            process=process,
            server_killed=expected.server_killed,
            process_cleanup_complete=True,
            removal=ProcessRemovalProof(
                process=process, removed=True, observed_at=at + timedelta(seconds=3)
            ),
        )
        rows.append(
            FaultObservation(
                scenario_id=scenario.scenario_id,
                transport=scenario.transport,
                sdk_version="2.2.0",
                started_at=at,
                completed_at=at + timedelta(seconds=4),
                catalog_fingerprint=pack.catalog_fingerprint,
                tool_names=pack.tool_names,
                requests=requests,
                responses=tuple(responses),
                frames=tuple(
                    FrameReceipt(request_id=frame["id"], frame_digest=canonical_digest(frame))
                    for frame in frames
                ),
                dispatch=dispatch,
                result=result,
                before=before,
                after=snapshot(authority, resources, at + timedelta(seconds=3)),
            )
        )
    collected = start + timedelta(seconds=120)
    evidence = FaultEvidence(
        batch_key=manifest.batch_key,
        nonce=manifest.nonce,
        pack_digest=manifest.pack_digest,
        source_digest=manifest.source_digest,
        manifest_digest=authority.manifest_digest,
        authority_digest=canonical_digest(authority.model_dump(mode="json")),
        stack=stack,
        inactive_fixture=InactiveFixture(
            creator_id=creator,
            machine_id=machine,
            creator_is_active=False,
            machine_enabled=True,
            machine_revoked=False,
            user_response_digest="1" * 64,
            account_response_digest="2" * 64,
            mechanism="public_user_patch_and_service_account_list",
        ),
        scenarios=tuple(rows),
        http_admitted=100,
        http_rejected=0,
        tools_admitted=len(rows),
        tools_rejected=0,
        process_cleanup_complete=True,
        disposal_receipt=DisposalReceipt(
            project_name=stack.project_name,
            binding_nonce=stack.nonce,
            runner_volume=stack.runner_volume,
            target_volume=stack.target_volume,
            candidate_image_digest=stack.candidate_image_digest,
            removed_at=collected + timedelta(seconds=1),
            containers_absent=True,
            volumes_absent=True,
            networks_absent=True,
        ),
        collected_at=collected,
    )
    return manifest, evidence, authority
