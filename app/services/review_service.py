"""智能审查编排（REQ-REV）。

create 仅落库 RUNNING 任务并立即返回，审查全图交后台 worker；任务状态与增量风险
为短事务读接口，供前端轮询；处置接口更新单条风险。重活不在请求生命周期内执行。
"""

from __future__ import annotations

import base64

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import CODE_REVIEW_TASK_NOT_FOUND, BizError
from app.infra import report
from app.models.review import ReviewRisk
from app.repositories import review_repo
from app.schemas.common import ExportFileOut
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
    logger.info(
        "review task created task={} java_task_id={} kb={} target_doc={} tender_doc={}",
        task.id,
        payload.java_task_id,
        payload.kb_id,
        payload.target_doc_id,
        payload.tender_doc_id,
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
        bbox=row.bbox,
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
    logger.info(
        "review risk disposed risk={} disposition={}", risk_id, payload.disposition.value
    )
    return _to_risk_out(risk)


_SEVERITY_LABEL = {
    Severity.HIGH.value: "高危",
    Severity.MEDIUM.value: "中风险",
    Severity.PASS.value: "通过",
}


def _build_report_blocks(
    risks: list[ReviewRisk], counts: dict[str, int]
) -> list[report.Block]:
    """把审查风险拼成报告块（概览 + 逐条）。"""
    high = counts.get(Severity.HIGH.value, 0)
    medium = counts.get(Severity.MEDIUM.value, 0)
    passed = counts.get(Severity.PASS.value, 0)
    blocks: list[report.Block] = [
        (
            "p",
            f"概览：高危 {high} 条、中风险 {medium} 条、通过 {passed} 条，共 {len(risks)} 条。",
        )
    ]
    for idx, risk in enumerate(risks, start=1):
        label = _SEVERITY_LABEL.get(risk.severity, risk.severity)
        blocks.append(("h2", f"{idx}. [{label}] {risk.title}"))
        if risk.description:
            blocks.append(("p", risk.description))
        if risk.suggested_text:
            blocks.append(("p", f"建议：{risk.suggested_text}"))
        if risk.source_page is not None:
            para = f" {risk.source_para_id}" if risk.source_para_id else ""
            blocks.append(("p", f"出处：第 {risk.source_page} 页{para}"))
    return blocks


async def export(
    session: AsyncSession, review_task_id: int, fmt: str
) -> ExportFileOut:
    """导出审查报告为 docx/pdf 字节（base64），由 Java 落桶 + 预签名（契约 §1.5）。"""
    task = await review_repo.get_task(session, review_task_id)
    if task is None:
        raise BizError(CODE_REVIEW_TASK_NOT_FOUND, "审查任务不存在")
    risks = await review_repo.list_risks_since(session, review_task_id, 0)
    counts = await review_repo.severity_counts(session, review_task_id)
    blocks = _build_report_blocks(risks, counts)
    data, content_type, ext = report.render("智能审查报告", blocks, fmt)
    logger.info(
        "review report exported task={} fmt={} risks={}", review_task_id, fmt, len(risks)
    )
    return ExportFileOut(
        filename=f"审查报告-{review_task_id}.{ext}",
        content_type=content_type,
        content_base64=base64.b64encode(data).decode("ascii"),
    )


__all__ = [
    "create_review",
    "dispose_risk",
    "export",
    "get_task",
    "list_risks",
]
