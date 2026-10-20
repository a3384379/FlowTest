import socket
from typing import Never
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from test_event_protocols import _login_headers as event_headers
from test_event_protocols import event_client as event_client
from test_multi_protocol import GRAPHQL_SDL, PROTO_SOURCE, _login_headers
from test_multi_protocol import protocol_client as protocol_client

from app.core.encryption import SecretBox


@pytest.mark.asyncio
async def test_schema_by_id_is_project_and_protocol_scoped_and_does_not_execute(
    protocol_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = protocol_client
    headers = await _login_headers(client)
    project = await client.post("/api/v1/projects", headers=headers, json={"name": "协议定位项目"})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    graphql = await client.post(
        "/api/v1/graphql/schemas",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "精确GraphQL版本",
            "source_format": "graphql_sdl",
            "sdl": GRAPHQL_SDL,
        },
    )
    grpc = await client.post(
        "/api/v1/grpc/descriptors",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "精确gRPC版本",
            "source_format": "proto_source",
            "entrypoint": "echo.proto",
            "files": [{"name": "echo.proto", "content": PROTO_SOURCE}],
        },
    )
    assert graphql.status_code == grpc.status_code == 201

    def forbidden(*args: object, **kwargs: object) -> Never:
        raise AssertionError("Stored protocol reads must not perform DNS or decrypt credentials")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(SecretBox, "decrypt", forbidden)
    for route, value in [("graphql/schemas", graphql.json()), ("grpc/descriptors", grpc.json())]:
        path = f"/api/v1/{route}/{value['id']}"
        assert (await client.get(path, params={"project_id": project_id})).status_code == 401
        response = await client.get(path, headers=headers, params={"project_id": project_id})
        assert response.status_code == 200, response.text
        assert response.json() == value
        assert (
            not {"canonical_content", "source_content", "secret", "password"}
            & response.json().keys()
        )
        foreign = await client.get(path, headers=headers, params={"project_id": str(uuid4())})
        assert foreign.status_code == 404 and foreign.json()["error"]["trace_id"]
    mismatch = await client.get(
        f"/api/v1/graphql/schemas/{grpc.json()['id']}",
        headers=headers,
        params={"project_id": project_id},
    )
    assert mismatch.status_code == 404 and mismatch.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_event_source_by_id_validates_kind_and_project(
    event_client: tuple[AsyncClient, UUID],
) -> None:
    client, project_id = event_client
    headers = await event_headers(client)
    created = await client.post(
        "/api/v1/event-sources",
        headers=headers,
        json={
            "project_id": str(project_id),
            "kind": "websocket",
            "name": "页外WebSocket源",
            "websocket_url": "wss://events.example.test/ws",
        },
    )
    assert created.status_code == 201, created.text
    identifier = created.json()["id"]
    path = f"/api/v1/event-sources/{identifier}"
    response = await client.get(
        path, headers=headers, params={"project_id": str(project_id), "kind": "websocket"}
    )
    assert response.status_code == 200, response.text
    assert response.json() == created.json()
    wrong_kind = await client.get(
        path, headers=headers, params={"project_id": str(project_id), "kind": "kafka"}
    )
    assert wrong_kind.status_code == 404 and wrong_kind.json()["error"]["trace_id"]
    missing = await client.get(path, headers=headers, params={"project_id": str(uuid4())})
    assert missing.status_code == 404 and missing.json()["error"]["trace_id"]
