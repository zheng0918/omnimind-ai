"""文档解析路由（REQ-KB-04）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks

from app.api.deps import ClientsDep, SessionDep, ok
from app.core.errors import CODE_RESOURCE_NOT_FOUND, BizError
from app.core.trace import get_trace_id
from app.schemas.parse import ParseSubmitIn
from app.services import parse_service
from app.workers.parse_worker import run_parse

router = APIRouter(prefix="/ai/v1/parse", tags=["parse"])


@router.post("")
async def submit_parse(
    payload: ParseSubmitIn,
    session: SessionDep,
    clients: ClientsDep,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """登记解析任务并立即返回；解析在后台执行。"""
    result = await parse_service.submit_parse(session, payload)
    # 后台任务在响应返回后执行；此时请求会话已提交，任务记录可见。
    background_tasks.add_task(run_parse, result.parse_task_id, clients, get_trace_id())
    return ok(result)


@router.get("/{parse_task_id}/status")
async def get_parse_status(parse_task_id: int, session: SessionDep) -> dict[str, Any]:
    """查询解析进度。"""
    status = await parse_service.get_status(session, parse_task_id)
    if status is None:
        raise BizError(CODE_RESOURCE_NOT_FOUND, "解析任务不存在")
    return ok(status)
