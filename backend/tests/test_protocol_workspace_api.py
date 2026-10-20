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


@pytest.mark.asyncio
async def test_message_schema_read_is_scoped_to_kafka_and_project(
    event_client: tuple[AsyncClient, UUID],
) -> None:
    client, project_id = event_client
    headers = await event_headers(client)
    source = await client.post(
        "/api/v1/event-sources",
        headers=headers,
        json={
            "project_id": str(project_id),
            "kind": "kafka",
            "name": "消息目录源",
            "bootstrap_servers": ["broker.example.test:9092"],
        },
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["id"]
    schema = await client.post(
        f"/api/v1/event-sources/{source_id}/schemas",
        headers=headers,
        params={"project_id": str(project_id)},
        json={
            "name": "页外消息契约",
            "schema_format": "json_schema",
            "schema": '{"type":"object","properties":{"id":{"type":"string"}}}',
        },
    )
    assert schema.status_code == 201, schema.text
    path = f"/api/v1/event-sources/{source_id}/schemas/{schema.json()['id']}"
    assert (await client.get(path, params={"project_id": str(project_id)})).status_code == 401
    response = await client.get(path, headers=headers, params={"project_id": str(project_id)})
    assert response.status_code == 200 and response.json() == schema.json()
    foreign = await client.get(path, headers=headers, params={"project_id": str(uuid4())})
    assert foreign.status_code == 404 and foreign.json()["error"]["trace_id"]
    wrong = await client.get(
        path.replace(source_id, str(uuid4())),
        headers=headers,
        params={"project_id": str(project_id)},
    )
    assert wrong.status_code == 404 and wrong.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_stored_structure_and_source_are_bounded_scoped_and_read_only(
    protocol_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = protocol_client
    headers = await _login_headers(client)
    project = await client.post("/api/v1/projects", headers=headers, json={"name": "结构浏览项目"})
    project_id = project.json()["id"]
    source = "#" + "source-prefix" * 6000 + "\n" + GRAPHQL_SDL
    created = await client.post(
        "/api/v1/graphql/schemas",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "结构固定版本",
            "source_format": "graphql_sdl",
            "sdl": source,
        },
    )
    assert created.status_code == 201, created.text
    artifact = created.json()
    path = f"/api/v1/protocol-assets/{artifact['id']}/structure"
    params = {"project_id": project_id, "protocol": "graphql"}

    def forbidden(*args: object, **kwargs: object) -> Never:
        raise AssertionError("Contract browsing must not contact targets or decrypt credentials")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(SecretBox, "decrypt", forbidden)
    assert (await client.get(path, params=params)).status_code == 401
    result = await client.get(path, params=params, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["content_sha256"] == artifact["content_sha256"]
    assert result.json()["version"] == artifact["version"]
    assert result.json()["view"]["entries"][0]["type_label"] == "Query"
    field = await client.get(
        path, params={**params, "node": "field:Query.user", "limit": 1}, headers=headers
    )
    assert field.status_code == 200 and field.json()["view"]["total"] == 2
    assert field.json()["view"]["example"]["variables"] == {"id": "example-id"}
    document = await client.get(path, params={**params, "node": "source"}, headers=headers)
    assert document.json()["view"]["notice"] and len(document.json()["view"]["document"]) == 65536
    assert document.json()["view"]["document_format"] == "text"
    for override, status in [
        ({"node": "type:absent"}, 404),
        ({"protocol": "grpc"}, 404),
        ({"project_id": str(uuid4())}, 404),
        ({"limit": 101}, 422),
    ]:
        response = await client.get(path, params={**params, **override}, headers=headers)
        assert response.status_code == status, response.text
        assert response.json()["error"]["trace_id"]
    locate_path = f"/api/v1/graphql/schemas/{artifact['id']}/locate-error"
    locate_input = {
        "project_id": project_id,
        "operation": 'query Q { found: user(id:"42") { id } }',
        "operation_name": "Q",
        "path": ["found", "id"],
    }
    located = await client.post(locate_path, headers=headers, json=locate_input)
    assert located.status_code == 200 and located.json()["node"] == "field:Query.user"
    assert located.json()["content_sha256"] == artifact["content_sha256"]
    for override, status in [
        ({"project_id": str(uuid4())}, 404),
        ({"path": ["missing"]}, 422),
        ({"path": ["found"] * 21}, 422),
    ]:
        response = await client.post(
            locate_path, headers=headers, json={**locate_input, **override}
        )
        assert response.status_code == status and response.json()["error"]["trace_id"]
    unchanged = await client.get(
        f"/api/v1/graphql/schemas/{artifact['id']}",
        params={"project_id": project_id},
        headers=headers,
    )
    assert unchanged.json() == artifact
