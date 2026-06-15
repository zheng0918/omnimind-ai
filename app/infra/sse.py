"""SSE 序列化辅助（interfaceContract §0.8）。

事件经 Java 原样透传给前端：`event: <name>\\ndata: <json>\\n\\n`，
字段 camelCase，事件名取自模型的 `type` 字段，data 中不含 `type`。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.schemas.sse_events import (
    CitationEvent,
    DoneEvent,
    ErrorEvent,
    ProgressEvent,
    TokenEvent,
)

SSEEvent = TokenEvent | CitationEvent | ProgressEvent | DoneEvent | ErrorEvent

KEEP_ALIVE = ": keep-alive\n\n"
SSE_MEDIA_TYPE = "text/event-stream"


def format_sse(event: str, data: str) -> str:
    """拼装单条 SSE 帧。"""
    return f"event: {event}\ndata: {data}\n\n"


def serialize_event(event: SSEEvent) -> str:
    """把事件模型序列化为 SSE 帧（data 为 camelCase JSON，不含 type）。"""
    payload = event.model_dump_json(by_alias=True, exclude={"type"})
    return format_sse(event.type, payload)


async def stream_events(events: AsyncIterator[SSEEvent]) -> AsyncIterator[str]:
    """把事件模型异步流转换为 SSE 文本帧流，供 StreamingResponse 使用。"""
    async for event in events:
        yield serialize_event(event)
