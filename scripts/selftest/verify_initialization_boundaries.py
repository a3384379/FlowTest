"""Exact install-set/version and failed-recovery checks; no native Run is claimed."""

from __future__ import annotations

from datetime import UTC, datetime

from scripts.selftest.boundary_pack import load_boundary_pack
from scripts.selftest.initialization_contracts import (
    INIT_SCENARIOS,
    InitializationObservation,
    InitializationResult,
    InstallationInventory,
)
from scripts.selftest.initialization_worker import selected_initialization_pack


def verify_initialization_boundaries(result: InitializationResult) -> tuple[str, ...]:
    manifest, evidence = result.manifest, result.evidence
    reasons: list[str] = []
    if manifest.pack_digest != load_boundary_pack(manifest.pack_id, INIT_SCENARIOS).digest:
        reasons.append("INIT_PACK_MISMATCH")
    if manifest.deadline.tzinfo is None or datetime.now(UTC) > manifest.deadline:
        reasons.append("INIT_BATCH_EXPIRED")
    if (
        manifest.expected_scenarios != INIT_SCENARIOS
        or tuple(item.scenario_id for item in evidence.scenarios) != INIT_SCENARIOS
        or evidence.manifest_digest != manifest.digest
        or manifest.source_pack_digest != selected_initialization_pack().digest
    ):
        reasons.append("INIT_FROZEN_DENOMINATOR_OR_SOURCE_MISMATCH")
    for scene in evidence.scenarios:
        if not all(
            item.complete
            and not item.run_ids
            and not item.execution_ids
            and item.project_id == scene.project_id
            for item in (scene.before, scene.after, scene.repeat)
        ):
            reasons.append("INIT_INVENTORY_OR_RUN_SET_MISMATCH")
        if any(
            (
                scene.before.api_ids,
                scene.before.workflow_ids,
                scene.before.case_ids,
                scene.before.suite_ids,
                scene.before.plan_ids,
                scene.before.environment_ids,
            )
        ):
            reasons.append("INIT_FRESH_PROJECT_NOT_EMPTY")
        reasons.extend(_case_reasons(scene))
    if evidence.http_attempts > 500 or evidence.rejected_attempts:
        reasons.append("INIT_REQUEST_BUDGET_MISMATCH")
    if (
        manifest.created_at.tzinfo is None
        or evidence.collected_at.tzinfo is None
        or manifest.deadline.tzinfo is None
        or not manifest.created_at <= evidence.collected_at <= manifest.deadline
    ):
        reasons.append("INIT_TIME_WINDOW_MISMATCH")
    reasons.extend(_disposal_reasons(result))
    return tuple(dict.fromkeys(reasons))


def _case_reasons(scene: InitializationObservation) -> list[str]:
    codes = tuple(item.exit_code for item in scene.workers)
    if scene.scenario_id == "ST-INIT-unknown":
        expected = (
            "SELFTEST_INSTALL_UNKNOWN_POST_RESULT",
            "SELFTEST_BOOTSTRAP_UNKNOWN_RESULT_NEEDS_REVIEW",
        )
        if (
            codes != (2, 2)
            or tuple(item.reason_codes[0] for item in scene.workers if item.reason_codes)
            != expected
            or scene.unknown_posts_before_restart != scene.unknown_posts_after_restart
            or scene.after != scene.repeat
            or len(scene.repeat.environment_ids) != 1
            or scene.repeat.service_ids != (scene.repeat.default_service_id,)
            or any(
                (
                    scene.repeat.api_ids,
                    scene.repeat.workflow_ids,
                    scene.repeat.case_ids,
                    scene.repeat.suite_ids,
                    scene.repeat.plan_ids,
                )
            )
        ):
            return ["INIT_UNKNOWN_POST_REPLAY_OR_SET_MISMATCH"]
        return []
    if scene.scenario_id == "ST-INIT-concurrent":
        if (
            codes != (0, 4, 0)
            or scene.workers[1].reason_codes != ("SELFTEST_BOOTSTRAP_IN_PROGRESS_OR_NEEDS_REVIEW",)
            or scene.after != scene.repeat
            or scene.installation != scene.resumed_installation
        ):
            return ["INIT_CONCURRENT_DUPLICATION_OR_MAPPING_MISMATCH"]
    elif scene.scenario_id == "ST-INIT-partial":
        if (
            codes != (3, 0)
            or scene.after.environment_ids != scene.repeat.environment_ids
            or len(scene.after.environment_ids) != 1
            or scene.after.api_ids
            or scene.after.workflow_ids
        ):
            return ["INIT_PARTIAL_RESTART_MISMATCH"]
    else:
        return ["INIT_UNEXPECTED_SCENARIO"]
    if not _installed_set(scene) or not scene.published_mapping_matches:
        return ["INIT_PUBLISHED_NATIVE_MAPPING_MISMATCH"]
    return []


def _installed_set(scene: InitializationObservation) -> bool:
    installed = scene.installation
    actual: InstallationInventory = scene.repeat
    if installed is None or len(installed.assets) != 1:
        return False
    asset = installed.assets[0]
    return (
        actual.api_ids == (asset.api_id,)
        and actual.workflow_ids == (asset.workflow_id,)
        and actual.case_ids == (asset.case_id,)
        and actual.suite_ids == (installed.suite_id,)
        and actual.plan_ids == (installed.plan_id,)
        and actual.environment_ids == (installed.environment_id,)
        and installed.project_id == scene.project_id
        and installed.service_id in actual.service_ids
        and len(actual.service_ids) == 2
        and set(actual.service_ids) == {installed.service_id, actual.default_service_id}
        and installed.pack_digest == selected_initialization_pack().digest
    )


def _disposal_reasons(result: InitializationResult) -> list[str]:
    manifest, evidence = result.manifest, result.evidence
    if evidence.cleanup_status != "completed" or evidence.target_disposal is None:
        return ["OWNED_ASSET_DISPOSAL_PENDING"]
    elif (
        evidence.target_disposal.project_name,
        evidence.target_disposal.binding_nonce,
        evidence.target_disposal.target_container_id,
        evidence.target_disposal.target_image,
        evidence.target_disposal.target_volume,
    ) != (
        manifest.project_name,
        manifest.nonce,
        manifest.target_container_id,
        manifest.target_image,
        manifest.target_volume,
    ):
        return ["INIT_DISPOSAL_IDENTITY_MISMATCH"]
    if (
        not evidence.collected_at
        <= evidence.target_disposal.removed_at
        <= min(manifest.deadline, datetime.now(UTC))
    ):
        return ["INIT_DISPOSAL_TIME_MISMATCH"]
    return []
