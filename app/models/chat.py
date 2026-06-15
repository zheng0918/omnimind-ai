"""问答会话与消息表（REQ-CHAT）。"""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class ChatSession(Base, IdMixin, TimestampMixin):
    """问答会话。kb_id 为知识库 id 列表（多库检索），以 JSONB 数组存储。"""

    __tablename__ = "chat_sessions"

    java_task_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kb_id: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'precise'")
    )


class ChatMessage(Base, IdMixin, TimestampMixin):
    """单条消息。role=user/assistant；assistant 消息带引用、模型、prompt 版本。"""

    __tablename__ = "chat_messages"

    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachments: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_ver: Mapped[str | None] = mapped_column(String(32), nullable=True)
    feedback: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (Index("ix_chat_messages_session_id", "session_id"),)
