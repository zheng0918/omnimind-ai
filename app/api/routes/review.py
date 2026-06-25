"""智能审查路由（REQ-REV）。

启动审查为普通 JSON 接口（落库后台执行）；进度与增量风险供前端轮询；处置接口
更新单条风险。审查全图在后台 worker 运行，请求会话提交后任务记录方可见。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Query
from loguru import logger

from app.api.deps import ClientsDep, SessionDep, ok
from app.core.errors import CODE_RESOURCE_NOT_FOUND, BizError
from app.core.trace import get_trace_id
from app.schemas.common import ExportIn
from app.schemas.review import ReviewCreateIn, RiskDispositionIn
from app.services import review_service
from app.workers.review_worker import run_review

router = APIRouter(prefix="/ai/v1/review", tags=["review"])


@router.post("")
async def create_review(
    payload: ReviewCreateIn,
    session: SessionDep,
    clients: ClientsDep,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """登记审查任务并立即返回；审查在后台执行。"""
    result = await review_service.create_review(session, payload)
    background_tasks.add_task(
        run_review, result.review_task_id, clients, get_trace_id()
    )
    logger.info("review task scheduled task={}", result.review_task_id)
    return ok(result)


@router.get("/{review_task_id}")
async def get_review(review_task_id: int, session: SessionDep) -> dict[str, Any]:
    """查询审查任务进度摘要。"""
    task = await review_service.get_task(session, review_task_id)
    if task is None:
        raise BizError(CODE_RESOURCE_NOT_FOUND, "审查任务不存在")
    return ok(task)


@router.get("/{review_task_id}/risks")
async def list_risks(
    review_task_id: int,
    session: SessionDep,
    since_id: Annotated[int, Query(alias="since", ge=0)] = 0,
) -> dict[str, Any]:
    """增量拉取风险条目（id > sinceId），附带进度与严重度汇总。"""
    result = await review_service.list_risks(session, review_task_id, since_id=since_id)
    return ok(result)


@router.post("/risks/{risk_id}/disposition")
async def dispose_risk(
    risk_id: int, payload: RiskDispositionIn, session: SessionDep
) -> dict[str, Any]:
    """更新单条风险处置。"""
    result = await review_service.dispose_risk(session, risk_id, payload)
    return ok(result)


@router.post("/{review_task_id}/export")
async def export_review(
    review_task_id: int, payload: ExportIn, session: SessionDep
) -> dict[str, Any]:
    """导出审查报告为 docx/pdf 文件（base64），由 Java 落桶 + 预签名下载（契约 §1.5）。"""
    result = await review_service.export(session, review_task_id, payload.format)
    return ok(result)
