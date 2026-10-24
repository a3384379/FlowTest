"""Physical evidence retention is distinct from metadata and immutable sealed verdicts."""

from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from test_selftest_product_api import ProductContext
from test_selftest_product_api import observation as observation
from test_selftest_product_api import product as product
from test_tasking_api import TaskingTestContext
from test_tasking_api import tasking_context as tasking_context

from app.core import storage as storage_module
from app.core.storage import LocalObjectStorage, ObjectAvailability, ObjectStorage
from app.models.artifacts import Artifact
from app.schemas.self_tests import ArtifactReference
from app.services.artifacts import ArtifactService
from app.services.self_test_retention import SelfTestEvidenceAvailability


@pytest.fixture(autouse=True)
def owned_storage(
    tasking_context: TaskingTestContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> LocalObjectStorage:
    storage = LocalObjectStorage(tmp_path / "evidence")
    monkeypatch.setattr("app.services.artifacts.object_storage", storage)
    return storage


async def seal(product: ProductContext, observation: tuple[dict, dict]) -> tuple[dict, dict]:
    batch, receipt = observation
    assert batch["plan_run_ids"]
    result = await product.post(
        f"/api/v1/ci/projects/{product.project_id}/self-test-runs/{batch['id']}/verification",
        receipt,
        machine="o",
    )
    assert result["verdict"] == result["sealed_verdict"] == "passed"
    return batch, receipt


async def test_physical_object_retention_blocks_current_verdict_without_deleting_metadata(
    product: ProductContext,
    observation: tuple[dict, dict],
    owned_storage: LocalObjectStorage,
) -> None:
    batch, receipt = await seal(product, observation)
    identifier = UUID(receipt["artifacts"][0]["id"])
    async with product.native.session_maker() as session:
        artifact = await session.get(Artifact, identifier)
        assert artifact is not None
        key = artifact.object_key
    await owned_storage.delete(key=key)
    async with product.native.session_maker() as session:
        assert await session.get(Artifact, identifier) is not None
    current = await product.get(product.root + f"/runs/{batch['id']}")
    assert (current["verdict"], current["readiness"], current["evidence_integrity"]) == (
        "blocked",
        "blocked",
        "expired",
    )
    assert current["sealed_verdict"] == "passed"
    assert "SELFTEST_EVIDENCE_EXPIRED" in current["reason_codes"]
    rows = await product.get(product.root + f"/runs/{batch['id']}/scenarios")
    assert all(row["verification_status"] == "matched" for row in rows["items"])


async def test_transient_probe_failure_is_unavailable_and_does_not_rewrite_history(
    product: ProductContext,
    observation: tuple[dict, dict],
    owned_storage: LocalObjectStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch, _ = await seal(product, observation)

    async def unavailable(*, key: str) -> ObjectAvailability:
        return ObjectAvailability.UNAVAILABLE

    with monkeypatch.context() as offline:
        offline.setattr(owned_storage, "availability", unavailable)
        current = await product.get(product.root + f"/runs/{batch['id']}")
    assert (current["verdict"], current["evidence_integrity"]) == ("blocked", "missing")
    assert current["sealed_verdict"] == "passed"
    assert "SELFTEST_EVIDENCE_UNAVAILABLE" in current["reason_codes"]
    assert "SELFTEST_EVIDENCE_EXPIRED" not in current["reason_codes"]
    restored = await product.get(product.root + f"/runs/{batch['id']}")
    assert restored["verdict"] == restored["sealed_verdict"] == "passed"


async def test_sealed_status_projection_does_not_download_evidence_content(
    product: ProductContext,
    observation: tuple[dict, dict],
    owned_storage: LocalObjectStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch, _ = await seal(product, observation)

    async def forbidden_download(*, key: str) -> None:
        pytest.fail("Status projection must use HEAD/stat, not download evidence")

    monkeypatch.setattr(owned_storage, "get", forbidden_download)
    current = await product.get(product.root + f"/runs/{batch['id']}")
    assert current["verdict"] == "passed" and current["evidence_integrity"] == "complete"


async def test_many_batch_projections_share_one_request_probe_count_budget() -> None:
    artifacts = AsyncMock(spec=ArtifactService)
    artifacts.availability.return_value = ObjectAvailability.AVAILABLE
    budget = SelfTestEvidenceAvailability(cast(ArtifactService, artifacts))
    project = uuid4()
    for _ in range(33):
        refs = tuple(
            ArtifactReference(id=uuid4(), sha256="a" * 64, kind="evidence") for _ in range(3)
        )
        assert await budget.inspect(project, refs) is ObjectAvailability.AVAILABLE
    refs = tuple(ArtifactReference(id=uuid4(), sha256="a" * 64, kind="evidence") for _ in range(3))
    assert await budget.inspect(project, refs) is ObjectAvailability.UNAVAILABLE
    assert artifacts.availability.await_count == 100
    assert await budget.inspect(project, refs) is ObjectAvailability.UNAVAILABLE
    assert artifacts.availability.await_count == 100


async def test_probe_deadline_is_shared_across_batches_and_known_refs_are_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import self_test_retention

    clock = [10.0]
    artifacts = AsyncMock(spec=ArtifactService)

    async def available(**_: object) -> ObjectAvailability:
        clock[0] += 6
        return ObjectAvailability.AVAILABLE

    artifacts.availability.side_effect = available
    monkeypatch.setattr(self_test_retention, "monotonic", lambda: clock[0])
    budget = SelfTestEvidenceAvailability(cast(ArtifactService, artifacts))
    project = uuid4()
    first = ArtifactReference(id=uuid4(), sha256="a" * 64, kind="evidence")
    second = first.model_copy(update={"id": uuid4()})
    assert await budget.inspect(project, (first,)) is ObjectAvailability.AVAILABLE
    assert await budget.inspect(project, (second,)) is ObjectAvailability.UNAVAILABLE
    assert await budget.inspect(project, (first,)) is ObjectAvailability.AVAILABLE
    assert artifacts.availability.await_count == 1


async def test_probe_timeout_never_counts_as_available(monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = AsyncMock(spec=ArtifactService)
    artifacts.availability.side_effect = TimeoutError
    budget = SelfTestEvidenceAvailability(cast(ArtifactService, artifacts))
    reference = ArtifactReference(id=uuid4(), sha256="a" * 64, kind="evidence")
    assert await budget.inspect(uuid4(), (reference,)) is ObjectAvailability.UNAVAILABLE


async def test_local_probe_checks_read_permission_without_reading_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalObjectStorage(tmp_path / "local")
    await storage.put(
        key="owned.json", content=b"private-synthetic-body", content_type="application/json"
    )
    assert await storage.availability(key="owned.json") is ObjectAvailability.AVAILABLE
    assert await storage.availability(key="missing.json") is ObjectAvailability.MISSING

    def denied(*_: object) -> int:
        raise PermissionError("synthetic permission denial")

    monkeypatch.setattr(storage_module.os, "open", denied)
    assert await storage.availability(key="owned.json") is ObjectAvailability.UNAVAILABLE


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (None, ObjectAvailability.AVAILABLE),
        (ClientError({"Error": {"Code": "NoSuchKey"}}, "HeadObject"), ObjectAvailability.MISSING),
        (ClientError({"Error": {"Code": "404"}}, "HeadObject"), ObjectAvailability.MISSING),
        (
            ClientError({"Error": {"Code": "AccessDenied"}}, "HeadObject"),
            ObjectAvailability.UNAVAILABLE,
        ),
        (
            EndpointConnectionError(endpoint_url="http://owned-storage.invalid"),
            ObjectAvailability.UNAVAILABLE,
        ),
    ],
)
async def test_s3_probe_uses_only_bounded_head_and_distinguishes_missing_from_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception | None,
    expected: ObjectAvailability,
) -> None:
    calls: list[tuple[str, str]] = []

    class HeadOnly:
        def head_object(self, *, Bucket: str, Key: str) -> dict:
            calls.append((Bucket, Key))
            if error is not None:
                raise error
            return {"ContentLength": 999999999}

    def client(*, config: object) -> HeadOnly:
        assert config.connect_timeout == config.read_timeout == 1
        assert config.retries["max_attempts"] == 0
        return HeadOnly()

    monkeypatch.setattr(storage_module, "create_s3_client", client)
    assert await ObjectStorage().availability(key="owned-evidence") is expected
    assert len(calls) == 1
