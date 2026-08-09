import asyncio
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

app = FastAPI(title="FlowTest Mock Target", version="1.0.0")


class LoginRequest(BaseModel):
    username: str
    password: str


class OrderRequest(BaseModel):
    product: str
    amount: int = Field(gt=0)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/login")
async def login(payload: LoginRequest) -> dict[str, object]:
    if payload.username != "tester" or payload.password != "flowtest":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return {"code": 0, "data": {"token": "mock-token", "user_id": "user-001"}}


@app.get("/users/me")
async def current_user(authorization: Annotated[str | None, Header()] = None) -> dict[str, object]:
    if authorization != "Bearer mock-token":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    return {"code": 0, "data": {"id": "user-001", "name": "测试用户"}}


@app.post("/orders")
async def create_order(
    payload: OrderRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    if authorization != "Bearer mock-token":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    return {"code": 0, "data": {"id": str(uuid4()), **payload.model_dump()}}


@app.post("/upload")
async def upload(file: Annotated[UploadFile, File()]) -> dict[str, object]:
    content = await file.read()
    return {"filename": file.filename, "content_type": file.content_type, "size": len(content)}


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No notification")
    return notification
