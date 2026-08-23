import asyncio
import json
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import (
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field

app = FastAPI(title="FlowTest Mock Target", version="1.0.0")


class LoginRequest(BaseModel):
    username: str
    password: str


class OrderRequest(BaseModel):
    product: str
    amount: int = Field(gt=0)


class S471OrderRequest(BaseModel):
    quantity: int
    type: str
    remark: str | None = None
    profile: dict[str, str]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/login")
async def login(payload: LoginRequest) -> dict[str, object]:
    if payload.username != "tester" or payload.password != "flowtest":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    return {"code": 0, "data": {"token": "mock-token", "user_id": "user-001"}}


@app.get("/users/me")
async def current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    if authorization != "Bearer mock-token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token"
        )
    return {"code": 0, "data": {"id": "user-001", "name": "测试用户"}}


@app.post("/orders")
async def create_order(
    payload: OrderRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    if authorization != "Bearer mock-token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token"
        )
    return {"code": 0, "data": {"id": str(uuid4()), **payload.model_dump()}}


@app.post("/tenants/{tenant_id}/orders")
async def create_s471_order(
    tenant_id: str,
    payload: S471OrderRequest,
    dry_run: Annotated[str | None, Query(alias="dryRun")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    app.state.last_s471_request = {
        "tenant_id": tenant_id,
        "dry_run": dry_run,
        "tenant_header_present": x_tenant_id is not None,
        "authorization_present": authorization is not None,
        "body": payload.model_dump(),
    }
    try:
        UUID(tenant_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid tenant id") from error
    if authorization != "Bearer mock-token":
        raise HTTPException(status_code=401, detail="Missing token")
    if x_tenant_id is None:
        raise HTTPException(status_code=400, detail="Missing tenant header")
    if dry_run not in {None, "true", "false"}:
        raise HTTPException(status_code=400, detail="Invalid dryRun")
    if not 1 <= payload.quantity <= 999:
        raise HTTPException(status_code=400, detail="Invalid quantity")
    if payload.type not in {"NORMAL", "PRIORITY"}:
        raise HTTPException(status_code=400, detail="Invalid order type")
    if payload.remark is not None and len(payload.remark) > 20:
        raise HTTPException(status_code=400, detail="Invalid remark")
    if not payload.profile.get("display_name"):
        raise HTTPException(status_code=400, detail="Invalid profile")
    return {"id": str(uuid4()), "accepted": True}


@app.get("/s47-1/requests/last")
async def last_s471_request() -> dict[str, object]:
    request = getattr(app.state, "last_s471_request", None)
    if not isinstance(request, dict):
        raise HTTPException(status_code=404, detail="No S47.1 request")
    return request


@app.post("/upload")
async def upload(file: Annotated[UploadFile, File()]) -> dict[str, object]:
    content = await file.read()
    return {
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(content),
    }


@app.get("/download")
async def download() -> Response:
    return Response(
        b"flowtest-download",
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="flowtest.bin"'},
    )


@app.get("/slow")
async def slow(seconds: float = 1.0) -> dict[str, float]:
    await asyncio.sleep(min(max(seconds, 0), 10))
    return {"slept": seconds}


@app.get("/failure")
async def failure() -> None:
    raise HTTPException(status_code=500, detail="Expected failure")


@app.post("/echo")
async def echo(payload: dict[str, object]) -> dict[str, object]:
    return payload


@app.websocket("/ws/echo")
async def websocket_echo(websocket: WebSocket) -> None:
    requested_protocols = websocket.headers.get("sec-websocket-protocol", "")
    selected_protocol = next(
        (item.strip() for item in requested_protocols.split(",") if item.strip()),
        None,
    )
    await websocket.accept(subprotocol=selected_protocol)
    try:
        while True:
            message = await websocket.receive()
            if text_payload := message.get("text"):
                await websocket.send_text(text_payload)
            elif binary_payload := message.get("bytes"):
                await websocket.send_bytes(binary_payload)
    except WebSocketDisconnect:
        return


@app.post("/graphql")
async def graphql(request: Request) -> dict[str, object]:
    payload = await request.json()
    query = payload.get("query")
    variables = payload.get("variables", {})
    if not isinstance(query, str) or not isinstance(variables, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Bad GraphQL request",
        )
    if "renameUser" in query:
        return {
            "data": {
                "renameUser": {
                    "id": str(variables.get("id", "user-001")),
                    "name": str(variables.get("name", "测试用户")),
                }
            }
        }
    return {
        "data": {
            "user": {
                "id": str(variables.get("id", "user-001")),
                "name": "测试用户",
            }
        }
    }


@app.post("/notifications/flowtest", status_code=status.HTTP_204_NO_CONTENT)
async def receive_flowtest_notification(request: Request) -> Response:
    app.state.last_notification = {
        "event": request.headers.get("X-FlowTest-Event"),
        "timestamp": request.headers.get("X-FlowTest-Timestamp"),
        "signature": request.headers.get("X-FlowTest-Signature"),
        "body": await request.json(),
    }
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/notifications/last")
async def last_flowtest_notification() -> dict[str, object]:
    notification = getattr(app.state, "last_notification", None)
    if not isinstance(notification, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No notification"
        )
    return notification


@app.post("/v1/chat/completions")
async def openai_compatible_completion(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    if authorization != "Bearer flowtest-mock-ai-key":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid AI key"
        )
    payload = await request.json()
    messages = payload.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="No prompt"
        )
    user_message = messages[-1]
    if not isinstance(user_message, dict) or not isinstance(
        user_message.get("content"), str
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Bad prompt"
        )
    prompt = json.loads(user_message["content"])
    encoded_prompt = json.dumps(prompt, ensure_ascii=False)
    if "must-not-reach-ai" in encoded_prompt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="FlowTest sent an unredacted value",
        )
    job_type = prompt.get("job_type")
    if job_type not in {"workflow_draft", "change_set"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unsupported smoke job",
        )
    suggestions = _ai_suggestions(str(job_type))
    return {
        "choices": [
            {"message": {"content": json.dumps(suggestions, ensure_ascii=False)}}
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }


def _ai_suggestions(job_type: str) -> dict[str, object]:
    content: dict[str, object] = {
        "name": "S21 AI 人工审核工作流",
        "description": "仅在人工接受后创建",
        "definition": {
            "schema_version": "1.0",
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "name": "开始",
                    "position": {"x": 0, "y": 0},
                    "config": {},
                },
                {
                    "id": "end",
                    "type": "end",
                    "name": "结束",
                    "position": {"x": 240, "y": 0},
                    "config": {},
                },
            ],
            "edges": [{"id": "start-end", "source": "start", "target": "end"}],
        },
    }
    if job_type == "change_set":
        content["action"] = "create"
        content["name"] = "S30 AI 变更集草稿工作流"
        content["description"] = "逐项人工审核后只生成草稿"
        content["definition"] = _change_set_workflow_definition()
    return {
        "suggestions": [
            {
                "type": "workflow",
                "title": (
                    "S30 AI 变更集草稿工作流"
                    if job_type == "change_set"
                    else "S21 AI 人工审核工作流"
                ),
                "content": content,
            }
        ]
    }


def _change_set_workflow_definition() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "variables": [],
        "nodes": [
            _change_set_workflow_node("start", "start", "开始", x=0),
            _change_set_workflow_node("end", "end", "结束", x=240),
        ],
        "edges": [
            {
                "id": "start-end",
                "source": "start",
                "target": "end",
                "condition": None,
                "mappings": [],
            }
        ],
        "settings": {
            "fail_fast": True,
            "concurrency": 20,
            "default_timeout_seconds": 30,
        },
    }


def _change_set_workflow_node(
    node_id: str,
    node_type: str,
    name: str,
    *,
    x: int,
) -> dict[str, object]:
    return {
        "id": node_id,
        "type": node_type,
        "name": name,
        "position": {"x": x, "y": 0},
        "config_json": "{}",
        "capability_id": None,
        "capability_version": None,
        "configuration_json": None,
        "bindings": None,
    }
