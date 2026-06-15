"""AI 问答路由（REQ-CHAT）。

建会话与历史为普通 JSON 接口；问答为 SSE 流（token/citation/done/error），
由 Java 原样透传前端。错误在流内以 error 事件下发，不抛 HTTPException。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.api.deps import ClientsDep, ok
from app.core.config import get_settings
from app.infra.sse import SSE_MEDIA_TYPE, stream_events
from app.schemas.chat import ChatSessionCreateIn
from app.services import chat_service

router = APIRouter(prefix="/ai/v1/chat", tags=["chat"])


@router.post("/sessions")
async def create_session(payload: ChatSessionCreateIn) -> dict[str, Any]:
    """建立问答会话，返回 aiSessionId。"""
    result = await chat_service.create_session(payload)
    return ok(result)


@router.get("/stream")
async def stream_chat(
    clients: ClientsDep,
    session_id: Annotated[int, Query(alias="sessionId")],
    query: Annotated[str, Query(min_length=1)],
) -> StreamingResponse:
    """SSE 流式问答。"""
    events = chat_service.stream_chat(
        clients, get_settings(), session_id=session_id, query=query
    )
    return StreamingResponse(
        stream_events(events),
        media_type=SSE_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: int,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> dict[str, Any]:
    """分页查询历史消息。"""
    result = await chat_service.list_messages(session_id, page=page, page_size=page_size)
    return ok(result)
