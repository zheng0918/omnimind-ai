"""问答会话编排（REQ-CHAT）。

建会话 / 历史分页为短事务；流式问答把检索-生成委托给 agents.rag_qa，
在事件流首尾负责落库（user 提问、assistant 回答 + 引用），并为 done 事件回填
messageId。落库与生成解耦，避免在 LLM 流式期间长占数据库连接。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from loguru import logger

from app.agents import rag_qa
from app.clients.registry import Clients
from app.core.config import Settings
from app.core.db import session_scope
from app.core.errors import CODE_RESOURCE_NOT_FOUND, CODE_UNKNOWN, BizError
from app.infra.sse import SSEEvent
from app.llm.base import ChatMessage
from app.prompts.v1 import PROMPT_VERSION
from app.repositories import chat_repo
from app.schemas.chat import ChatMessageOut, ChatMode, ChatSessionCreateIn, ChatSessionOut
from app.schemas.common import PageResult
from app.schemas.sse_events import (
    Citation,
    CitationEvent,
    DoneEvent,
    ErrorEvent,
    ProgressEvent,
    TokenEvent,
)


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
        logger.info(
            "chat session created session={} java_task_id={} kb={}",
            row.id,
            payload.java_task_id,
            payload.kb_id,
        )
        return ChatSessionOut(ai_session_id=row.id)


def _to_message_out(row: object) -> ChatMessageOut:
    raw = getattr(row, "citations_json", None) or []
    citations = [Citation.model_validate(item) for item in raw]
    return ChatMessageOut(
        message_id=row.id,  # type: ignore[attr-defined]
        session_id=row.session_id,  # type: ignore[attr-defined]
        role=row.role,  # type: ignore[attr-defined]
        content=row.content,  # type: ignore[attr-defined]
        citations=citations,
        feedback=row.feedback,  # type: ignore[attr-defined]
        created_at=row.created_at,  # type: ignore[attr-defined]
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


async def set_feedback(
    message_id: int, feedback: str | None, *, owner_id: int | None = None
) -> None:
    """更新消息点赞/点踩；消息不存在或非本人会话均抛资源不存在（契约 §1.4）。

    owner_id 来自 Java 透传的登录用户，用于校验消息归属，防越权（IDOR）。
    越权与不存在统一返回「不存在」，不泄露他人消息是否存在。
    """
    async with session_scope() as session:
        status = await chat_repo.set_feedback(
            session, message_id, feedback, owner_id=owner_id
        )
        if status != "ok":
            raise BizError(CODE_RESOURCE_NOT_FOUND, "消息不存在")
        logger.info("chat feedback set message={} feedback={}", message_id, feedback)


async def delete_session(session_id: int, *, owner_id: int | None = None) -> None:
    """删除会话及其消息（级联）。幂等：会话不存在/非本人静默返回。"""
    async with session_scope() as session:
        deleted = await chat_repo.delete_session(
            session, session_id, owner_id=owner_id
        )
        logger.info("chat session delete session={} deleted={}", session_id, deleted)


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
    """驱动一轮问答，产出 SSE 事件流并落库 user/assistant 消息。

    无论检索/生成/落库出现何种异常，都保证下发一个终态事件（done 或 error）；
    否则前端 SSE 收不到终态会一直停在「正在生成」（见 sse 客户端收尾逻辑）。
    """
    try:
        kb_ids, creative, history = await _load_context(
            session_id, query, settings.rag_history_rounds
        )
    except BizError as exc:
        yield ErrorEvent(code=exc.code, message=exc.message)
        return
    except Exception:
        logger.exception("chat stream load context failed session={}", session_id)
        yield ErrorEvent(code=CODE_UNKNOWN, message="会话加载失败，请稍后重试")
        return

    # 契约 §3.2：请求级 mode 覆盖会话默认；docRefs 限定文档范围
    if mode is not None:
        creative = mode == ChatMode.CREATIVE.value
    doc_ids = _parse_doc_refs(doc_refs)
    logger.info(
        "chat stream start session={} kb_ids={} creative={} doc_ids={} query_len={}",
        session_id,
        kb_ids,
        creative,
        doc_ids,
        len(query),
    )

    content_parts: list[str] = []
    citations: list[Citation] = []
    done: DoneEvent | None = None

    try:
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
            elif isinstance(event, ProgressEvent):
                # 进度事件仅作阶段反馈，必须透传后继续等待后续 token，
                # 切不可当终态——否则首个 retrieving 进度就会让流提前结束。
                yield event
            elif isinstance(event, DoneEvent):
                done = event
            elif isinstance(event, ErrorEvent):
                # rag 已自带终态，透传收尾，不落库 assistant
                yield event
                return
            else:
                # 未知事件类型：透传但不终止，避免未来新增事件再次误判为终态。
                yield event
    except Exception:
        logger.exception("chat stream answer failed session={}", session_id)
        yield ErrorEvent(code=CODE_UNKNOWN, message="AI 服务异常，请稍后重试")
        return

    # 落库失败不应让前端卡在「正在生成」：答案已流式送达，仅记日志并照常收尾。
    message_id: int | None = None
    try:
        message_id = await _save_answer(
            session_id, "".join(content_parts), citations, settings.deepseek_model
        )
        logger.info(
            "chat stream done session={} message={} citations={}",
            session_id,
            message_id,
            len(citations),
        )
    except Exception:
        logger.exception("save assistant message failed session={}", session_id)

    # 始终下发 done 终态：有原始 done 则回填 messageId，否则兜底合成一个。
    if done is not None:
        yield done.model_copy(update={"message_id": message_id})
    else:
        yield DoneEvent(message_id=message_id, filtered_count=len(citations))
