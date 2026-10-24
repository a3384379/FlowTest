"""Rebuild product observation inputs from published, registered refs using GET only."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from scripts.selftest.contracts import ApiSource, Contract, canonical_digest
from scripts.selftest.fixed_baseline import CoreAPI, CorePack, CoreSource, CoreWorkflow, FixedAsset
from scripts.selftest.io import HarnessError, JsonObject, PublicAPI, object_value, objects_value

from app.domain.test_engineering import fingerprint_contract
from app.engine.contracts import ApiNodeConfig, WorkflowDefinition
from app.schemas.api_assets import APIVersionInput, APIVersionResponse
from app.schemas.self_tests import AgentTaskResponse, InstallationMapping, ScenarioAssets
from app.schemas.test_assets import TestCaseDefinitionInput, TestCaseVersionResponse
from app.schemas.workflows import WorkflowVersionResponse


class PreparedFixedAssets(Contract):
    schema_version: Literal["flowtest-prepared-fixed-assets-v1"] = (
        "flowtest-prepared-fixed-assets-v1"
    )
    project_id: UUID
    environment_id: UUID
    service_id: UUID
    batch_key: str
    nonce: str
    pack_digest: str
    assets: tuple[FixedAsset, ...]


def _api_nodes(definition: JsonObject) -> dict[tuple[str, str], ApiNodeConfig]:
    result = {}
    for group in [definition, *objects_value(definition.get("regions", []))]:
        for node in objects_value(group["nodes"]):
            if node["type"] != "api":
                continue
            key = (str(group.get("id", "main")), str(node["id"]))
            if key in result:
                raise HarnessError("SELFTEST_FIXED_RECOVERY_GRAPH_AMBIGUOUS")
            result[key] = ApiNodeConfig.model_validate(node["config"])
    return result


class FixedAssetRecovery:
    def __init__(self, reader: PublicAPI, task: AgentTaskResponse) -> None:
        if task.batch is None or task.frozen_manifest is None:
            raise HarnessError("SELFTEST_FIXED_RECOVERY_MANIFEST_MISSING")
        self.reader, self.task = reader, task
        # The frozen target-request budget still bounds native execution separately.
        # Reconstructing metadata is GET-only, capped independently, and uses its deadline.
        self.deadline, self.remaining = task.batch.deadline, 500

    async def _get(self, path: str) -> list[JsonObject]:
        if self.remaining <= 0 or datetime.now(UTC) >= self.deadline:
            raise HarnessError("SELFTEST_FIXED_RECOVERY_BUDGET_EXHAUSTED")
        self.remaining -= 1
        async with asyncio.timeout((self.deadline - datetime.now(UTC)).total_seconds()):
            rows = objects_value(await self.reader.request("GET", path))
        if not rows or len(rows) > 100:
            raise HarnessError("SELFTEST_FIXED_RECOVERY_VERSION_SET_INVALID")
        return rows

    async def _api(self, origin: CoreSource, reference: ApiNodeConfig, service: UUID) -> ApiSource:
        project = self.task.project_id
        if reference.api_version is None:
            raise HarnessError("SELFTEST_FIXED_RECOVERY_API_UNPINNED")
        versions = await self._get(
            f"/projects/{project}/apis/{reference.api_definition_id}/versions"
        )
        found = [row for row in versions if row["version"] == reference.api_version]
        if len(found) != 1:
            raise HarnessError("SELFTEST_FIXED_RECOVERY_API_VERSION_MISSING")
        version = APIVersionResponse.model_validate(found[0])
        expected = deepcopy(origin.request)
        path = expected.get("path")
        if isinstance(path, str):
            expected["path"] = path.replace("{batch_key}", "{{selftest_batch_key}}")
        spec = APIVersionInput.model_validate(expected)
        actual = APIVersionInput(
            **version.model_dump(exclude={"auth_kind", "auth_config"}),
            auth={"kind": version.auth_kind, "values": version.auth_config},
        )
        if (
            version.api_definition_id != reference.api_definition_id
            or version.version != reference.api_version
            or version.service_id != service
            or version.canonical_contract is None
            or version.contract_fingerprint != fingerprint_contract(version.canonical_contract)
            or canonical_digest(actual.model_dump(mode="json", exclude={"base_version"}))
            != canonical_digest(spec.model_dump(mode="json", exclude={"base_version"}))
        ):
            raise HarnessError("SELFTEST_FIXED_RECOVERY_API_SOURCE_MISMATCH")
        return ApiSource(
            project_id=project,
            api_definition_id=version.api_definition_id,
            api_version=version.version,
            contract_fingerprint=version.contract_fingerprint,
        )

    async def _sources(
        self,
        template: CoreWorkflow,
        source: CoreAPI,
        version: WorkflowVersionResponse,
        service: UUID,
    ) -> tuple[ApiSource, ...]:
        frozen = _api_nodes(template.published_definition)
        actual = _api_nodes(object_value(version.definition.model_dump(mode="json")))
        if set(frozen) != set(actual):
            raise HarnessError("SELFTEST_FIXED_RECOVERY_GRAPH_MISMATCH")
        origins = {item.source_id: item for item in (source, *source.additional_sources)}
        bindings: dict[UUID, ApiNodeConfig] = {}
        for key, original in frozen.items():
            if original.api_definition_id not in origins:
                raise HarnessError("SELFTEST_FIXED_RECOVERY_API_REFERENCE_UNKNOWN")
            current = actual[key]
            previous = bindings.get(original.api_definition_id)
            if previous is not None and (previous.api_definition_id, previous.api_version) != (
                current.api_definition_id,
                current.api_version,
            ):
                raise HarnessError("SELFTEST_FIXED_RECOVERY_API_REFERENCE_AMBIGUOUS")
            bindings[original.api_definition_id] = current
        if set(bindings) != set(origins) or len(
            {item.api_definition_id for item in bindings.values()}
        ) != len(bindings):
            raise HarnessError("SELFTEST_FIXED_RECOVERY_API_SET_MISMATCH")
        restored = tuple(
            [
                await self._api(origin, bindings[origin.source_id], service)
                for origin in (source, *source.additional_sources)
            ]
        )
        expected = deepcopy(template.published_definition)
        refs = dict(zip(origins, restored, strict=True))
        for group in [expected, *objects_value(expected.get("regions", []))]:
            for node in objects_value(group["nodes"]):
                if node["type"] == "api":
                    config = object_value(node["config"])
                    api = refs[UUID(str(config["api_definition_id"]))]
                    config.update(
                        api_definition_id=str(api.api_definition_id), api_version=api.api_version
                    )
        normalized = WorkflowDefinition.model_validate(expected).model_dump(
            mode="json", exclude_none=True
        )
        published = version.definition.model_dump(mode="json", exclude_none=True)
        if canonical_digest(normalized) != canonical_digest(published):
            raise HarnessError("SELFTEST_FIXED_RECOVERY_GRAPH_MISMATCH")
        return restored

    async def asset(
        self,
        asset: ScenarioAssets,
        source: CoreAPI,
        template: CoreWorkflow,
        mapping: InstallationMapping,
    ) -> FixedAsset:
        root = f"/projects/{self.task.project_id}"
        versions = await self._get(root + f"/workflows/{asset.workflow.id}/versions")
        found = [row for row in versions if row["version"] == asset.workflow.version]
        if len(found) != 1:
            raise HarnessError("SELFTEST_FIXED_RECOVERY_WORKFLOW_VERSION_MISSING")
        workflow = WorkflowVersionResponse.model_validate(found[0])
        if (
            workflow.workflow_id != asset.workflow.id
            or workflow.fingerprint != asset.workflow.fingerprint
            or canonical_digest(workflow.definition.model_dump(mode="json", exclude_none=True))
            != asset.workflow.fingerprint
        ):
            raise HarnessError("SELFTEST_FIXED_RECOVERY_WORKFLOW_FINGERPRINT_MISMATCH")
        sources = await self._sources(template, source, workflow, mapping.fixture_service_id)
        versions = await self._get(root + f"/test-cases/{asset.case.id}/versions")
        found = [row for row in versions if row["version"] == asset.case.version]
        if len(found) != 1:
            raise HarnessError("SELFTEST_FIXED_RECOVERY_CASE_VERSION_MISSING")
        case = TestCaseVersionResponse.model_validate(found[0])
        expected = TestCaseDefinitionInput(
            workflow_id=workflow.workflow_id,
            workflow_version=workflow.version,
            environment_id=mapping.environment_id,
            runtime_headers=template.case_runtime_headers,
        ).model_dump(mode="json", exclude_none=True)
        actual = case.definition.model_dump(mode="json", exclude_none=True)
        if (
            case.test_case_id != asset.case.id
            or case.fingerprint != asset.case.fingerprint
            or canonical_digest(actual) != asset.case.fingerprint
            or canonical_digest(actual) != canonical_digest(expected)
        ):
            raise HarnessError("SELFTEST_FIXED_RECOVERY_CASE_SOURCE_MISMATCH")
        primary = sources[0]
        return FixedAsset(
            scenario_id=asset.scenario_id,
            api_id=primary.api_definition_id,
            api_version=primary.api_version,
            api_fingerprint=primary.contract_fingerprint,
            workflow_id=workflow.workflow_id,
            workflow_version_id=workflow.id,
            workflow_version=workflow.version,
            workflow_fingerprint=workflow.fingerprint,
            case_id=case.test_case_id,
            case_version=case.version,
            case_fingerprint=case.fingerprint,
            api_sources=sources,
        )


async def recover_fixed_assets(
    reader: PublicAPI,
    task: AgentTaskResponse,
    pack: CorePack,
) -> PreparedFixedAssets:
    installation, batch, frozen = task.installation, task.batch, task.frozen_manifest
    mapping = installation.mapping
    if batch is None or frozen is None or mapping is None or installation.status != "ready":
        raise HarnessError("SELFTEST_FIXED_RECOVERY_INSTALLATION_NOT_READY")
    if (
        installation.project_id != task.project_id
        or batch.project_id != task.project_id
        or frozen.project_id != task.project_id
        or installation.id != batch.installation_id
        or installation.id != frozen.installation_id
        or task.task_id != batch.id
        or task.task_id != frozen.batch_id
        or task.binding_id != installation.binding_id
        or task.binding_id != batch.binding_id
        or task.binding_id != frozen.binding_id
        or pack.digest != installation.pack_digest
        or pack.digest != frozen.template.pack_digest
        or mapping.target_build_digest != task.builds.target
        or installation.environment_fingerprint != task.environment_fingerprint
        or frozen.environment_fingerprint != task.environment_fingerprint
        or frozen.binding_fingerprint != task.binding_fingerprint
        or frozen.builds != task.builds
    ):
        raise HarnessError("SELFTEST_FIXED_RECOVERY_IDENTITY_MISMATCH")
    expected = {(item, "default") for item in pack.manifest.scenario_ids}
    actual = [(item.scenario_id, item.variant_key) for item in mapping.assets]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise HarnessError("SELFTEST_FIXED_RECOVERY_ASSET_SET_MISMATCH")
    if len({item.workflow.id for item in mapping.assets}) != len(actual) or len(
        {item.case.id for item in mapping.assets}
    ) != len(actual):
        raise HarnessError("SELFTEST_FIXED_RECOVERY_ASSET_SET_MISMATCH")
    registered = {(item.scenario_id, item.variant_key): item for item in mapping.assets}
    recovery = FixedAssetRecovery(reader, task)
    assets = tuple(
        [
            await recovery.asset(
                registered[(source.scenario_id, "default")], source, template, mapping
            )
            for source, template in zip(pack.apis, pack.workflows, strict=True)
        ]
    )
    selected = {item.scenario_id for item in frozen.scenarios}
    return PreparedFixedAssets(
        project_id=task.project_id,
        environment_id=mapping.environment_id,
        service_id=mapping.fixture_service_id,
        batch_key=batch.batch_key,
        nonce=task.nonce,
        pack_digest=pack.digest,
        assets=tuple(asset for asset in assets if asset.scenario_id in selected),
    )
