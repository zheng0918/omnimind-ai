"""chat_sessions / chat_messages 数据访问（REQ-CHAT）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession


async def create_session(
    session: AsyncSession,
    *,
    java_task_id: int,
    kb_id: list[int],
    owner_id: int,
    tenant_id: int,
    mode: str,
) -> ChatSession:
    """新建问答会话并 flush 取得 id。"""
    row = ChatSession(
        java_task_id=java_task_id,
        kb_id=kb_id,
        owner_id=owner_id,
        tenant_id=tenant_id,
        mode=mode,
    )
    session.add(row)
    await session.flush()
    return row


async def get_session_row(session: AsyncSession, session_id: int) -> ChatSession | None:
    """按 id 取会话。"""
    return await session.get(ChatSession, session_id)


async def add_message(
    session: AsyncSession,
    *,
    session_id: int,
    role: str,
    content: str,
    citations_json: list[Any] | None = None,
    ai_model: str | None = None,
    prompt_ver: str | None = None,
) -> ChatMessage:
    """追加一条消息并 flush 取得 id。"""
    row = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        citations_json=citations_json,
        ai_model=ai_model,
        prompt_ver=prompt_ver,
    )
    session.add(row)
    await session.flush()
    return row


async def recent_messages(
    session: AsyncSession, session_id: int, limit: int
) -> list[ChatMessage]:
    """取最近 limit 条消息，按时间正序返回（供历史轮次装配）。"""
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    rows.reverse()
    return rows


async def list_messages(
    session: AsyncSession, session_id: int, *, page: int, page_size: int
) -> tuple[list[ChatMessage], int]:
    """分页取历史消息（正序），返回（当页, 总数）。"""
    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ChatMessage)
                .where(ChatMessage.session_id == session_id)
            )
        ).scalar_one()
    )
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return rows, total
