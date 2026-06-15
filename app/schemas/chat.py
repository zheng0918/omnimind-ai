"""AI 问答相关 schema（REQ-CHAT）。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from app.schemas.common import CamelModel
from app.schemas.sse_events import Citation


class ChatMode(StrEnum):
    """问答模式：精准 / 创意（影响生成温度与发散度）。"""

    PRECISE = "precise"
    CREATIVE = "creative"


class ChatSessionCreateIn(CamelModel):
    """POST /ai/v1/chat/sessions 入参。"""

    java_task_id: int
    kb_id: list[int]
    owner_id: int
    tenant_id: int = 0
    mode: ChatMode = ChatMode.PRECISE


class ChatSessionOut(CamelModel):
    """建会话响应。"""

    ai_session_id: int


class ChatMessageOut(CamelModel):
    """历史消息出参。"""

    id: int
    session_id: int
    role: str
    content: str
    citations: list[Citation] = Field(default_factory=list)
    ai_model: str | None = None
    prompt_ver: str | None = None
