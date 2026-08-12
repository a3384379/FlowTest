#!/usr/bin/env python3
"""Run the S23 multi-protocol import, debug, binding, and snapshot acceptance flow."""

from __future__ import annotations

import json
import secrets
from typing import Any, cast
from urllib.parse import urlsplit

from smoke_s4 import APIClient, SmokeConfig, _change_password
from smoke_s5 import _wait_for_completion

GRAPHQL_SDL = """
type Query { user(id: ID!): User! }
type Mutation { renameUser(id: ID!, name: String!): User! }
type User { id: ID!, name: String! }
"""


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json("POST", "/auth/login", {"email": config.email, "password": config.password})
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(cast(dict[str, Any], login["user"])["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-S23-{secrets.token_urlsafe(18)}"
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
    project = client.json(
        "POST",
        "/projects",
        {"name": f"S23 Protocol {secrets.token_hex(5)}", "description": "S23 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    target_host = urlsplit(config.target_url).hostname or "mock-target"
    client.json(
        "PUT",
        f"/projects/{project_id}/security-policy",
        {
            "allowed_hosts": [target_host, "grpc-target"],
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
    graphql = _create_graphql(client, token, project_id)
    grpc_descriptor = _import_grpc_reflection(client, token, project_id)
    _verify_debug(client, config, token, project_id, graphql, grpc_descriptor)
    api = _create_echo_api(client, token, project_id)
    workflow = client.json(
        "POST",
        f"/projects/{project_id}/workflows",
        {
            "name": "REST 到 GraphQL/gRPC 绑定",
            "description": "S23 mixed protocol acceptance",
            "definition": _workflow_definition(
                str(api["definition"]["id"]),
                str(graphql["id"]),
                str(grpc_descriptor["id"]),
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
    _verify_workflow(detail, graphql, grpc_descriptor)
    return {
        "project_id": project_id,
        "workflow_id": workflow_id,
        "execution_id": str(started["id"]),
    }


def _verify_capabilities(client: APIClient, token: str) -> None:
    flags = client.json("GET", "/v3/features", token=token)
    if not flags.get("capability_sdk") or not flags.get("multi_protocol"):
        raise RuntimeError(f"S23 features are not enabled: {flags}")
    capabilities = client.json("GET", "/capabilities?page=1&page_size=100", token=token)
    keys = {(item["id"], item["version"]) for item in capabilities["items"]}
    required = {("graphql.request", "3.0.0"), ("grpc.call", "3.0.0")}
    if capabilities["total"] < 14 or not required.issubset(keys):
        raise RuntimeError("S23 protocol Capability manifests are missing")


def _create_graphql(client: APIClient, token: str, project_id: str) -> dict[str, Any]:
    return client.json(
        "POST",
        "/graphql/schemas",
        {
            "project_id": project_id,
            "name": "Compose GraphQL",
            "source_format": "graphql_sdl",
            "sdl": GRAPHQL_SDL,
        },
        token=token,
    )


def _import_grpc_reflection(client: APIClient, token: str, project_id: str) -> dict[str, Any]:
    return client.json(
        "POST",
        "/grpc/descriptors/reflection",
        {
            "project_id": project_id,
            "name": "Compose gRPC Reflection",
            "endpoint": "grpc-target:50051",
            "tls_mode": "plaintext",
            "timeout_seconds": 30,
        },
        token=token,
    )


def _verify_debug(
    client: APIClient,
    config: SmokeConfig,
    token: str,
    project_id: str,
    graphql: dict[str, Any],
    grpc_descriptor: dict[str, Any],
) -> None:
    graphql_result = client.json(
        "POST",
        "/graphql/execute",
        {
            "project_id": project_id,
            "schema_id": graphql["id"],
            "endpoint": f"{config.target_url}/graphql",
            "operation": "query User($id: ID!) { user(id: $id) { id name } }",
            "variables": {"id": "user-debug"},
        },
        token=token,
    )
    grpc_result = client.json(
        "POST",
        "/grpc/execute",
        {
            "project_id": project_id,
            "descriptor_id": grpc_descriptor["id"],
            "endpoint": "grpc-target:50051",
            "service": "flowtest.user.v1.UserService",
            "method": "WatchUsers",
            "request": {"id": "user-debug"},
            "call_type": "server_streaming",
            "tls_mode": "plaintext",
        },
        token=token,
    )
    if graphql_result["output"]["body"]["data"]["user"]["id"] != "user-debug":
        raise RuntimeError("GraphQL Query debug did not return the bound variable")
    if grpc_result["output"]["message_count"] != 3:
        raise RuntimeError("gRPC Server Streaming debug did not return all messages")


def _create_echo_api(client: APIClient, token: str, project_id: str) -> dict[str, Any]:
    return client.json(
        "POST",
        f"/projects/{project_id}/apis",
        {
            "name": "绑定数据源",
            "description": "S23 REST source",
            "request": {
                "method": "POST",
                "path": "/echo",
                "query_parameters": [],
                "headers": {"Content-Type": "application/json"},
                "body_kind": "json",
                "body": {"id": "user-042"},
                "auth": {"kind": "none", "values": {}},
            },
        },
        token=token,
    )


def _workflow_definition(api_id: str, schema_id: str, descriptor_id: str) -> dict[str, Any]:
    return {
        "schema_version": "3.0",
        "nodes": [
            _legacy_node("start", "start", "开始", 0),
            {
                **_legacy_node("rest", "api", "REST 数据源", 220),
                "config": {"api_definition_id": api_id},
            },
            _graphql_node(schema_id),
            _grpc_node(descriptor_id),
            _legacy_node("end", "end", "结束", 700),
        ],
        "edges": [
            {"id": "start-rest", "source": "start", "target": "rest"},
            {"id": "rest-graphql", "source": "rest", "target": "graphql"},
            {"id": "rest-grpc", "source": "rest", "target": "grpc"},
            {"id": "graphql-end", "source": "graphql", "target": "end"},
            {"id": "grpc-end", "source": "grpc", "target": "end"},
        ],
        "settings": {"fail_fast": True, "concurrency": 20, "default_timeout_seconds": 30},
    }


def _graphql_node(schema_id: str) -> dict[str, Any]:
    return {
        **_legacy_node("graphql", "capability", "GraphQL 用户", 460, -80),
        "config": {},
        "capability_id": "graphql.request",
        "capability_version": "3.0.0",
        "configuration": {
            "schema_id": schema_id,
            "endpoint": "http://mock-target:8080/graphql",
            "operation": "query User($id: ID!) { user(id: $id) { id name } }",
            "variables": {"id": "placeholder"},
        },
        "bindings": [{"input": "variables.id", "expression": "node_outputs.rest.body.id"}],
    }


def _grpc_node(descriptor_id: str) -> dict[str, Any]:
    return {
        **_legacy_node("grpc", "capability", "gRPC 用户", 460, 80),
        "config": {},
        "capability_id": "grpc.call",
        "capability_version": "3.0.0",
        "configuration": {
            "descriptor_id": descriptor_id,
            "endpoint": "grpc-target:50051",
            "service": "flowtest.user.v1.UserService",
            "method": "GetUser",
            "request": {"id": "placeholder"},
            "call_type": "unary",
            "tls_mode": "plaintext",
        },
        "bindings": [{"input": "request.id", "expression": "node_outputs.rest.body.id"}],
    }


def _legacy_node(
    node_id: str,
    node_type: str,
    name: str,
    x: int,
    y: int = 0,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "name": name,
        "position": {"x": x, "y": y},
        "config": {},
    }


def _verify_workflow(
    detail: dict[str, Any],
    graphql: dict[str, Any],
    grpc_descriptor: dict[str, Any],
) -> None:
    if detail["execution"]["status"] != "passed":
        raise RuntimeError(f"S23 mixed protocol Workflow failed: {detail}")
    nodes = {item["node_id"]: item for item in detail["nodes"]}
    graphql_body = nodes["graphql"]["result"]["output"]["body"]
    grpc_messages = nodes["grpc"]["result"]["output"]["messages"]
    if graphql_body["data"]["user"]["id"] != "user-042" or grpc_messages[0]["id"] != "user-042":
        raise RuntimeError("REST response was not bound into both protocol requests")
    snapshot = detail["execution"]["snapshot"]["protocol_nodes"]
    if snapshot["graphql"]["schema_hash"] != graphql["content_sha256"]:
        raise RuntimeError("GraphQL Schema hash was not pinned")
    if snapshot["grpc"]["schema_hash"] != grpc_descriptor["content_sha256"]:
        raise RuntimeError("gRPC Descriptor hash was not pinned")


if __name__ == "__main__":
    main()
