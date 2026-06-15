"""解析任务编排（REQ-KB-04）。

submit 仅落库 PENDING 并立即返回，重活交给后台 worker；status 查询读任务表。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import parse_task_repo
from app.schemas.parse import ParseStatus, ParseStatusOut, ParseSubmitIn, ParseSubmitOut


async def submit_parse(session: AsyncSession, payload: ParseSubmitIn) -> ParseSubmitOut:
    """登记解析任务，返回任务 id 与 PENDING 状态。"""
    task = await parse_task_repo.create(
        session,
        document_id=payload.document_id,
        kb_id=payload.kb_id,
        minio_key=payload.minio_key,
        mime_type=payload.mime_type,
    )
    return ParseSubmitOut(parse_task_id=task.id, status=ParseStatus.PENDING)


async def get_status(session: AsyncSession, parse_task_id: int) -> ParseStatusOut | None:
    """查询解析进度。"""
    task = await parse_task_repo.get(session, parse_task_id)
    if task is None:
        return None
    return ParseStatusOut(
        document_id=task.document_id,
        status=ParseStatus(task.status),
        progress=task.progress,
        page_count=task.page_count,
        error_msg=task.error_msg,
    )
