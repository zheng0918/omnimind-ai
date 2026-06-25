"""AI 问答相关 schema（REQ-CHAT）。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

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
    """历史消息出参。

    字段名对齐契约 §1.4（messageId / feedback / createdAt），Java 透传不重命名，
    前端据此渲染历史气泡与反馈态。citations 已为 camelCase 结构。
    """

    message_id: int
    session_id: int
    role: str
    content: str
    citations: list[Citation] = Field(default_factory=list)
    feedback: str | None = None
    created_at: datetime | None = None
    ai_model: str | None = None
    prompt_ver: str | None = None


class FeedbackIn(CamelModel):
    """POST /ai/v1/chat/messages/{id}/feedback 入参。

    feedback：up 点赞 / down 点踩 / null 取消（契约 §1.4）。
    userId：Java 透传的登录用户，用于校验消息归属、防越权点赞他人消息（IDOR）。
    """

    feedback: Literal["up", "down"] | None = None
    user_id: int | None = None
