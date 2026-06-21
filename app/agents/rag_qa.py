"""RAG 问答编排（spec §10.1）。

query 改写 → 混合检索 → 父块上下文装配 → DeepSeek 流式生成 → 引用抽取。
以异步生成器产出 SSE 事件（token / citation / done / error）；DB 落库由 service 负责。
检索阶段单独开短事务并尽快释放，避免在 LLM 流式生成期间长占数据库连接。
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator

from loguru import logger
from openai import APITimeoutError

from app.clients.registry import Clients
from app.core.config import Settings
from app.core.db import session_scope
from app.core.errors import (
    CODE_LLM_TIMEOUT,
    CODE_RAG_RETRIEVE_FAILED,
    CODE_RAG_SCOPE_EMPTY,
    BizError,
)
from app.infra.sse import SSEEvent
from app.llm.base import ChatMessage
from app.prompts import v1
from app.rag.retriever import RetrievedBlock, hybrid_retrieve
from app.schemas.sse_events import (
    Citation,
    CitationEvent,
    DoneEvent,
    ErrorEvent,
    TokenEvent,
)
from app.utils.text import StreamingDesensitizer

_CITATION_PATTERN = re.compile(r"\[(\d{1,2})\]")
_SNIPPET_CHARS = 120
_CREATIVE_TEMPERATURE = 0.7


def _cited_indices(text: str) -> list[int]:
    """按出现顺序抽取答案中的 [n] 引用编号（去重，1 起）。"""
    seen: set[int] = set()
    ordered: list[int] = []
    for match in _CITATION_PATTERN.finditer(text):
        idx = int(match.group(1))
        if idx not in seen:
            seen.add(idx)
            ordered.append(idx)
    return ordered


def _build_citations(answer: str, blocks: list[RetrievedBlock]) -> list[Citation]:
    """根据答案中的 [n] 标注，映射回父块生成引用列表。"""
    citations: list[Citation] = []
    for idx in _cited_indices(answer):
        if 1 <= idx <= len(blocks):
            block = blocks[idx - 1]
            citations.append(
                Citation(
                    doc_id=block.document_id,
                    chunk_id=block.parent_id,
                    page=block.page,
                    paragraph_id=block.paragraph_id,
                    snippet=block.text[:_SNIPPET_CHARS],
                    confidence=round(block.score, 4),
                )
            )
    return citations


async def _rewrite_query(
    clients: Clients, history: list[ChatMessage], query: str
) -> str:
    """基于历史改写检索 query；失败或为空时回退原始 query。"""
    if not history:
        return query
    try:
        messages = v1.build_query_rewrite_messages(history, query)
        rewritten = (await clients.llm.chat(messages, temperature=0.0)).strip()
        return rewritten or query
    except Exception:
        logger.warning("query rewrite failed, fallback to original")
        return query


async def _retrieve(
    clients: Clients,
    settings: Settings,
    query: str,
    kb_ids: list[int],
    doc_ids: list[int] | None = None,
) -> list[RetrievedBlock]:
    """短事务内完成混合检索，随后立即释放连接。"""
    async with session_scope() as session:
        return await hybrid_retrieve(
            session, clients, settings, query=query, kb_ids=kb_ids, doc_ids=doc_ids
        )


async def stream_answer(
    clients: Clients,
    settings: Settings,
    *,
    query: str,
    kb_ids: list[int],
    history: list[ChatMessage],
    creative: bool = False,
    doc_ids: list[int] | None = None,
) -> AsyncIterator[SSEEvent]:
    """产出问答 SSE 事件流。token* → citation → done；异常以 error 事件收尾。"""
    started = time.monotonic()
    try:
        rewritten = await _rewrite_query(clients, history, query)
        blocks = await _retrieve(clients, settings, rewritten, kb_ids, doc_ids)
    except BizError as exc:
        yield ErrorEvent(code=exc.code, message=exc.message)
        return
    except Exception:
        logger.exception("retrieval failed")
        yield ErrorEvent(code=CODE_RAG_RETRIEVE_FAILED, message="检索失败，请稍后重试")
        return

    if not blocks:
        yield ErrorEvent(code=CODE_RAG_SCOPE_EMPTY, message="未检索到相关资料")
        return

    messages = v1.build_qa_messages(
        blocks, history, query, context_token_limit=settings.rag_context_token_limit
    )
    temperature = _CREATIVE_TEMPERATURE if creative else settings.deepseek_temperature

    sanitizer = StreamingDesensitizer()
    first_token_ms: int | None = None
    try:
        async for delta in clients.llm.stream(messages, temperature=temperature):
            if first_token_ms is None:
                first_token_ms = int((time.monotonic() - started) * 1000)
            safe = sanitizer.feed(delta)
            if safe:
                yield TokenEvent(text=safe)
    except APITimeoutError:
        logger.warning("llm stream timeout")
        yield ErrorEvent(code=CODE_LLM_TIMEOUT, message="AI 响应超时，请稍后重试")
        return
    except Exception:
        logger.exception("llm stream failed")
        yield ErrorEvent(code=CODE_RAG_RETRIEVE_FAILED, message="生成失败，请稍后重试")
        return

    tail = sanitizer.flush()
    if tail:
        yield TokenEvent(text=tail)

    answer = sanitizer.full_text
    yield CitationEvent(citations=_build_citations(answer, blocks))
    yield DoneEvent(
        filtered_count=len(blocks),
        first_token_ms=first_token_ms,
        total_ms=int((time.monotonic() - started) * 1000),
    )
