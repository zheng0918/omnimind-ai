"""review_tasks / review_risks 数据访问（REQ-REV）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import ReviewRisk, ReviewTask


async def create_task(
    session: AsyncSession,
    *,
    java_task_id: int,
    kb_id: int,
    target_doc_id: int,
    tender_doc_id: int | None,
    checklist_id: str | None,
    strictness: str,
    use_history: bool,
    from_write_task_id: int | None,
) -> ReviewTask:
    """新建 RUNNING 审查任务并 flush 取得 id。"""
    task = ReviewTask(
        java_task_id=java_task_id,
        kb_id=kb_id,
        target_doc_id=target_doc_id,
        tender_doc_id=tender_doc_id,
        checklist_id=checklist_id,
        strictness=strictness,
        status="RUNNING",
        use_history=use_history,
        from_write_task_id=from_write_task_id,
    )
    session.add(task)
    await session.flush()
    return task


async def get_task(session: AsyncSession, review_task_id: int) -> ReviewTask | None:
    """按 id 取审查任务。"""
    return await session.get(ReviewTask, review_task_id)


async def update_task(
    session: AsyncSession,
    task: ReviewTask,
    *,
    status: str | None = None,
    progress: int | None = None,
    total_items: int | None = None,
    done_items: int | None = None,
    error_msg: str | None = None,
) -> None:
    """更新任务字段（仅非 None 项）。"""
    if status is not None:
        task.status = status
    if progress is not None:
        task.progress = progress
    if total_items is not None:
        task.total_items = total_items
    if done_items is not None:
        task.done_items = done_items
    if error_msg is not None:
        task.error_msg = error_msg
    await session.flush()


async def add_risk(
    session: AsyncSession,
    *,
    review_task_id: int,
    severity: str,
    risk_type: str | None,
    title: str | None,
    description: str | None,
    original_text: str | None,
    suggested_text: str | None,
    source_page: int | None,
    source_para_id: str | None,
    confidence: float | None,
    related_cases: list[Any] | None,
    ai_model: str | None,
    prompt_ver: str | None,
) -> ReviewRisk:
    """写入一条风险并 flush。"""
    risk = ReviewRisk(
        review_task_id=review_task_id,
        severity=severity,
        risk_type=risk_type,
        title=title,
        description=description,
        original_text=original_text,
        suggested_text=suggested_text,
        source_page=source_page,
        source_para_id=source_para_id,
        confidence=confidence,
        related_cases=related_cases,
        ai_model=ai_model,
        prompt_ver=prompt_ver,
    )
    session.add(risk)
    await session.flush()
    return risk


async def bump_done_items(
    session: AsyncSession, review_task_id: int, total_items: int
) -> int:
    """原子自增 done_items 并同步 progress（并发安全），返回最新 done_items。"""
    done = int(
        (
            await session.execute(
                update(ReviewTask)
                .where(ReviewTask.id == review_task_id)
                .values(done_items=ReviewTask.done_items + 1)
                .returning(ReviewTask.done_items)
            )
        ).scalar_one()
    )
    progress = min(99, int(done / total_items * 100)) if total_items > 0 else 99
    await session.execute(
        update(ReviewTask).where(ReviewTask.id == review_task_id).values(progress=progress)
    )
    return done


async def list_risks_since(
    session: AsyncSession, review_task_id: int, since_id: int
) -> list[ReviewRisk]:
    """增量取 id > since_id 的风险（升序），供前端轮询。"""
    stmt = (
        select(ReviewRisk)
        .where(ReviewRisk.review_task_id == review_task_id, ReviewRisk.id > since_id)
        .order_by(ReviewRisk.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def severity_counts(session: AsyncSession, review_task_id: int) -> dict[str, int]:
    """统计各 severity 的数量。"""
    stmt = (
        select(ReviewRisk.severity, func.count())
        .where(ReviewRisk.review_task_id == review_task_id)
        .group_by(ReviewRisk.severity)
    )
    rows = (await session.execute(stmt)).all()
    return {severity: int(count) for severity, count in rows}


async def get_risk(session: AsyncSession, risk_id: int) -> ReviewRisk | None:
    """按 id 取风险。"""
    return await session.get(ReviewRisk, risk_id)


async def set_disposition(
    session: AsyncSession,
    risk: ReviewRisk,
    *,
    disposition: str,
    ignore_reason: str | None,
    user_edited_text: str | None,
) -> None:
    """更新风险处置。"""
    risk.disposition = disposition
    risk.ignore_reason = ignore_reason
    risk.user_edited_text = user_edited_text
    await session.flush()
