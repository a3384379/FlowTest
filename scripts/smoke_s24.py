#!/usr/bin/env python3
"""Run the S24 Kafka, Schema Registry, WebSocket, and Workflow acceptance flow."""

from __future__ import annotations

import json
import os
import secrets
from typing import Any, cast
from urllib.request import Request, urlopen

from smoke_s4 import APIClient, SmokeConfig, _change_password
from smoke_s5 import _wait_for_completion

TOPIC = os.getenv("FLOWTEST_S24_TOPIC", "flowtest.orders")
REGISTRY_URL = os.getenv("FLOWTEST_S24_REGISTRY_URL", "http://localhost:8081")
INTERNAL_REGISTRY_URL = os.getenv("FLOWTEST_S24_INTERNAL_REGISTRY_URL", "http://redpanda:8081")
ORDER_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["id"],
    "properties": {"id": {"type": "string"}},
    "additionalProperties": False,
}


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json("POST", "/auth/login", {"email": config.email, "password": config.password})
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(cast(dict[str, Any], login["user"])["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-S24-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    try:
        result = _run_acceptance(client, config, token)
        print(json.dumps({"status": "passed", **result}))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


def _run_acceptance(client: APIClient, config: SmokeConfig, token: str) -> dict[str, str]:
    _verify_capabilities(client, token)
    correlation_id = f"order-{secrets.token_hex(8)}"
    project = client.json(
        "POST",
        "/projects",
        {"name": f"S24 Event {secrets.token_hex(5)}", "description": "S24 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    client.json(
        "PUT",
        f"/projects/{project_id}/security-policy",
        {
            "allowed_hosts": ["mock-target", "redpanda"],
            "allowed_private_cidrs": ["172.16.0.0/12"],
        },
        token=token,
    )
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": "Compose Mock", "base_url": config.target_url},
        token=token,
    )
    kafka_source = _create_kafka_source(client, token, project_id)
    websocket_source = _create_websocket_source(client, token, project_id)
    schema = _import_registry_schema(client, token, project_id, str(kafka_source["id"]))
    _verify_debug(
        client,
        token,
        project_id,
        str(kafka_source["id"]),
        str(websocket_source["id"]),
        str(schema["id"]),
        correlation_id,
    )
    api = _create_echo_api(client, token, project_id, correlation_id)
    workflow = client.json(
        "POST",
        f"/projects/{project_id}/workflows",
        {
            "name": "REST 到 Kafka/WebSocket 绑定",
            "description": "S24 event protocol acceptance",
            "definition": _workflow_definition(
                str(api["definition"]["id"]),
                str(kafka_source["id"]),
                str(websocket_source["id"]),
                str(schema["id"]),
            ),
        },
        token=token,
    )
    workflow_id = str(workflow["id"])
    client.json("POST", f"/projects/{project_id}/workflows/{workflow_id}/versions", token=token)
    started = client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/executions",
        {"environment_id": str(environment["id"])},
        token=token,
    )
    detail = _wait_for_completion(client, token, project_id, str(started["id"]))
    _verify_workflow(detail, kafka_source, websocket_source, schema, correlation_id)
    return {
        "project_id": project_id,
        "workflow_id": workflow_id,
        "execution_id": str(started["id"]),
    }


def _verify_capabilities(client: APIClient, token: str) -> None:
    flags = client.json("GET", "/v3/features", token=token)
    if not flags.get("capability_sdk") or not flags.get("event_protocols"):
        raise RuntimeError(f"S24 features are not enabled: {flags}")
    capabilities = client.json("GET", "/capabilities?page=1&page_size=100", token=token)
    keys = {(item["id"], item["version"]) for item in capabilities["items"]}
    required = {
        ("kafka.produce", "3.0.0"),
        ("kafka.consume", "3.0.0"),
        ("websocket.exchange", "3.0.0"),
    }
    if capabilities["total"] != 21 or not required.issubset(keys):
        raise RuntimeError("S24 event Capability manifests are missing")


def _create_kafka_source(client: APIClient, token: str, project_id: str) -> dict[str, Any]:
    return client.json(
        "POST",
        "/event-sources",
        {
            "project_id": project_id,
            "kind": "kafka",
            "name": "Compose Redpanda",
            "bootstrap_servers": ["redpanda:9092"],
            "schema_registry_url": INTERNAL_REGISTRY_URL,
        },
        token=token,
    )


def _create_websocket_source(client: APIClient, token: str, project_id: str) -> dict[str, Any]:
    return client.json(
        "POST",
        "/event-sources",
        {
            "project_id": project_id,
            "kind": "websocket",
            "name": "Compose WebSocket Echo",
            "websocket_url": "ws://mock-target:8080/ws/echo",
        },
        token=token,
    )


def _import_registry_schema(
    client: APIClient,
    token: str,
    project_id: str,
    source_id: str,
) -> dict[str, Any]:
    subject = f"{TOPIC}-value"
    _register_schema(subject)
    return client.json(
        "POST",
        f"/event-sources/{source_id}/schemas/import?project_id={project_id}",
        {"name": "Order JSON Schema", "subject": subject, "version": "latest"},
        token=token,
    )


def _register_schema(subject: str) -> None:
    schema = json.dumps(ORDER_SCHEMA, separators=(",", ":"))
    body = json.dumps({"schemaType": "JSON", "schema": schema}).encode()
    request = Request(
        f"{REGISTRY_URL.rstrip('/')}/subjects/{subject}/versions",
        data=body,
        headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read())
    if not isinstance(payload.get("id"), int):
        raise RuntimeError(f"Schema Registry did not return an ID: {payload}")


def _verify_debug(
    client: APIClient,
    token: str,
    project_id: str,
    kafka_source_id: str,
    websocket_source_id: str,
    schema_id: str,
    correlation_id: str,
) -> None:
    produced = client.json(
        "POST",
        f"/event-sources/{kafka_source_id}/kafka/produce",
        {
            "project_id": project_id,
            "topic": TOPIC,
            "value": {"id": correlation_id},
            "schema_id": schema_id,
            "correlation_header": "flowtest-correlation-id",
            "correlation_id": correlation_id,
        },
        token=token,
    )
    consumed = client.json(
        "POST",
        f"/event-sources/{kafka_source_id}/kafka/consume",
        {
            "project_id": project_id,
            "topic": TOPIC,
            "offset": "earliest",
            "maximum_messages": 1000,
            "schema_id": schema_id,
            "correlation_header": "flowtest-correlation-id",
            "correlation_id": correlation_id,
        },
        token=token,
    )
    exchanged = client.json(
        "POST",
        f"/event-sources/{websocket_source_id}/websocket/exchange",
        {
            "project_id": project_id,
            "message": {"id": correlation_id},
            "correlation_expression": "id",
            "correlation_value": correlation_id,
            "maximum_messages": 1,
        },
        token=token,
    )
    if produced["output"]["operation"] != "produce":
        raise RuntimeError("Kafka Produce debug did not acknowledge the message")
    if consumed["output"]["messages"][0]["value"]["id"] != correlation_id:
        raise RuntimeError("Kafka Consume debug did not decode the fixed JSON Schema")
    if exchanged["output"]["messages"][0]["id"] != correlation_id:
        raise RuntimeError("WebSocket Exchange did not return the correlated message")


def _create_echo_api(
    client: APIClient, token: str, project_id: str, correlation_id: str
) -> dict[str, Any]:
    return client.json(
        "POST",
        f"/projects/{project_id}/apis",
        {
            "name": "S24 绑定数据源",
            "description": "S24 REST source",
            "request": {
                "method": "POST",
                "path": "/echo",
                "query_parameters": [],
                "headers": {"Content-Type": "application/json"},
                "body_kind": "json",
                "body": {"id": correlation_id},
                "auth": {"kind": "none", "values": {}},
            },
        },
        token=token,
    )


def _workflow_definition(
    api_id: str,
    kafka_source_id: str,
    websocket_source_id: str,
    schema_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": "3.0",
        "nodes": [
            _node("start", "start", "开始", 0),
            {**_node("rest", "api", "REST 数据源", 180), "config": {"api_definition_id": api_id}},
            _event_node(
                "produce",
                "Kafka Produce",
                380,
                -100,
                "kafka.produce",
                {
                    "source_id": kafka_source_id,
                    "topic": TOPIC,
                    "value": {"id": "placeholder"},
                    "schema_id": schema_id,
                    "correlation_header": "flowtest-correlation-id",
                    "correlation_id": "placeholder",
                },
                [
                    {"input": "value.id", "expression": "node_outputs.rest.body.id"},
                    {"input": "correlation_id", "expression": "node_outputs.rest.body.id"},
                ],
            ),
            _event_node(
                "consume",
                "Kafka Consume",
                580,
                -100,
                "kafka.consume",
                {
                    "source_id": kafka_source_id,
                    "topic": TOPIC,
                    "offset": "earliest",
                    "maximum_messages": 1000,
                    "schema_id": schema_id,
                    "correlation_header": "flowtest-correlation-id",
                    "correlation_id": "placeholder",
                },
                [{"input": "correlation_id", "expression": "node_outputs.rest.body.id"}],
            ),
            _event_node(
                "websocket",
                "WebSocket Exchange",
                480,
                100,
                "websocket.exchange",
                {
                    "source_id": websocket_source_id,
                    "message": {"id": "placeholder"},
                    "maximum_messages": 1,
                },
                [{"input": "message.id", "expression": "node_outputs.rest.body.id"}],
            ),
            _node("end", "end", "结束", 800),
        ],
        "edges": [
            {"id": "start-rest", "source": "start", "target": "rest"},
            {"id": "rest-produce", "source": "rest", "target": "produce"},
            {"id": "produce-consume", "source": "produce", "target": "consume"},
            {"id": "consume-end", "source": "consume", "target": "end"},
            {"id": "rest-websocket", "source": "rest", "target": "websocket"},
            {"id": "websocket-end", "source": "websocket", "target": "end"},
        ],
        "settings": {"fail_fast": True, "concurrency": 20, "default_timeout_seconds": 30},
    }


def _event_node(
    node_id: str,
    name: str,
    x: int,
    y: int,
    capability_id: str,
    configuration: dict[str, Any],
    bindings: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        **_node(node_id, "capability", name, x, y),
        "capability_id": capability_id,
        "capability_version": "3.0.0",
        "configuration": configuration,
        "bindings": bindings,
    }


def _node(node_id: str, node_type: str, name: str, x: int, y: int = 0) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "name": name,
        "position": {"x": x, "y": y},
        "config": {},
    }


