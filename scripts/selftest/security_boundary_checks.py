"""Probe actual denied trust paths and independently read only synthetic export sentinels."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4

import httpx
import jwt
from scripts.selftest.io import HarnessError, JsonObject, object_value, objects_value, text_value
from scripts.selftest.security_boundary_contracts import BoundaryObservation, DenialObservation
from scripts.selftest.security_boundary_http import BoundaryAPI
from scripts.selftest.security_boundary_setup import SecurityActors, actor_permissions

PRIVATE_SENTINEL = "flowtest-owned-secret-sentinel-never-exported-v1"
PUBLIC_SENTINEL = "Bearer flowtest-public-off-policy-synthetic-v1"
SECRET_REFERENCE = "{{secret.SELFTEST_SENTINEL}}"  # noqa: S105 -- reference, never a value


def denial(operation: str, response: httpx.Response) -> DenialObservation:
    payload = object_value(response.json())
    error = object_value(payload.get("error", {}))
    code, trace = error.get("code"), error.get("trace_id")
    return DenialObservation(
        operation=operation,
        status=response.status_code,
        code=code if isinstance(code, str) else None,
        trace_id=trace if isinstance(trace, str) else None,
        response_digest=hashlib.sha256(response.content).hexdigest(),
    )


async def _empty_runs(
    api: BoundaryAPI, project: UUID
) -> tuple[tuple[UUID, ...], tuple[UUID, ...], bool]:
    result = []
    complete = True
    for path in ("test-plan-runs", "workflow-executions"):
        page = await api.object("GET", f"/projects/{project}/{path}?page=1&page_size=100")
        items = objects_value(page["items"])
        complete = complete and page["total"] == len(items) and len(items) < 100
        result.append(tuple(UUID(text_value(item["id"])) for item in items))
    return result[0], result[1], complete


async def trust_denials(
    actors: SecurityActors, *, editor: bool, deadline: datetime
) -> BoundaryObservation:
    project = actors.identity.project_ids[0]
    api = actors.editor if editor else actors.owner
    actor_id, admin, permission = await actor_permissions(
        api, project, "editor" if editor else "owner"
    )
    root = f"/agent/projects/{project}/self-tests"
    forged = jwt.encode(
        {
            "sub": str(actor_id),
            "iss": "owner-self-signed",
            "aud": "flowtest-selftest",
            "exp": deadline.timestamp(),
        },
        "synthetic-owner-controlled-key-not-deployment-trust",
        algorithm="HS256",
    )
    denied = [
        denial("ordinary_tasks", await api.probe("GET", root + "/tasks")),
        denial("self_signed_tasks", await api.probe("GET", root + "/tasks", access_token=forged)),
        denial(
            "self_report_verification",
            await api.probe(
                "POST",
                f"/ci/projects/{project}/self-test-runs/{uuid4()}/verification",
                {
                    "verdict": "passed",
                    "provenance": "trusted_ci",
                    "verified_pass": True,
                },
            ),
        ),
        denial(
            "invented_trusted_scope",
            await api.probe(
                "POST",
                f"/projects/{project}/service-tokens",
                {
                    "name": "不能自授权可信身份",
                    "scopes": ["write:trusted-verification"],
                },
            ),
        ),
    ]
    if not editor:
        token = await api.object(
            "POST",
            f"/projects/{project}/service-tokens",
            {
                "name": "普通项目读取身份",
                "scopes": ["read:execution"],
            },
        )
        value = text_value(token["token"])
        denied.append(
            denial(
                "valid_project_token_tasks",
                await api.probe("GET", root + "/tasks", access_token=value),
            )
        )
        await api.request("DELETE", f"/projects/{project}/service-tokens/{text_value(token['id'])}")
    runs, executions, complete = await _empty_runs(actors.observer, project)
    return BoundaryObservation(
        scenario_id="ST-SECURITY-editor-self-sign" if editor else "ST-SECURITY-owner-self-sign",
        role="editor" if editor else "owner",
        actor_id=actor_id,
        is_system_admin=admin,
        permission_role=permission,
        denials=tuple(denied),
        native_run_ids=runs,
        native_executions=executions,
        complete=complete,
    )


async def manual_report(actors: SecurityActors) -> BoundaryObservation:
    project = actors.identity.project_ids[0]
    body = json.dumps(
        {"verdict": "passed", "provenance": "trusted_ci", "verified_pass": True}
    ).encode()
    uploaded = await actors.editor.upload_synthetic(
        f"/projects/{project}/files", "synthetic-report.json", body
    )
    page = await actors.observer.object("GET", f"/projects/{project}/files?page=1&page_size=100")
    listed = [item for item in objects_value(page["items"]) if item["id"] == uploaded["id"]]
    if len(listed) != 1:
        raise HarnessError("SELFTEST_SECURITY_MANUAL_REPORT_NOT_READABLE")
    runs, executions, complete = await _empty_runs(actors.observer, project)
    actor_id, admin, role = await actor_permissions(actors.observer, project, "viewer")
    return BoundaryObservation(
        scenario_id="ST-SECURITY-manual-report",
        role="observer",
        actor_id=actor_id,
        is_system_admin=admin,
        permission_role=role,
        artifact_id=UUID(text_value(uploaded["id"])),
        artifact_purpose=text_value(listed[0]["purpose"]),
        native_run_ids=runs,
        native_executions=executions,
        complete=complete and "provenance" not in listed[0] and "verified_pass" not in listed[0],
    )


async def _export_api(owner: BoundaryAPI, project: UUID, batch: str) -> UUID:
    metadata = await owner.object(
        "PUT",
        f"/projects/{project}/secrets",
        {
            "name": "SELFTEST_SENTINEL",
            "value": PRIVATE_SENTINEL,
        },
    )
    if PRIVATE_SENTINEL in json.dumps(metadata) or {"value", "ciphertext"} & metadata.keys():
        raise HarnessError("SELFTEST_SECURITY_SECRET_WRITE_RESPONSE_LEAK")
    created = await owner.object(
        "POST",
        f"/projects/{project}/apis",
        {
            "name": batch + "-合成导出",
            "request": {
                "method": "GET",
                "path": "/synthetic-only",
                "headers": {"Authorization": PUBLIC_SENTINEL, "X-Secret-Ref": SECRET_REFERENCE},
            },
        },
    )

    api_id = text_value(object_value(created["definition"])["id"])
    definition: JsonObject = {
        "variables": {"synthetic_reference": SECRET_REFERENCE},
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {
                "id": "request",
                "type": "api",
                "name": "未执行的合成引用",
                "position": {"x": 100, "y": 0},
                "config": {"api_definition_id": api_id, "api_version": 1},
            },
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 200, "y": 0}},
        ],
        "edges": [
            {"id": "first", "source": "start", "target": "request"},
            {"id": "last", "source": "request", "target": "end"},
        ],
    }
    workflow = await owner.object(
        "POST",
        f"/projects/{project}/workflows",
        {
            "name": batch + "-合成引用导出",
            "definition": definition,
        },
    )
    identity = text_value(workflow["id"])
    await owner.object("POST", f"/projects/{project}/workflows/{identity}/versions", {})
    return UUID(identity)


async def sentinel_exports(
    actors: SecurityActors, batch: str
) -> tuple[BoundaryObservation, BoundaryObservation]:
    first, second = actors.identity.project_ids
    default = await actors.owner.object("GET", f"/projects/{first}/redaction-policy")
    if default["mode"] != "off" or default["source"] != "installation":
        raise HarnessError("SELFTEST_SECURITY_DEFAULT_REDACTION_NOT_OFF")
    first_workflow = await _export_api(actors.owner, first, batch)
    await actors.owner.object("PUT", f"/projects/{second}/redaction-policy", {"mode": "on"})
    second_workflow = await _export_api(actors.owner, second, batch)
    presence, digests = [], []
    secret_presence: list[bool] = []
    forbidden: list[str] = []
    workflows = {first: first_workflow, second: second_workflow}
    all_digests: list[str] = []
    for project in (first, second, first):
        exported = await actors.observer.probe(
            "GET", f"/projects/{project}/exports/apis?format=har"
        )
        if exported.status_code != 200:
            raise HarnessError("SELFTEST_SECURITY_EXPORT_FAILED")
        presence.append(PUBLIC_SENTINEL.encode() in exported.content)
        secret_presence.append(PRIVATE_SENTINEL.encode() in exported.content)
        digests.append(hashlib.sha256(exported.content).hexdigest())
        all_digests.append(digests[-1])
        native = await actors.observer.probe(
            "GET", f"/projects/{project}/workflows/{workflows[project]}/native-export"
        )
        if native.status_code != 200:
            raise HarnessError("SELFTEST_SECURITY_NATIVE_EXPORT_FAILED")
        secret_presence.append(PRIVATE_SENTINEL.encode() in native.content)
        all_digests.append(hashlib.sha256(native.content).hexdigest())
        listed = objects_value(await actors.observer.request("GET", f"/projects/{project}/secrets"))
        secret_presence.append(PRIVATE_SENTINEL in json.dumps(listed))
        forbidden.extend(key for item in listed for key in ("value", "ciphertext") if key in item)
    actor_id, admin, role = await actor_permissions(actors.observer, first, "viewer")
    return (
        BoundaryObservation(
            scenario_id="ST-SECURITY-write-only-export",
            role="observer",
            actor_id=actor_id,
            is_system_admin=admin,
            permission_role=role,
            complete=True,
            sentinel_present=tuple(secret_presence),
            forbidden_secret_keys=tuple(forbidden),
            observation_digests=tuple(all_digests),
        ),
        BoundaryObservation(
            scenario_id="ST-SECURITY-project-redaction",
            role="observer",
            actor_id=actor_id,
            is_system_admin=admin,
            permission_role=role,
            complete=True,
            sentinel_present=tuple(presence),
            observation_digests=tuple(digests),
        ),
    )
