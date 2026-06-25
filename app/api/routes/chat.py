"""AI 问答路由（REQ-CHAT）。

建会话与历史为普通 JSON 接口；问答为 SSE 流（token/citation/done/error），
由 Java 原样透传前端。错误在流内以 error 事件下发，不抛 HTTPException。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from loguru import logger

from app.api.deps import ClientsDep, ok
from app.core.config import get_settings
from app.infra.sse import SSE_MEDIA_TYPE, stream_events
from app.schemas.chat import ChatSessionCreateIn, FeedbackIn
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
    mode: Annotated[str | None, Query()] = None,
    doc_refs: Annotated[str | None, Query(alias="docRefs")] = None,
) -> StreamingResponse:
    """SSE 流式问答。

    契约 §3.2：mode 可覆盖会话默认模式；docRefs 为逗号分隔 docId，限定检索范围。
    """
    logger.info(
        "chat stream request session={} mode={} doc_refs={}", session_id, mode, doc_refs
    )
    events = chat_service.stream_chat(
        clients,
        get_settings(),
        session_id=session_id,
        query=query,
        mode=mode,
        doc_refs=doc_refs,
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


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: int,
    owner_id: Annotated[int | None, Query(alias="ownerId")] = None,
) -> dict[str, Any]:
    """删除会话及其历史消息（级联）。Java 删除本地元数据后调用，避免 Python 侧孤儿数据。"""
    await chat_service.delete_session(session_id, owner_id=owner_id)
    return ok()


@router.post("/messages/{message_id}/feedback")
async def submit_feedback(message_id: int, payload: FeedbackIn) -> dict[str, Any]:
    """消息点赞/点踩/取消（契约 §1.4）。"""
    await chat_service.set_feedback(
        message_id, payload.feedback, owner_id=payload.user_id
    )
    return ok()
