"""问答会话编排（REQ-CHAT）。

建会话 / 历史分页为短事务；流式问答把检索-生成委托给 agents.rag_qa，
在事件流首尾负责落库（user 提问、assistant 回答 + 引用），并为 done 事件回填
messageId。落库与生成解耦，避免在 LLM 流式期间长占数据库连接。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.agents import rag_qa
from app.clients.registry import Clients
from app.core.config import Settings
from app.core.db import session_scope
from app.core.errors import CODE_RESOURCE_NOT_FOUND, BizError
from app.infra.sse import SSEEvent
from app.llm.base import ChatMessage
from app.prompts.v1 import PROMPT_VERSION
from app.repositories import chat_repo
from app.schemas.chat import ChatMessageOut, ChatMode, ChatSessionCreateIn, ChatSessionOut
from app.schemas.common import PageResult
from app.schemas.sse_events import Citation, CitationEvent, DoneEvent, TokenEvent


async def create_session(payload: ChatSessionCreateIn) -> ChatSessionOut:
    """建立问答会话。"""
    async with session_scope() as session:
        row = await chat_repo.create_session(
            session,
            java_task_id=payload.java_task_id,
            kb_id=payload.kb_id,
            owner_id=payload.owner_id,
            tenant_id=payload.tenant_id,
            mode=payload.mode.value,
        )
        return ChatSessionOut(ai_session_id=row.id)


def _to_message_out(row: object) -> ChatMessageOut:
    raw = getattr(row, "citations_json", None) or []
    citations = [Citation.model_validate(item) for item in raw]
    return ChatMessageOut(
        id=row.id,  # type: ignore[attr-defined]
        session_id=row.session_id,  # type: ignore[attr-defined]
        role=row.role,  # type: ignore[attr-defined]
        content=row.content,  # type: ignore[attr-defined]
        citations=citations,
        ai_model=row.ai_model,  # type: ignore[attr-defined]
        prompt_ver=row.prompt_ver,  # type: ignore[attr-defined]
    )


async def list_messages(
    session_id: int, *, page: int, page_size: int
) -> PageResult[ChatMessageOut]:
    """分页查询历史消息。"""
    async with session_scope() as session:
        rows, total = await chat_repo.list_messages(
            session, session_id, page=page, page_size=page_size
        )
        return PageResult(
            items=[_to_message_out(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
        )


async def _load_context(
    session_id: int, query: str, history_rounds: int
) -> tuple[list[int], bool, list[ChatMessage]]:
    """读取会话范围与历史，并落库本轮 user 提问。返回（kbIds, 是否创意模式, 历史）。"""
    async with session_scope() as session:
        row = await chat_repo.get_session_row(session, session_id)
        if row is None:
            raise BizError(CODE_RESOURCE_NOT_FOUND, "会话不存在")
        kb_ids = list(row.kb_id or [])
        creative = row.mode == ChatMode.CREATIVE.value
        prior = await chat_repo.recent_messages(session, session_id, history_rounds * 2)
        history = [ChatMessage(role=m.role, content=m.content) for m in prior]
        await chat_repo.add_message(session, session_id=session_id, role="user", content=query)
    return kb_ids, creative, history


async def _save_answer(
    session_id: int, content: str, citations: list[Citation], model: str
) -> int:
    async with session_scope() as session:
        row = await chat_repo.add_message(
            session,
            session_id=session_id,
            role="assistant",
            content=content,
            citations_json=[c.model_dump(by_alias=True) for c in citations],
            ai_model=model,
            prompt_ver=PROMPT_VERSION,
        )
        return row.id


def _parse_doc_refs(doc_refs: str | None) -> list[int]:
    """解析逗号分隔的 docId 字符串为 int 列表，忽略非法/空项。"""
    if not doc_refs:
        return []
    ids: list[int] = []
    for part in doc_refs.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


async def stream_chat(
    clients: Clients,
    settings: Settings,
    *,
    session_id: int,
    query: str,
    mode: str | None = None,
    doc_refs: str | None = None,
) -> AsyncIterator[SSEEvent]:
    """驱动一轮问答，产出 SSE 事件流并落库 user/assistant 消息。"""
    kb_ids, creative, history = await _load_context(
        session_id, query, settings.rag_history_rounds
    )
    # 契约 §3.2：请求级 mode 覆盖会话默认；docRefs 限定文档范围
    if mode is not None:
        creative = mode == ChatMode.CREATIVE.value
    doc_ids = _parse_doc_refs(doc_refs)

    content_parts: list[str] = []
    citations: list[Citation] = []
    done: DoneEvent | None = None

    async for event in rag_qa.stream_answer(
        clients,
        settings,
        query=query,
        kb_ids=kb_ids,
        history=history,
        creative=creative,
        doc_ids=doc_ids,
    ):
        if isinstance(event, TokenEvent):
            content_parts.append(event.text)
            yield event
        elif isinstance(event, CitationEvent):
            citations = event.citations
            yield event
        elif isinstance(event, DoneEvent):
            done = event
        else:  # ErrorEvent：不落库 assistant，直接收尾
            yield event
            return

    message_id = await _save_answer(
        session_id, "".join(content_parts), citations, settings.deepseek_model
    )
    if done is not None:
        yield done.model_copy(update={"message_id": message_id})
