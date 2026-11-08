"""No browser actor may create or expand negative observation authority."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query

from app.api.dependencies import SessionDependency
from app.api.v1.endpoints.self_tests import Agent, Config
from app.schemas.self_test_probes import ProbeCursor, ProbeInventory
from app.schemas.self_tests import Digest
from app.services.self_test_access import self_test_error
from app.services.self_test_probes import NegativeProbeService

router = APIRouter(prefix="/agent/self-test-probes")


@router.get("/{probe_id}/inventory", response_model=ProbeInventory)
async def inventory(
    probe_id: UUID,
    principal: Agent,
    session: SessionDependency,
    config: Config,
    nonce: Annotated[
        str | None, Header(alias="X-SelfTest-Probe-Nonce", min_length=32, max_length=200)
    ] = None,
    manifest_digest: Annotated[Digest | None, Header(alias="X-SelfTest-Manifest-Digest")] = None,
    cursor: Annotated[ProbeCursor | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
) -> ProbeInventory:
    if nonce is None or manifest_digest is None:
        raise self_test_error("SELFTEST_PROBE_IDENTITY_MISSING", "需要探针 nonce 与清单摘要", 403)
    return await NegativeProbeService(session, config).inventory(
        principal, probe_id, nonce, manifest_digest, cursor=cursor, page_size=page_size
    )
