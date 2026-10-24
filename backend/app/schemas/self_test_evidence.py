"""Only the existing authorized synthetic create/patch name capture crosses O's API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.self_tests import APISourceReference, Digest, Identity, SelfTestDTO


class SyntheticNameField(SelfTestDTO):
    purpose: Literal["create", "patch"]
    node_id: Identity
    field: Literal["body.name"] = "body.name"
    api_source: APISourceReference
    actual: str = Field(min_length=1, max_length=200)


class SyntheticNameEvidence(SelfTestDTO):
    batch_id: UUID
    batch_key: Identity
    scenario_id: Literal["ST-MCP-023"] = "ST-MCP-023"
    project_id: UUID
    execution_id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    environment_id: UUID
    status: Literal["passed", "failed", "cancelled"]
    snapshot_digest: Digest
    fields: tuple[SyntheticNameField, ...] = Field(min_length=2, max_length=2)
    observed_at: datetime
