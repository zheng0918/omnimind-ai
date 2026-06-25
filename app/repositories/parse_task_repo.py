"""parse_tasks 数据访问。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.parse_task import ParseTask


async def create(
    session: AsyncSession,
    *,
    document_id: int,
    kb_id: int,
    minio_key: str,
    mime_type: str,
) -> ParseTask:
    """新建 PENDING 解析任务并 flush 取得 id。"""
    task = ParseTask(
        document_id=document_id,
        kb_id=kb_id,
        minio_key=minio_key,
        mime_type=mime_type,
        status="PENDING",
        progress=0,
    )
    session.add(task)
    await session.flush()
    return task


async def get(session: AsyncSession, parse_task_id: int) -> ParseTask | None:
    """按 id 取任务。"""
    return await session.get(ParseTask, parse_task_id)


async def get_by_document(session: AsyncSession, document_id: int) -> ParseTask | None:
    """取某文档最新的解析任务。"""
    stmt = (
        select(ParseTask)
        .where(ParseTask.document_id == document_id)
        .order_by(ParseTask.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_unfinished(session: AsyncSession) -> list[ParseTask]:
    """取所有未完成的解析任务（PENDING/PARSING）。

    BackgroundTasks 为进程内、重启即丢；启动时凡 PENDING/PARSING 皆为孤儿，需重新入队。
    """
    stmt = (
        select(ParseTask)
        .where(ParseTask.status.in_(("PENDING", "PARSING")))
        .order_by(ParseTask.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def update_progress(
    session: AsyncSession,
    task: ParseTask,
    *,
    status: str | None = None,
    progress: int | None = None,
    page_count: int | None = None,
    chunk_count: int | None = None,
    error_msg: str | None = None,
) -> None:
    """更新任务状态字段（仅更新非 None 项）。"""
    if status is not None:
        task.status = status
    if progress is not None:
        task.progress = progress
    if page_count is not None:
        task.page_count = page_count
    if chunk_count is not None:
        task.chunk_count = chunk_count
    if error_msg is not None:
        task.error_msg = error_msg
    await session.flush()
