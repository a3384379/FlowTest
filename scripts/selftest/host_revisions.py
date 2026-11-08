"""Explicit signed requests for human revisions; this path never launches a model."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator
from scripts.selftest.contracts import Contract, Identity


class AssistedSelection(Contract):
    scenario_id: Identity
    variant_key: Identity = "default"
    workflow_proposal_id: UUID
    case_proposal_id: UUID
    case_item_id: UUID
    editor_id: UUID
    reason: str = Field(min_length=1, max_length=2000)


class AssistedRequest(Contract):
    before_batch_id: UUID
    selections: tuple[AssistedSelection, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_revisions(self) -> AssistedRequest:
        keys = [(item.scenario_id, item.variant_key) for item in self.selections]
        if len(keys) != len(set(keys)):
            raise ValueError("assisted requests cannot duplicate a selected scenario")
        return self