def _verify_workflow(
    detail: dict[str, Any],
    kafka_source: dict[str, Any],
    websocket_source: dict[str, Any],
    schema: dict[str, Any],
    correlation_id: str,
) -> None:
    if detail["execution"]["status"] != "passed":
        raise RuntimeError(f"S24 mixed event Workflow failed: {detail}")
    nodes = {item["node_id"]: item for item in detail["nodes"]}
    consumed = nodes["consume"]["result"]["output"]
    exchanged = nodes["websocket"]["result"]["output"]
    if consumed["messages"][0]["value"]["id"] != correlation_id:
        raise RuntimeError("REST response was not bound into Kafka Produce/Consume")
    if exchanged["messages"][0]["id"] != correlation_id:
        raise RuntimeError("REST response was not bound into WebSocket Exchange")
    snapshot = detail["execution"]["snapshot"]["event_nodes"]
    if snapshot["produce"]["source_hash"] != kafka_source["config_sha256"]:
        raise RuntimeError("Kafka source hash was not pinned")
    if snapshot["produce"]["schema_hash"] != schema["content_sha256"]:
        raise RuntimeError("Kafka Schema hash was not pinned")
    if snapshot["websocket"]["source_hash"] != websocket_source["config_sha256"]:
        raise RuntimeError("WebSocket source hash was not pinned")


if __name__ == "__main__":
    main()
