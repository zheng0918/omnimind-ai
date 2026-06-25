"""编写准备后台任务（REQ-WRT）。

供 BackgroundTasks 调度：抽取评分点 + 规划大纲（WriteAgent.prepare），就绪后置
GENERATING，章节正文由前端经 SSE 流驱动生成。失败置 FAILED，不向调用方泄露堆栈。
"""

from __future__ import annotations

from loguru import logger

from app.agents.write_agent import WriteAgent
from app.clients.registry import Clients
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import CODE_WRITE_TENDER_NOT_PARSED, BizError
from app.core.trace import trace_id_ctx
from app.repositories import write_repo


async def run_write_prepare(write_task_id: int, clients: Clients, trace_id: str) -> None:
    """执行评分点抽取与大纲规划。"""
    trace_id_ctx.set(trace_id)
    settings = get_settings()
    logger.info("write prepare worker start task={}", write_task_id)
    try:
        async with session_scope() as session:
            task = await write_repo.get_task(session, write_task_id)
            if task is None:
                logger.error("write task not found id={}", write_task_id)
                return
            kb_id = task.kb_id
            tender_doc_id = task.tender_doc_id

        if tender_doc_id is None:
            raise BizError(CODE_WRITE_TENDER_NOT_PARSED, "编写任务缺少招标文件")
        agent = WriteAgent(clients, settings)
        await agent.prepare(
            write_task_id=write_task_id, kb_id=kb_id, tender_doc_id=tender_doc_id
        )
        logger.info("write prepare done task={}", write_task_id)
    except Exception as exc:
        await _handle_failure(write_task_id, exc)


async def _handle_failure(write_task_id: int, exc: Exception) -> None:
    logger.error("write prepare failed task={} type={}", write_task_id, type(exc).__name__)
    try:
        async with session_scope() as session:
            task = await write_repo.get_task(session, write_task_id)
            if task is not None:
                message = getattr(exc, "message", "编写准备失败")
                await write_repo.update_task(
                    session, task, status="FAILED", error_msg=message
                )
    except Exception:
        logger.exception("failed to mark write FAILED id={}", write_task_id)
