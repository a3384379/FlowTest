from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from test_contract_hub import (
    ADMIN_PASSWORD,
    ContractHubContext,
    FakeVerifier,
    _create_project,
    _deployment_check,
    _login_headers,
    _pact_document,
    _upload_pact,
)
from test_contract_hub import contract_hub_context as contract_hub_context

from app.domain.access import ProjectRole
from app.models.access import AuditLog, Project, ProjectMember, User
from app.models.contracts import ContractRun, GeneratedContractCase, PactContractVersion
from app.models.organizations import OrganizationMember


@pytest.mark.asyncio
async def test_pact_reference_catalog_search_pages_and_exact_detail(
    contract_hub_context: ContractHubContext,
) -> None:
    client = contract_hub_context.client
    headers = await _login_headers(client)
    project_id = await _create_project(client, headers)
    root = f"/api/v1/projects/{project_id}/contract-hub"
    imported = await _upload_pact(client, headers, root)
    assert imported.status_code == 201, imported.text
    pact_id = imported.json()["id"]
    async with contract_hub_context.sessions() as session:
        source = await session.get(PactContractVersion, UUID(pact_id))
        assert source is not None
        session.add_all(
            [
                PactContractVersion(
                    project_id=source.project_id,
                    consumer_service_id=source.consumer_service_id,
                    provider_service_id=source.provider_service_id,
                    consumer_version=f"version-{index:03}",
                    pact_specification_version=source.pact_specification_version,
                    source_type="upload",
                    source_name=f"契约_{index:03}",
                    content_sha256=source.content_sha256,
                    contract_document=source.contract_document,
                    interaction_count=1,
                    created_by_id=source.created_by_id,
                    created_at=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=index),
                )
                for index in range(104)
            ]
        )
        await session.commit()
    first = await client.get(f"{root}/pacts", headers=headers, params={"page_size": 100})
    second = await client.get(
        f"{root}/pacts", headers=headers, params={"page_size": 100, "page": 2}
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 105
    assert len(first.json()["items"]) == 100 and len(second.json()["items"]) == 5
    assert len({item["id"] for item in first.json()["items"] + second.json()["items"]}) == 105
    for search in ("契约_103", "version-103"):
        result = await client.get(f"{root}/pacts", headers=headers, params={"search": search})
        assert result.json()["total"] == 1
        assert result.json()["items"][0]["consumer_version"] == "version-103"
    provider = await client.get(f"{root}/pacts", headers=headers, params={"search": "Orders"})
    assert provider.json()["total"] == 105
    literal = await client.get(f"{root}/pacts", headers=headers, params={"search": "%"})
    assert literal.json()["total"] == 0
    outside = await client.get(f"{root}/pacts", headers=headers, params={"page": 1000})
    assert outside.json()["items"] == [] and outside.json()["total"] == 105
    detail = await client.get(f"{root}/pacts/{pact_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["contract"]["id"] == pact_id
    assert detail.json()["contract_document"]["interactions"][0]["response"]["body"] == {
        "status": "ok"
    }
    invalid = await client.get(f"{root}/pacts", headers=headers, params={"search": "x" * 201})
    assert invalid.status_code == 422 and invalid.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_contract_runs_and_candidates_reach_past_first_hundred_and_filter_reviews(
    contract_hub_context: ContractHubContext,
) -> None:
    client = contract_hub_context.client
    headers = await _login_headers(client)
    project_id = await _create_project(client, headers)
    async with contract_hub_context.sessions() as session:
        actor_id = await session.scalar(select(User.id).where(User.is_system_admin.is_(True)))
        assert actor_id is not None
        runs = [
            ContractRun(
                project_id=UUID(project_id),
                source_name=f"分析_{index:03}",
                source_type="upload",
                source_sha256="a" * 64,
                schema_document={},
                diff_summary={},
                coverage={},
                created_by_id=actor_id,
                created_at=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=index),
            )
            for index in range(105)
        ]
        session.add_all(runs)
        await session.flush()
        run_id = runs[0].id
        session.add_all(
            [
                GeneratedContractCase(
                    contract_run_id=run_id,
                    operation_key=f"operation-{index}",
                    operation_id=f"op-{index}",
                    method="GET",
                    path=f"/orders/{index:03}",
                    generation_kind="example",
                    name=f"候选{index}",
                    definition={"nodes": []},
                    review_status="pending" if index < 103 else "rejected",
                )
                for index in range(105)
            ]
        )
        await session.commit()
    root = f"/api/v1/projects/{project_id}/contract-runs"
    tail = await client.get(root, headers=headers, params={"page": 6, "page_size": 20})
    assert tail.status_code == 200 and tail.json()["total"] == 105
    assert len(tail.json()["items"]) == 5
    exact = await client.get(root, headers=headers, params={"search": "分析_000"})
    assert exact.json()["total"] == 1 and exact.json()["items"][0]["id"] == str(run_id)
    literal = await client.get(root, headers=headers, params={"search": "%"})
    assert literal.json()["total"] == 0
    candidates = f"{root}/{run_id}/generated-cases"
    tail = await client.get(
        candidates, headers=headers, params={"page": 6, "page_size": 20, "review_status": "pending"}
    )
    assert tail.status_code == 200 and tail.json()["total"] == 103
    assert len(tail.json()["items"]) == 3
    assert all(item["review_status"] == "pending" for item in tail.json()["items"])


async def _viewer_headers(context: ContractHubContext, project_id: str) -> dict[str, str]:
    async with context.sessions() as session:
        admin = await session.scalar(select(User).where(User.is_system_admin.is_(True)))
        project = await session.get(Project, UUID(project_id))
        assert admin is not None and project is not None
        viewer = User(
            email="contract-viewer@example.test",
            display_name="契约只读成员",
            password_hash=admin.password_hash,
            is_active=True,
            requires_password_change=False,
        )
        session.add(viewer)
        await session.flush()
        session.add(
            OrganizationMember(
                organization_id=project.organization_id, user_id=viewer.id, role="member"
            )
        )
        session.add(
            ProjectMember(project_id=project.id, user_id=viewer.id, role=ProjectRole.VIEWER)
        )
        await session.commit()
    login = await context.client.post(
        "/api/v1/auth/login", json={"email": viewer.email, "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_frozen_evidence_reads_are_scoped_viewer_safe_and_never_reverify(
    contract_hub_context: ContractHubContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = contract_hub_context.client
    headers = await _login_headers(client)
    project_id = await _create_project(client, headers)
    other_project = await _create_project(client, headers)
    root = f"/api/v1/projects/{project_id}/contract-hub"
    imported = await _upload_pact(client, headers, root)
    pact_id = imported.json()["id"]
    verification = await client.post(
        f"{root}/pacts/{pact_id}/verify",
        headers=headers,
        json={"provider_version": "1.0", "target_base_url": "https://fail.example.test"},
    )
    assert verification.status_code == 201, verification.text
    verification_id = verification.json()["id"]
    check = await _deployment_check(
        client, headers, root, imported.json()["provider_service_id"], "1.0"
    )
    assert check.status_code == 201 and check.json()["decision"] == "unsafe"
    newer = await client.post(
        f"{root}/pacts",
        headers=headers,
        files={
            "document": (
                "new.json",
                _pact_document().replace(b'"ok"', b'"changed"'),
                "application/json",
            )
        },
        data={"consumer_version": "web-2.0.0"},
    )
    assert newer.status_code == 201 and newer.json()["id"] != pact_id
    viewer_headers = await _viewer_headers(contract_hub_context, project_id)

    async def forbidden_external_call(*args: object, **kwargs: object) -> None:
        pytest.fail("reading evidence must not invoke a provider or broker")

    monkeypatch.setattr(FakeVerifier, "verify", forbidden_external_call)
    monkeypatch.setattr(type(contract_hub_context.broker), "fetch_pact", forbidden_external_call)
    async with contract_hub_context.sessions() as session:
        audit_count = await session.scalar(select(func.count()).select_from(AuditLog))
    detail = await client.get(f"{root}/verifications/{verification_id}", headers=viewer_headers)
    assert detail.status_code == 200, detail.text
    evidence = detail.json()
    assert evidence["actual_response_available"] is False
    assert evidence["verification"]["results"][0]["mismatch_codes"] == ["BODY_MISMATCH"]
    assert evidence["pact"]["contract"]["id"] == pact_id
    assert evidence["pact"]["contract_document"]["interactions"][0]["response"]["body"] == {
        "status": "ok"
    }
    paths = [
        f"pacts/{pact_id}",
        f"verifications/{verification_id}",
        f"deployment-checks/{check.json()['id']}",
    ]
    for path in paths:
        response = await client.get(f"{root}/{path}", headers=viewer_headers)
        assert response.status_code == 200
        hidden = await client.get(
            f"/api/v1/projects/{other_project}/contract-hub/{path}", headers=headers
        )
        assert hidden.status_code == 404 and hidden.json()["error"]["trace_id"]
    rejected = await client.post(
        f"{root}/pacts/{pact_id}/verify",
        headers=viewer_headers,
        json={"provider_version": "2.0", "target_base_url": "https://provider.example.test"},
    )
    assert rejected.status_code == 403
    async with contract_hub_context.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == audit_count
