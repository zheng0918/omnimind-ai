"""智能审查编排（REQ-REV）。

create 仅落库 RUNNING 任务并立即返回，审查全图交后台 worker；任务状态与增量风险
为短事务读接口，供前端轮询；处置接口更新单条风险。重活不在请求生命周期内执行。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import CODE_REVIEW_TASK_NOT_FOUND, BizError
from app.models.review import ReviewRisk
from app.repositories import review_repo
from app.schemas.review import (
    Disposition,
    ReviewCreateIn,
    ReviewCreateOut,
    ReviewRiskOut,
    ReviewRisksOut,
    ReviewStatus,
    ReviewSummary,
    ReviewTaskOut,
    RiskDispositionIn,
    Severity,
)


async def create_review(session: AsyncSession, payload: ReviewCreateIn) -> ReviewCreateOut:
    """登记审查任务，返回任务 id 与 RUNNING 状态。"""
    task = await review_repo.create_task(
        session,
        java_task_id=payload.java_task_id,
        kb_id=payload.kb_id,
        target_doc_id=payload.target_doc_id,
        tender_doc_id=payload.tender_doc_id,
        checklist_id=payload.checklist_id,
        strictness=payload.strictness.value,
        use_history=payload.use_history,
        from_write_task_id=payload.from_write_task_id,
    )
    return ReviewCreateOut(review_task_id=task.id, status=ReviewStatus.RUNNING)


async def get_task(session: AsyncSession, review_task_id: int) -> ReviewTaskOut | None:
    """查询审查任务进度摘要。"""
    task = await review_repo.get_task(session, review_task_id)
    if task is None:
        return None
    return ReviewTaskOut(
        review_task_id=task.id,
        status=ReviewStatus(task.status),
        progress=task.progress,
        total_items=task.total_items,
        done_items=task.done_items,
        error_msg=task.error_msg,
    )


def _to_risk_out(row: ReviewRisk) -> ReviewRiskOut:
    return ReviewRiskOut(
        risk_id=row.id,
        severity=Severity(row.severity),
        risk_type=row.risk_type,
        title=row.title,
        description=row.description,
        original_text=row.original_text,
        suggested_text=row.suggested_text,
        source_page=row.source_page,
        source_para_id=row.source_para_id,
        confidence=row.confidence,
        disposition=Disposition(row.disposition),
        related_cases=[str(c) for c in (row.related_cases or [])],
    )


async def list_risks(
    session: AsyncSession, review_task_id: int, *, since_id: int
) -> ReviewRisksOut:
    """增量取 id > since_id 的风险，并附带任务进度与严重度汇总。"""
    task = await review_repo.get_task(session, review_task_id)
    if task is None:
        raise BizError(CODE_REVIEW_TASK_NOT_FOUND, "审查任务不存在")

    risks = await review_repo.list_risks_since(session, review_task_id, since_id)
    counts = await review_repo.severity_counts(session, review_task_id)
    last_id = risks[-1].id if risks else since_id
    return ReviewRisksOut(
        last_id=last_id,
        total_items=task.total_items,
        done_items=task.done_items,
        status=ReviewStatus(task.status),
        summary=ReviewSummary(
            high=counts.get(Severity.HIGH.value, 0),
            medium=counts.get(Severity.MEDIUM.value, 0),
            **{"pass": counts.get(Severity.PASS.value, 0)},
        ),
        risks=[_to_risk_out(r) for r in risks],
    )


async def dispose_risk(
    session: AsyncSession, risk_id: int, payload: RiskDispositionIn
) -> ReviewRiskOut:
    """更新单条风险处置，返回处置后的风险条目。"""
    risk = await review_repo.get_risk(session, risk_id)
    if risk is None:
        raise BizError(CODE_REVIEW_TASK_NOT_FOUND, "风险条目不存在")
    await review_repo.set_disposition(
        session,
        risk,
        disposition=payload.disposition.value,
        ignore_reason=payload.ignore_reason,
        user_edited_text=payload.user_edited_text,
    )
    return _to_risk_out(risk)


__all__ = [
    "create_review",
    "dispose_risk",
    "get_task",
    "list_risks",
]
