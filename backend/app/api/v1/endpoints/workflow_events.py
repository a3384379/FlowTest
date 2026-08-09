from typing import cast
from uuid import UUID

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.errors import AppError
from app.core.security import token_service
from app.models.workflows import WorkflowExecution
from app.repositories.access import UserRepository
from app.repositories.workflows import WorkflowRepository
from app.services.execution_events import (
    ExecutionEventBus,
    ExecutionEventType,
)
from app.services.projects import ProjectService

router = APIRouter()
EVENTS_SUBPROTOCOL = "flowtest.events.v1"
TOKEN_SUBPROTOCOL_PREFIX = "flowtest.token."


@router.websocket("/executions/{execution_id}/events")
async def workflow_execution_events(websocket: WebSocket, execution_id: UUID) -> None:
    token = websocket_access_token(websocket.headers.get("sec-websocket-protocol"))
    execution = await _authorize(websocket, execution_id, token)
    if execution is None:
        return
    events = _event_bus(websocket)
    await websocket.accept(subprotocol=EVENTS_SUBPROTOCOL)
    try:
        async for event in events.subscribe(execution_id):
            await websocket.send_text(event.model_dump_json())
            if event.type is ExecutionEventType.EXECUTION_COMPLETED:
                await websocket.close(code=1000)
                return
    except WebSocketDisconnect:
        return


def websocket_access_token(protocols: str | None) -> str | None:
    if not protocols:
        return None
    for protocol in (item.strip() for item in protocols.split(",")):
        if protocol.startswith(TOKEN_SUBPROTOCOL_PREFIX):
            token = protocol.removeprefix(TOKEN_SUBPROTOCOL_PREFIX)
            return token or None
    return None


async def _authorize(
    websocket: WebSocket, execution_id: UUID, token: str | None
) -> WorkflowExecution | None:
    if token is None:
        await websocket.close(code=4401, reason="访问令牌缺失")
        return None
    try:
        claims = token_service.decode_access_token(token)
    except (jwt.InvalidTokenError, ValueError, KeyError):
        await websocket.close(code=4401, reason="访问令牌无效")
        return None
    session_maker = websocket.app.state.database_session_factory
    async with session_maker() as session:
        user = await UserRepository(session).get(claims.user_id)
        if user is None or not user.is_active or user.requires_password_change:
            await websocket.close(code=4401, reason="访问令牌无效")
            return None
        execution = await WorkflowRepository(session).get_execution(execution_id)
        if execution is None:
            await websocket.close(code=4404, reason="工作流执行不存在")
            return None
        try:
            await ProjectService(session).authorize(
                actor=user,
                project_id=execution.project_id,
                editing=False,
            )
        except AppError:
            await websocket.close(code=4403, reason="没有执行查看权限")
            return None
        return execution


def _event_bus(websocket: WebSocket) -> ExecutionEventBus:
    return cast(ExecutionEventBus, websocket.app.state.execution_event_bus)
