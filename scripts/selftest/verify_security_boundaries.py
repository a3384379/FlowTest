"""Independent fixed policy checks for bounded security probes; zero Runs is not a closure."""

from __future__ import annotations

from datetime import UTC, datetime

from scripts.selftest.boundary_pack import load_boundary_pack
from scripts.selftest.security_boundary_contracts import (
    SECURITY_SCENARIOS,
    BoundaryIdentity,
    BoundaryObservation,
    BoundaryResult,
)


def verify_security_boundaries(result: BoundaryResult) -> tuple[str, ...]:
    manifest, evidence = result.manifest, result.evidence
    checked = datetime.now(UTC)
    reasons: list[str] = []
    if manifest.pack_digest != load_boundary_pack(manifest.pack_id, SECURITY_SCENARIOS).digest:
        reasons.append("SECURITY_PACK_MISMATCH")
    if manifest.deadline.tzinfo is None or checked > manifest.deadline:
        reasons.append("SECURITY_BATCH_EXPIRED")
    if (
        manifest.expected_scenarios != SECURITY_SCENARIOS
        or evidence.manifest_digest != manifest.digest
    ):
        reasons.append("SECURITY_MANIFEST_IDENTITY_MISMATCH")
    actual = tuple(item.scenario_id for item in evidence.scenarios)
    if actual != SECURITY_SCENARIOS:
        reasons.append("SECURITY_REQUIRED_SCENARIO_SET_MISMATCH")
    identity = evidence.identities
    if len({identity.owner_id, identity.editor_id, identity.observer_id}) != 3:
        reasons.append("SECURITY_ROLE_SEPARATION_MISMATCH")
    for scene in evidence.scenarios:
        if (
            not scene.complete
            or scene.native_run_ids
            or scene.native_executions
            or scene.is_system_admin
        ):
            reasons.append("SECURITY_SCOPE_OR_COMPLETENESS_MISMATCH")
        reasons.extend(_scenario_reasons(scene, identity))
    reasons.extend(_disposal_reasons(result))
    if (
        evidence.rejected_attempts
        or evidence.http_attempts > 500
        or manifest.created_at.tzinfo is None
        or evidence.collected_at.tzinfo is None
        or manifest.deadline.tzinfo is None
        or not manifest.created_at <= evidence.collected_at <= manifest.deadline
    ):
        reasons.append("SECURITY_BUDGET_OR_TIME_MISMATCH")
    return tuple(dict.fromkeys(reasons))


def _scenario_reasons(scene: BoundaryObservation, identity: BoundaryIdentity) -> list[str]:
    if scene.scenario_id in SECURITY_SCENARIOS[:2]:
        editor = scene.scenario_id == SECURITY_SCENARIOS[1]
        role = "editor" if editor else "owner"
        expected = {
            "ordinary_tasks": (401, "SELFTEST_AGENT_UNAUTHORIZED"),
            "self_signed_tasks": (401, "SELFTEST_AGENT_UNAUTHORIZED"),
            "self_report_verification": (401, "SELFTEST_AGENT_UNAUTHORIZED"),
            "invented_trusted_scope": (422, "VALIDATION_ERROR"),
        }
        if not editor:
            expected["valid_project_token_tasks"] = (401, "SELFTEST_AGENT_UNAUTHORIZED")
        actual = {item.operation: (item.status, item.code) for item in scene.denials}
        if (
            actual != expected
            or len(scene.denials) != len(expected)
            or any(not item.trace_id for item in scene.denials)
            or scene.role != role
            or scene.permission_role != role
            or scene.actor_id != (identity.editor_id if editor else identity.owner_id)
        ):
            return ["SECURITY_SELF_SIGNED_TRUST_BOUNDARY_MISMATCH"]
        return []
    if (
        scene.role != "observer"
        or scene.permission_role != "viewer"
        or scene.actor_id != identity.observer_id
    ):
        return ["SECURITY_OBSERVER_ROLE_MISMATCH"]
    if scene.scenario_id == SECURITY_SCENARIOS[2]:
        return (
            []
            if scene.artifact_id is not None and scene.artifact_purpose == "upload"
            else ["SECURITY_MANUAL_UPLOAD_PROMOTED"]
        )
    if scene.scenario_id == SECURITY_SCENARIOS[3]:
        return (
            []
            if scene.sentinel_present == (False,) * 9 and not scene.forbidden_secret_keys
            else ["SECURITY_SECRET_BOUNDARY_LEAK"]
        )
    if scene.scenario_id == SECURITY_SCENARIOS[4]:
        return (
            []
            if scene.sentinel_present == (True, False, True) and len(scene.observation_digests) == 3
            else ["SECURITY_PROJECT_REDACTION_POLICY_MISMATCH"]
        )
    return ["SECURITY_UNKNOWN_SCENARIO"]


def _disposal_reasons(result: BoundaryResult) -> list[str]:
    manifest, evidence = result.manifest, result.evidence
    if evidence.cleanup_status != "completed" or evidence.target_disposal is None:
        return ["OWNED_ASSET_DISPOSAL_PENDING"]
    elif (
        evidence.target_disposal.project_name != manifest.project_name
        or evidence.target_disposal.binding_nonce != manifest.nonce
        or evidence.target_disposal.target_container_id != manifest.target_container_id
        or evidence.target_disposal.target_image != manifest.target_image
        or evidence.target_disposal.target_volume != manifest.target_volume
    ):
        return ["SECURITY_DISPOSAL_IDENTITY_MISMATCH"]
    if (
        not evidence.collected_at
        <= evidence.target_disposal.removed_at
        <= min(manifest.deadline, datetime.now(UTC))
    ):
        return ["SECURITY_DISPOSAL_TIME_MISMATCH"]
    return []
