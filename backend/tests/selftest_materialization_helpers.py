"""Explicit synthetic observer acknowledgements for public API contract fixtures.

These tests do not claim a real H/O manifest or human/model acceptance.
"""

from app.domain.self_tests import document_digest


async def finalize_fixture_materialization(context, path, payload, *, machine="h"):
    staged = await context.post(path, payload, machine=machine)
    assert staged["generation_stage"] == "publishing"
    assert not staged["actions"]["can_execute"]
    return await context.post(
        path,
        {
            **payload,
            "stage": "finalize",
            "observer_manifest_digest": document_digest(
                {"synthetic_observer_manifest": staged["resource_digest"]}
            ),
            "observer_selection_digest": document_digest(staged["resource_snapshot"]),
        },
        machine=machine,
    )
