"""智能审查 Agent（LangGraph，spec §11.2）。

图：extract（装配待审文本 + 内置清单 + 招标文件抽取）→ judge（并行判定每条要点）
→ finalize（置 DONE）。强制约束：
- 并发用 asyncio.Semaphore(REVIEW_PARALLEL)，禁止裸 gather 万级 fan-out；
- 单条失败 tenacity 重试 agent_max_retry 次，最终失败写 severity=PASS, confidence=0；
- 每条判定持久化 done_items（原子自增），支持 RUNNING 任务从 done_items 续审；
- 全程 temperature=0 + JSON Mode；严格度阈值后处理过滤。
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.agents.checklists import ChecklistItem, builtin_checklist
from app.clients.registry import Clients
from app.core.config import Settings
from app.core.db import session_scope
from app.core.errors import CODE_REVIEW_DOC_TOO_SHORT, BizError
from app.prompts import v1
from app.rag.retriever import hybrid_retrieve
from app.repositories import chunk_repo, review_repo

_MIN_TARGET_CHARS = 50
_EVIDENCE_BLOCKS = 3
_TARGET_PARENT_LIMIT = 40
_EXTRACT_MAX_ITEMS = 20

_STRICTNESS_THRESHOLD = {"LOOSE": 0.85, "BALANCED": 0.7, "STRICT": 0.5}
_VALID_SEVERITY = {"HIGH", "MEDIUM", "PASS"}


class ReviewState(TypedDict, total=False):
    """审查图状态。"""

    review_task_id: int
    kb_id: int
    target_doc_id: int
    tender_doc_id: int | None
    checklist_id: str | None
    threshold: float
    resume_from: int
    items: list[ChecklistItem]


def threshold_for(strictness: str) -> float:
    """严格度 → 置信度阈值。未知值按 BALANCED。"""
    return _STRICTNESS_THRESHOLD.get(strictness, 0.7)


class ReviewAgent:
    """审查编排。每次 run 处理一个 review_task。"""

    def __init__(self, clients: Clients, settings: Settings) -> None:
        self._clients = clients
        self._settings = settings
        self._model = settings.deepseek_model

    async def run(
        self,
        *,
        review_task_id: int,
        kb_id: int,
        target_doc_id: int,
        tender_doc_id: int | None,
        checklist_id: str | None,
        strictness: str,
        resume_from: int,
    ) -> None:
        """执行审查全图。"""
        state: ReviewState = {
            "review_task_id": review_task_id,
            "kb_id": kb_id,
            "target_doc_id": target_doc_id,
            "tender_doc_id": tender_doc_id,
            "checklist_id": checklist_id,
            "threshold": threshold_for(strictness),
            "resume_from": resume_from,
        }
        await self._build_graph().ainvoke(state)

    def _build_graph(self) -> Any:
        graph: Any = StateGraph(ReviewState)
        graph.add_node("extract", self._extract)
        graph.add_node("judge", self._judge)
        graph.add_node("finalize", self._finalize)
        graph.set_entry_point("extract")
        graph.add_edge("extract", "judge")
        graph.add_edge("judge", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    async def _load_doc_text(self, document_id: int, limit: int) -> str:
        async with session_scope() as session:
            parents = await chunk_repo.get_document_parents(session, document_id, limit)
        return "\n\n".join(p.text for p in parents)

    async def _extract(self, state: ReviewState) -> dict[str, Any]:
        """装配待审文本 + 合并内置清单与招标文件抽取，落库 total_items。"""
        target_text = await self._load_doc_text(
            state["target_doc_id"], _TARGET_PARENT_LIMIT
        )
        if len(target_text.strip()) < _MIN_TARGET_CHARS:
            raise BizError(CODE_REVIEW_DOC_TOO_SHORT, "待审文档内容过少，无法审查")

        items: list[ChecklistItem] = builtin_checklist(state["checklist_id"])
        if state["tender_doc_id"] is not None:
            items = items + await self._extract_from_tender(state["tender_doc_id"])

        async with session_scope() as session:
            task = await review_repo.get_task(session, state["review_task_id"])
            if task is not None:
                await review_repo.update_task(
                    session, task, total_items=len(items), status="RUNNING"
                )
        logger.info(
            "review extract done task={} total_items={} resume_from={}",
            state["review_task_id"],
            len(items),
            state["resume_from"],
        )
        return {"items": items}

    async def _extract_from_tender(self, tender_doc_id: int) -> list[ChecklistItem]:
        tender_text = await self._load_doc_text(tender_doc_id, _TARGET_PARENT_LIMIT)
        if not tender_text.strip():
            return []
        try:
            messages = v1.build_checklist_extract_messages(tender_text)
            result = await self._clients.llm.json_mode(messages, temperature=0.0)
        except Exception:
            logger.error("checklist extract failed, builtin only")
            return []
        extracted: list[ChecklistItem] = []
        for idx, raw in enumerate(result.get("items", [])[:_EXTRACT_MAX_ITEMS]):
            title = str(raw.get("title", "")).strip()
            requirement = str(raw.get("requirement", "")).strip()
            if not title or not requirement:
                continue
            extracted.append(
                ChecklistItem(
                    id=f"tender-{idx}",
                    title=title,
                    requirement=requirement,
                    risk_type=str(raw.get("riskType", "risk")),
                )
            )
        return extracted

    async def _judge(self, state: ReviewState) -> dict[str, Any]:
        """并行判定每条要点（Semaphore 限流），续审跳过已完成项。"""
        items = state["items"][state["resume_from"] :]
        total = len(state["items"])
        sem = asyncio.Semaphore(self._settings.review_parallel)

        async def worker(item: ChecklistItem) -> None:
            async with sem:
                await self._judge_one(state, item, total)

        await asyncio.gather(*(worker(item) for item in items))
        return {}

    async def _judge_one(
        self, state: ReviewState, item: ChecklistItem, total: int
    ) -> None:
        try:
            judgement = await asyncio.wait_for(
                self._call_judge(state, item),
                timeout=self._settings.agent_step_timeout_s,
            )
        except Exception:
            logger.error("judge item failed after retries id={}", item.id)
            judgement = {
                "severity": "PASS",
                "risk_type": item.risk_type,
                "title": item.title,
                "description": "自动判定失败，已置为通过待人工复核",
                "confidence": 0.0,
                "page": None,
                "para_id": None,
                "bbox": None,
            }
        await self._save(state, judgement, total)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=3), reraise=True)
    async def _call_judge(
        self, state: ReviewState, item: ChecklistItem
    ) -> dict[str, Any]:
        async with session_scope() as session:
            # 限定检索范围为被审文档本身：审查判定的是该投标文件是否满足要求，
            # 证据须取自 target 文档，避免召回库内其它文档导致误判与错误溯源页码。
            blocks = await hybrid_retrieve(
                session,
                self._clients,
                self._settings,
                query=item.requirement,
                kb_ids=[state["kb_id"]],
                doc_ids=[state["target_doc_id"]],
            )
        evidence = "\n\n".join(b.text for b in blocks[:_EVIDENCE_BLOCKS])
        messages = v1.build_risk_judge_messages(item.title, item.requirement, evidence)
        result = await self._clients.llm.json_mode(messages, temperature=0.0)

        severity = str(result.get("severity", "PASS")).upper()
        if severity not in _VALID_SEVERITY:
            severity = "PASS"
        risk_type = str(result.get("riskType", item.risk_type))
        confidence = float(result.get("confidence", 0.0))
        # 缺失项豁免阈值降级：招标硬性要求确实缺失时检索常召回为空、confidence 偏低，
        # 若按阈值一并过滤，会把最该暴露的缺失项悄悄改判为 PASS。
        if (
            severity != "PASS"
            and risk_type != "missing"
            and confidence < state["threshold"]
        ):
            severity = "PASS"
        top = blocks[0] if blocks else None
        return {
            "severity": severity,
            "risk_type": risk_type,
            "title": str(result.get("title", item.title)),
            "description": result.get("description"),
            "original_text": result.get("originalText"),
            "suggested_text": result.get("suggestedText"),
            "confidence": confidence,
            "page": top.page if top else None,
            "para_id": top.paragraph_id if top else None,
            "bbox": top.bbox if top else None,
        }

    async def _save(
        self, state: ReviewState, judgement: dict[str, Any], total: int
    ) -> None:
        async with session_scope() as session:
            await review_repo.add_risk(
                session,
                review_task_id=state["review_task_id"],
                severity=judgement["severity"],
                risk_type=judgement.get("risk_type"),
                title=judgement.get("title"),
                description=judgement.get("description"),
                original_text=judgement.get("original_text"),
                suggested_text=judgement.get("suggested_text"),
                source_page=judgement.get("page"),
                source_para_id=judgement.get("para_id"),
                confidence=judgement.get("confidence"),
                bbox=judgement.get("bbox"),
                related_cases=None,
                ai_model=self._model,
                prompt_ver=v1.PROMPT_VERSION,
            )
            await review_repo.bump_done_items(session, state["review_task_id"], total)

    async def _finalize(self, state: ReviewState) -> dict[str, Any]:
        async with session_scope() as session:
            task = await review_repo.get_task(session, state["review_task_id"])
            if task is not None:
                await review_repo.update_task(
                    session, task, status="DONE", progress=100
                )
        logger.info("review finalize done task={}", state["review_task_id"])
        return {}
