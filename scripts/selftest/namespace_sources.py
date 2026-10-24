"""Resolve only server-frozen namespace aliases for assisted product batches."""

from __future__ import annotations

from pydantic import JsonValue
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, object_value

from app.schemas.self_tests import BatchResponse, GenerationSummary


def frozen_namespace_keys(
    batch: BatchResponse, generation: GenerationSummary, *, assisted: bool
) -> dict[str, str]:
    snapshot = batch.resource_snapshot
    expected = [(item.scenario_id, item.variant_key) for item in batch.expected_scenario_set]
    sources = {(item.scenario_id, item.variant_key): item for item in generation.sources}
    if (
        generation.batch_id != batch.id
        or snapshot is None
        or batch.resource_digest is None
        or len(sources) != len(generation.sources)
        or set(sources) != set(expected)
    ):
        raise HarnessError("SELFTEST_NAMESPACE_SOURCE_INCOMPLETE")
    cases = {(item.scenario_id, item.variant_key): item for item in snapshot.cases}
    if len(cases) != len(snapshot.cases) or set(cases) != set(expected):
        raise HarnessError("SELFTEST_NAMESPACE_SOURCE_INCOMPLETE")
    resources: list[JsonValue] = []
    keys: dict[str, str] = {}
    for key in expected:
        source, case = sources[key], cases[key]
        assets = source.model_dump(
            mode="json", include={"scenario_id", "variant_key", "workflow", "case"}
        )
        if source.workflow != case.workflow or source.case != case.case:
            raise HarnessError("SELFTEST_NAMESPACE_SOURCE_ASSETS_CHANGED")
        namespace = source.fixture_batch_key or batch.batch_key
        if (
            source.assisted is not None
            and source.fixture_batch_key is None
            and source.scenario_id != "ST-MCP-023"
        ):
            raise HarnessError("SELFTEST_NAMESPACE_ASSISTED_KEY_MISSING")
        if source.scenario_id in keys and keys[source.scenario_id] != namespace:
            raise HarnessError("SELFTEST_NAMESPACE_SOURCE_ALIAS_CONFLICT")
        keys[source.scenario_id] = namespace
        resources.append(
            {
                "scenario_id": key[0],
                "variant_key": key[1],
                "assets": assets,
                "source_digest": canonical_digest(object_value(source.model_dump(mode="json"))),
            }
        )
    actual = canonical_digest(
        {
            "binding_fingerprint": batch.binding_fingerprint,
            "environment_fingerprint": batch.environment_fingerprint,
            "resources": resources,
            "snapshot": object_value(snapshot.model_dump(mode="json")),
        }
    )
    if actual != batch.resource_digest:
        raise HarnessError("SELFTEST_NAMESPACE_SOURCE_DIGEST_MISMATCH")
    if assisted and any(source.assisted is None for source in generation.sources):
        raise HarnessError("SELFTEST_NAMESPACE_ASSISTED_SOURCE_MISSING")
    return keys
