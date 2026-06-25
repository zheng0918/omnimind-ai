"""智能编写 Agent（spec §11.3 / REQ-WRT）。

两段式：
- prepare（后台）：EXTRACTING 抽取评分点 → MATCHING 检索素材规划大纲 → 建 PENDING
  段落并置 GENERATING；落库后前端可轮询大纲/评分点。
- stream（SSE 驱动）：按大纲顺序逐小节检索素材并流式生成正文，token 实时下发、
  完成即落库并自增 done_sections。单连接顺序流式，避免多节 token 交错。

约束：全程 temperature 取生成配置；检索与落库各开短事务，避免流式期间长占连接。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from loguru import logger

from app.clients.registry import Clients
from app.core.config import Settings
from app.core.db import session_scope
from app.core.errors import (
    CODE_RESOURCE_NOT_FOUND,
    CODE_WRITE_SECTION_FAILED,
    CODE_WRITE_TENDER_NOT_PARSED,
    BizError,
)
from app.infra.sse import SSEEvent
from app.prompts import v1
from app.rag.retriever import hybrid_retrieve
from app.repositories import chunk_repo, write_repo
from app.schemas.sse_events import (
    ErrorEvent,
    OutlineDoneEvent,
    OutlineNode,
    OutlineNodeEvent,
    ProgressEvent,
    SectionDoneEvent,
    TokenEvent,
)

_MIN_TENDER_CHARS = 50
_TENDER_PARENT_LIMIT = 40
_SCORE_POINT_MAX = 30
_OUTLINE_MATERIAL_BLOCKS = 5
_SECTION_EVIDENCE_BLOCKS = 4
_OUTLINE_QUERY_POINTS = 5
_OUTLINE_POLL_INTERVAL_S = 1.0
_OUTLINE_POLL_MAX_ATTEMPTS = 180


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
        logger.info(
            "write prepare done task={} score_points={} sections={}",
            write_task_id,
            len(point_texts),
            total,
        )

    async def _extract_score_points(
        self, write_task_id: int, tender_text: str
    ) -> list[str]:
        try:
            messages = v1.build_score_point_extract_messages(tender_text)
            result = await self._clients.llm.json_mode(messages, temperature=0.0)
        except Exception:
            logger.error("score point extract failed task={}", write_task_id)
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
            logger.error("outline build failed, using fallback")
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

    # ---- outline 流（契约 §1.6 /outline/stream）----

    async def stream_outline(self, *, write_task_id: int) -> AsyncIterator[SSEEvent]:
        """等待后台 prepare 产出大纲后，按节点增量下发。

        事件序列：progress*（extracting/matching）→ token{node}* → done{totalNodes,matchedMaterials}。
        """
        ready = False
        for _ in range(_OUTLINE_POLL_MAX_ATTEMPTS):
            snapshot = await self._load_outline_snapshot(write_task_id)
            if snapshot is None:
                yield ErrorEvent(code=CODE_RESOURCE_NOT_FOUND, message="编写任务不存在")
                return
            status, nodes, point_count = snapshot
            if status == "FAILED":
                yield ErrorEvent(
                    code=CODE_WRITE_TENDER_NOT_PARSED, message="招标解析或大纲规划失败"
                )
                return
            if status in {"GENERATING", "DONE"} and nodes:
                ready = True
                break
            stage = "matching" if status == "MATCHING" else "extracting"
            yield ProgressEvent(stage=stage, percent=30 if stage == "matching" else 10)
            await asyncio.sleep(_OUTLINE_POLL_INTERVAL_S)

        if not ready:
            yield ErrorEvent(code=CODE_WRITE_TENDER_NOT_PARSED, message="大纲规划超时")
            return

        snapshot = await self._load_outline_snapshot(write_task_id)
        if snapshot is None:
            yield ErrorEvent(code=CODE_RESOURCE_NOT_FOUND, message="编写任务不存在")
            return
        _, nodes, point_count = snapshot
        yield ProgressEvent(stage="done", percent=100)
        for node in nodes:
            yield OutlineNodeEvent(
                node=OutlineNode(
                    node_id=node.id,
                    parent_id=node.parent_id,
                    title=node.title,
                    order_idx=node.order_idx,
                    section_id=node.section_id,
                )
            )
        yield OutlineDoneEvent(total_nodes=len(nodes), matched_materials=point_count)
        logger.info(
            "write outline streamed task={} nodes={} score_points={}",
            write_task_id,
            len(nodes),
            point_count,
        )

    async def _load_outline_snapshot(
        self, write_task_id: int
    ) -> tuple[str, list, int] | None:
        async with session_scope() as session:
            task = await write_repo.get_task(session, write_task_id)
            if task is None:
                return None
            nodes = await write_repo.list_outline(session, write_task_id)
            point_count = len(await write_repo.list_score_points(session, write_task_id))
        return task.status, nodes, point_count

    # ---- 单章节流（契约 §1.6 /sections/{sid}/stream）----

    async def stream_section(
        self, *, write_task_id: int, section_id: int
    ) -> AsyncIterator[SSEEvent]:
        """流式生成单个小节正文：token* → done{sectionId,status}。"""
        ctx = await self._load_section_context(write_task_id, section_id)
        if ctx is None:
            yield ErrorEvent(code=CODE_RESOURCE_NOT_FOUND, message="小节不存在或任务未就绪")
            return
        kb_id, point_texts, project_params, chapter_title, section_title = ctx

        errored = False
        async for event in self._stream_one(
            kb_id, point_texts, project_params, section_id, chapter_title, section_title
        ):
            if isinstance(event, ErrorEvent):
                errored = True
            yield event
        if errored:
            return
        await self._finalize(write_task_id)
        logger.info(
            "write section streamed task={} section={}", write_task_id, section_id
        )
        yield SectionDoneEvent(section_id=section_id, status="DONE")

    async def _load_section_context(
        self, write_task_id: int, section_id: int
    ) -> tuple[int, list[str], dict[str, str], str, str] | None:
        async with session_scope() as session:
            task = await write_repo.get_task(session, write_task_id)
            if task is None or task.status not in {"GENERATING", "DONE"}:
                return None
            section = await write_repo.get_section(session, section_id)
            if section is None or section.write_task_id != write_task_id:
                return None
            point_texts = [
                p.point_text for p in await write_repo.list_score_points(session, write_task_id)
            ]
            params = {k: str(v) for k, v in (task.project_params_json or {}).items() if v}
            nodes = {n.id: n for n in await write_repo.list_outline(session, write_task_id)}
            node = nodes.get(section.outline_node_id) if section.outline_node_id else None
            section_title = node.title if node else "正文"
            parent = nodes.get(node.parent_id) if node and node.parent_id else None
            chapter_title = parent.title if parent else section_title
            kb_id = task.kb_id
        return kb_id, point_texts, params, chapter_title, section_title

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
                code=CODE_WRITE_SECTION_FAILED, message=f"小节生成失败（id={section_id}）"
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
