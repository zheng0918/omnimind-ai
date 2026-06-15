"""智能编写路由（REQ-WRT / REQ-LINK）。

POST 创建任务并后台准备（评分点+大纲）；GET 状态轮询；章节正文经 SSE 流生成；
PUT 保存用户编辑；check-response 校验响应度；export 导出初稿供 Java 落库。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse

from app.api.deps import ClientsDep, SessionDep, ok
from app.core.config import get_settings
from app.core.errors import CODE_RESOURCE_NOT_FOUND, BizError
from app.core.trace import get_trace_id
from app.infra.sse import SSE_MEDIA_TYPE, stream_events
from app.schemas.write import SectionSaveIn, WriteCreateIn
from app.services import write_service
from app.workers.write_worker import run_write_prepare

router = APIRouter(prefix="/ai/v1/write", tags=["write"])


@router.post("")
async def create_write(
    payload: WriteCreateIn,
    session: SessionDep,
    clients: ClientsDep,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """登记编写任务并立即返回；评分点抽取与大纲规划在后台执行。"""
    result = await write_service.create_write(session, payload)
    background_tasks.add_task(
        run_write_prepare, result.write_task_id, clients, get_trace_id()
    )
    return ok(result)


@router.get("/{write_task_id}")
async def get_write(write_task_id: int, session: SessionDep) -> dict[str, Any]:
    """查询编写任务状态与评分点进度。"""
    status = await write_service.get_status(session, write_task_id)
    if status is None:
        raise BizError(CODE_RESOURCE_NOT_FOUND, "编写任务不存在")
    return ok(status)


@router.get("/{write_task_id}/stream")
async def stream_write(write_task_id: int, clients: ClientsDep) -> StreamingResponse:
    """SSE 流式生成章节正文（progress/token/done/error）。"""
    events = write_service.stream_write(
        clients, get_settings(), write_task_id=write_task_id
    )
    return StreamingResponse(
        stream_events(events),
        media_type=SSE_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.put("/{write_task_id}/sections/{section_id}")
async def save_section(
    write_task_id: int,
    section_id: int,
    payload: SectionSaveIn,
    session: SessionDep,
) -> dict[str, Any]:
    """保存用户编辑的小节正文。"""
    await write_service.save_section(session, write_task_id, section_id, payload)
    return ok()


@router.post("/{write_task_id}/check-response")
async def check_response(
    write_task_id: int, session: SessionDep, clients: ClientsDep
) -> dict[str, Any]:
    """校验各评分点在初稿中的响应度。"""
    result = await write_service.check_response(session, clients, write_task_id)
    return ok(result)


@router.get("/{write_task_id}/export")
async def export_draft(write_task_id: int, session: SessionDep) -> dict[str, Any]:
    """导出初稿 markdown 供 Java 落 draft document。"""
    result = await write_service.export_draft(session, write_task_id)
    return ok(result)
