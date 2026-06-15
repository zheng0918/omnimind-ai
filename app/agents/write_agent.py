"""智能编写 Agent（spec §11.3 / REQ-WRT）。

两段式：
- prepare（后台）：EXTRACTING 抽取评分点 → MATCHING 检索素材规划大纲 → 建 PENDING
  段落并置 GENERATING；落库后前端可轮询大纲/评分点。
- stream（SSE 驱动）：按大纲顺序逐小节检索素材并流式生成正文，token 实时下发、
  完成即落库并自增 done_sections。单连接顺序流式，避免多节 token 交错。

约束：全程 temperature 取生成配置；检索与落库各开短事务，避免流式期间长占连接。
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from loguru import logger

from app.clients.registry import Clients
from app.core.config import Settings
from app.core.db import session_scope
from app.core.errors import CODE_WRITE_TENDER_NOT_PARSED, BizError
from app.infra.sse import SSEEvent
from app.prompts import v1
from app.rag.retriever import hybrid_retrieve
from app.repositories import chunk_repo, write_repo
from app.schemas.sse_events import DoneEvent, ErrorEvent, ProgressEvent, TokenEvent

_MIN_TENDER_CHARS = 50
_TENDER_PARENT_LIMIT = 40
_SCORE_POINT_MAX = 30
_OUTLINE_MATERIAL_BLOCKS = 5
_SECTION_EVIDENCE_BLOCKS = 4
_OUTLINE_QUERY_POINTS = 5


class WriteAgent:
    """编写编排。prepare 产出大纲，stream 流式生成正文。"""

    def __init__(self, clients: Clients, settings: Settings) -> None:
        self._clients = clients
        self._settings = settings
        self._model = settings.deepseek_model

    async def _load_doc_text(self, document_id: int, limit: int) -> str:
        async with session_scope() as session:
            parents = await chunk_repo.get_document_parents(session, document_id, limit)
        return "\n\n".join(p.text for p in parents)

    # ---- prepare（后台）----

    async def prepare(
        self, *, write_task_id: int, kb_id: int, tender_doc_id: int
    ) -> None:
        """抽取评分点 + 规划大纲 + 建 PENDING 段落，置 GENERATING。"""
        tender_text = await self._load_doc_text(tender_doc_id, _TENDER_PARENT_LIMIT)
        if len(tender_text.strip()) < _MIN_TENDER_CHARS:
            raise BizError(CODE_WRITE_TENDER_NOT_PARSED, "招标文件内容过少或未解析完成")

        point_texts = await self._extract_score_points(write_task_id, tender_text)
        materials = await self._retrieve_materials(
            kb_id, "\n".join(point_texts[:_OUTLINE_QUERY_POINTS]), _OUTLINE_MATERIAL_BLOCKS
        )
        outline = await self._build_outline(point_texts, materials)

        total = await self._persist_outline(write_task_id, outline)
        async with session_scope() as session:
            task = await write_repo.get_task(session, write_task_id)
            if task is not None:
                await write_repo.update_task(
                    session, task, status="GENERATING", total_sections=total
                )

    async def _extract_score_points(
        self, write_task_id: int, tender_text: str
    ) -> list[str]:
        try:
            messages = v1.build_score_point_extract_messages(tender_text)
            result = await self._clients.llm.json_mode(messages, temperature=0.0)
        except Exception:
            logger.warning("score point extract failed task={}", write_task_id)
            result = {}
        texts: list[str] = []
        async with session_scope() as session:
            for raw in result.get("points", [])[:_SCORE_POINT_MAX]:
                text = str(raw.get("pointText", "")).strip()
                if not text:
                    continue
                weight_raw = raw.get("weight")
                weight = float(weight_raw) if isinstance(weight_raw, (int, float)) else None
                await write_repo.add_score_point(
                    session, write_task_id=write_task_id, point_text=text, weight=weight
                )
                texts.append(text)
        return texts

    async def _retrieve_materials(self, kb_id: int, query: str, limit: int) -> str:
        if not query.strip():
            return ""
        async with session_scope() as session:
            blocks = await hybrid_retrieve(
                session, self._clients, self._settings, query=query, kb_ids=[kb_id]
            )
        return "\n\n".join(b.text for b in blocks[:limit])

    async def _build_outline(
        self, point_texts: list[str], materials: str
    ) -> list[tuple[str, list[str]]]:
        try:
            messages = v1.build_outline_messages(point_texts, materials)
            result = await self._clients.llm.json_mode(messages, temperature=0.0)
        except Exception:
            logger.warning("outline build failed, using fallback")
            result = {}
        outline: list[tuple[str, list[str]]] = []
        for raw in result.get("outline", []):
            title = str(raw.get("title", "")).strip()
            sections = [str(s).strip() for s in raw.get("sections", []) if str(s).strip()]
            if not title or not sections:
                continue
            outline.append((title, sections))
        if not outline:
            outline = [("投标方案", ["项目理解与总体方案"])]
        return outline

    async def _persist_outline(
        self, write_task_id: int, outline: list[tuple[str, list[str]]]
    ) -> int:
        total = 0
        async with session_scope() as session:
            order = 0
            for chapter_title, sections in outline:
                chapter = await write_repo.add_outline_node(
                    session,
                    write_task_id=write_task_id,
                    parent_id=None,
                    title=chapter_title,
                    order_idx=order,
                )
                order += 1
                for section_title in sections:
                    node = await write_repo.add_outline_node(
                        session,
                        write_task_id=write_task_id,
                        parent_id=chapter.id,
                        title=section_title,
                        order_idx=order,
                    )
                    order += 1
                    section = await write_repo.add_section(
                        session, write_task_id=write_task_id, outline_node_id=node.id
                    )
                    await write_repo.link_section(session, node, section.id)
                    total += 1
        return total

    # ---- stream（SSE）----

    async def stream(self, *, write_task_id: int) -> AsyncIterator[SSEEvent]:
        """按大纲顺序逐小节流式生成正文，token 实时下发并落库。"""
        started = time.monotonic()
        ctx = await self._load_stream_context(write_task_id)
        if ctx is None:
            yield ErrorEvent(code=CODE_WRITE_TENDER_NOT_PARSED, message="编写任务尚未就绪")
            return
        kb_id, point_texts, project_params, pending = ctx
        total = len(pending)

        for idx, item in enumerate(pending, start=1):
            section_id, chapter_title, section_title = item
            yield ProgressEvent(
                stage=f"section:{section_id}", percent=int(idx / total * 100)
            )
            async for event in self._stream_one(
                kb_id, point_texts, project_params, section_id, chapter_title, section_title
            ):
                yield event

        await self._finalize(write_task_id)
        yield DoneEvent(total_ms=int((time.monotonic() - started) * 1000))

    async def _load_stream_context(
        self, write_task_id: int
    ) -> tuple[int, list[str], dict[str, str], list[tuple[int, str, str]]] | None:
        async with session_scope() as session:
            task = await write_repo.get_task(session, write_task_id)
            if task is None or task.status not in {"GENERATING", "DONE"}:
                return None
            point_texts = [
                p.point_text for p in await write_repo.list_score_points(session, write_task_id)
            ]
            params = {k: str(v) for k, v in (task.project_params_json or {}).items() if v}
            nodes = {n.id: n for n in await write_repo.list_outline(session, write_task_id)}
            sections = await write_repo.list_sections(session, write_task_id)
            pending: list[tuple[int, str, str]] = []
            for s in sections:
                if s.status not in {"PENDING", "FAILED"}:
                    continue
                node = nodes.get(s.outline_node_id) if s.outline_node_id else None
                section_title = node.title if node else "正文"
                parent = nodes.get(node.parent_id) if node and node.parent_id else None
                chapter_title = parent.title if parent else section_title
                pending.append((s.id, chapter_title, section_title))
            kb_id = task.kb_id
        return kb_id, point_texts, params, pending

    async def _stream_one(
        self,
        kb_id: int,
        point_texts: list[str],
        project_params: dict[str, str],
        section_id: int,
        chapter_title: str,
        section_title: str,
    ) -> AsyncIterator[SSEEvent]:
        query = f"{chapter_title} {section_title}"
        materials = await self._retrieve_materials(kb_id, query, _SECTION_EVIDENCE_BLOCKS)
        messages = v1.build_section_messages(
            chapter_title, section_title, point_texts, materials, project_params
        )
        parts: list[str] = []
        try:
            async for delta in self._clients.llm.stream(
                messages, temperature=self._settings.deepseek_temperature
            ):
                parts.append(delta)
                yield TokenEvent(text=delta)
        except Exception:
            logger.exception("section generate failed id={}", section_id)
            await self._save_section(section_id, "".join(parts), "FAILED")
            yield ErrorEvent(
                code=CODE_WRITE_TENDER_NOT_PARSED, message=f"小节生成失败（id={section_id}）"
            )
            return
        await self._save_section(section_id, "".join(parts), "DONE")

    async def _save_section(self, section_id: int, content: str, status: str) -> None:
        async with session_scope() as session:
            section = await write_repo.get_section(session, section_id)
            if section is None:
                return
            await write_repo.update_section(
                session,
                section,
                content_md=content,
                status=status,
                ai_model=self._model,
                prompt_ver=v1.PROMPT_VERSION,
                generated_at=datetime.now(UTC),
            )
            if status == "DONE":
                await write_repo.bump_done_sections(session, section.write_task_id)

    async def _finalize(self, write_task_id: int) -> None:
        async with session_scope() as session:
            task = await write_repo.get_task(session, write_task_id)
            if task is None:
                return
            sections = await write_repo.list_sections(session, write_task_id)
            all_done = all(s.status in {"DONE", "USER_EDITED"} for s in sections)
            await write_repo.update_task(
                session, task, status="DONE" if all_done else "GENERATING"
            )
