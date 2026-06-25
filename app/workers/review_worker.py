"""审查后台任务（REQ-REV 全链路）。

供 BackgroundTasks 调度：装载任务参数 → 运行 ReviewAgent → 失败置 FAILED。
支持对 RUNNING 任务从 done_items 续审（断点续审钩子）。不向调用方泄露堆栈。
"""

from __future__ import annotations

from loguru import logger

from app.agents.review_agent import ReviewAgent
from app.clients.registry import Clients
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.trace import trace_id_ctx
from app.repositories import review_repo


async def run_review(review_task_id: int, clients: Clients, trace_id: str) -> None:
    """执行审查全链路。"""
    trace_id_ctx.set(trace_id)
    settings = get_settings()
    logger.info("review worker start task={}", review_task_id)
    try:
        async with session_scope() as session:
            task = await review_repo.get_task(session, review_task_id)
            if task is None:
                logger.error("review task not found id={}", review_task_id)
                return
            kb_id = task.kb_id
            target_doc_id = task.target_doc_id
            tender_doc_id = task.tender_doc_id
            checklist_id = str(task.checklist_id) if task.checklist_id else None
            strictness = task.strictness
            resume_from = task.done_items

        agent = ReviewAgent(clients, settings)
        await agent.run(
            review_task_id=review_task_id,
            kb_id=kb_id,
            target_doc_id=target_doc_id,
            tender_doc_id=tender_doc_id,
            checklist_id=checklist_id,
            strictness=strictness,
            resume_from=resume_from,
        )
        logger.info("review done task={}", review_task_id)
    except Exception as exc:
        await _handle_failure(review_task_id, exc)


async def _handle_failure(review_task_id: int, exc: Exception) -> None:
    logger.error("review failed task={} type={}", review_task_id, type(exc).__name__)
    try:
        async with session_scope() as session:
            task = await review_repo.get_task(session, review_task_id)
            if task is not None:
                message = getattr(exc, "message", "审查失败")
                await review_repo.update_task(
                    session, task, status="FAILED", error_msg=message
                )
    except Exception:
        logger.exception("failed to mark review FAILED id={}", review_task_id)
