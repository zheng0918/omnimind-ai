"""智能编写编排（REQ-WRT / REQ-LINK）。

create 落库 EXTRACTING 任务并立即返回，准备（评分点+大纲）交后台 worker；章节正文
经 SSE 流由 WriteAgent 驱动生成。状态查询、段落保存、响应度校验、初稿导出为短事务。
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.write_agent import WriteAgent
from app.clients.registry import Clients
from app.core.config import Settings
from app.core.errors import CODE_RESOURCE_NOT_FOUND, BizError
from app.infra import report
from app.infra.sse import SSEEvent
from app.prompts import v1
from app.repositories import write_repo
from app.schemas.common import ExportFileOut
from app.schemas.write import (
    CheckResponseOut,
    DraftExportOut,
    ResponseStatus,
    ScorePointOut,
    ScorePointResponse,
    SectionSaveIn,
    SectionStatus,
    WriteCreateIn,
    WriteCreateOut,
    WriteSectionOut,
    WriteStatus,
    WriteStatusOut,
)

_VALID_RESPONSE = {s.value for s in ResponseStatus}


async def create_write(session: AsyncSession, payload: WriteCreateIn) -> WriteCreateOut:
    """登记编写任务，返回任务 id 与 EXTRACTING 状态。"""
    task = await write_repo.create_task(
        session,
        java_task_id=payload.java_task_id,
        kb_id=payload.kb_id,
        tender_doc_id=payload.tender_doc_id,
        use_history=payload.use_history,
        project_params=payload.project_params.model_dump(),
    )
    logger.info(
        "write task created task={} java_task_id={} kb={} tender_doc={}",
        task.id,
        payload.java_task_id,
        payload.kb_id,
        payload.tender_doc_id,
    )
    return WriteCreateOut(write_task_id=task.id, status=WriteStatus.EXTRACTING)


async def get_status(session: AsyncSession, write_task_id: int) -> WriteStatusOut | None:
    """查询编写任务状态与评分点进度。"""
    task = await write_repo.get_task(session, write_task_id)
    if task is None:
        return None
    points = await write_repo.list_score_points(session, write_task_id)
    return WriteStatusOut(
        write_task_id=task.id,
        status=WriteStatus(task.status),
        total_sections=task.total_sections,
        done_sections=task.done_sections,
        score_points=[
            ScorePointOut(
                point_id=p.id,
                point_text=p.point_text,
                weight=p.weight,
                response_status=ResponseStatus(p.response_status),
            )
            for p in points
        ],
    )


def stream_outline(
    clients: Clients, settings: Settings, *, write_task_id: int
) -> AsyncIterator[SSEEvent]:
    """SSE 驱动大纲流（progress/token{node}/done）。"""
    return WriteAgent(clients, settings).stream_outline(write_task_id=write_task_id)


def stream_section(
    clients: Clients, settings: Settings, *, write_task_id: int, section_id: int
) -> AsyncIterator[SSEEvent]:
    """SSE 驱动单章节正文流式生成（token/done）。"""
    return WriteAgent(clients, settings).stream_section(
        write_task_id=write_task_id, section_id=section_id
    )


async def save_section(
    session: AsyncSession, write_task_id: int, section_id: int, payload: SectionSaveIn
) -> None:
    """保存用户编辑的小节正文，置 USER_EDITED。"""
    section = await write_repo.get_section(session, section_id)
    if section is None or section.write_task_id != write_task_id:
        raise BizError(CODE_RESOURCE_NOT_FOUND, "小节不存在")
    await write_repo.update_section(
        session, section, content_md=payload.content_md, status="USER_EDITED"
    )
    logger.info("write section saved task={} section={}", write_task_id, section_id)


async def get_section(
    session: AsyncSession, write_task_id: int, section_id: int
) -> WriteSectionOut:
    """读取单章节正文与状态（供编辑器加载）；标题取自关联大纲节点。"""
    section = await write_repo.get_section(session, section_id)
    if section is None or section.write_task_id != write_task_id:
        raise BizError(CODE_RESOURCE_NOT_FOUND, "小节不存在")
    title: str | None = None
    if section.outline_node_id is not None:
        for node in await write_repo.list_outline(session, write_task_id):
            if node.id == section.outline_node_id:
                title = node.title
                break
    return WriteSectionOut(
        section_id=section.id,
        title=title,
        content_md=section.content_md,
        status=SectionStatus(section.status),
    )


def _assemble_draft(outline: list, sections_by_id: dict) -> str:
    """按大纲顺序拼接 markdown（章 # / 节 ## + 正文）。"""
    lines: list[str] = []
    for node in outline:
        if node.parent_id is None:
            lines.append(f"# {node.title}")
            continue
        lines.append(f"## {node.title}")
        section = sections_by_id.get(node.section_id) if node.section_id else None
        if section is not None and section.content_md:
            lines.append(section.content_md)
    return "\n\n".join(lines)


async def export_draft(session: AsyncSession, write_task_id: int) -> DraftExportOut:
    """拼接初稿 markdown，供 Java 落 draft document（REQ-LINK-02）。"""
    task = await write_repo.get_task(session, write_task_id)
    if task is None:
        raise BizError(CODE_RESOURCE_NOT_FOUND, "编写任务不存在")
    outline = await write_repo.list_outline(session, write_task_id)
    sections = {s.id: s for s in await write_repo.list_sections(session, write_task_id)}
    logger.info(
        "write draft exported task={} nodes={} sections={}",
        write_task_id,
        len(outline),
        len(sections),
    )
    return DraftExportOut(
        write_task_id=write_task_id, content_md=_assemble_draft(outline, sections)
    )


async def export_file(
    session: AsyncSession, write_task_id: int, fmt: str
) -> ExportFileOut:
    """导出初稿为 docx/pdf 字节（base64），由 Java 落桶 + 预签名（契约 §1.6）。"""
    draft = await export_draft(session, write_task_id)
    blocks = report.markdown_to_blocks(draft.content_md)
    data, content_type, ext = report.render("投标文件初稿", blocks, fmt)
    logger.info("write draft file exported task={} fmt={}", write_task_id, fmt)
    return ExportFileOut(
        filename=f"投标初稿-{write_task_id}.{ext}",
        content_type=content_type,
        content_base64=base64.b64encode(data).decode("ascii"),
    )


async def check_response(
    session: AsyncSession, clients: Clients, write_task_id: int
) -> CheckResponseOut:
    """校验各评分点在初稿中的响应度，落库并返回。"""
    task = await write_repo.get_task(session, write_task_id)
    if task is None:
        raise BizError(CODE_RESOURCE_NOT_FOUND, "编写任务不存在")
    points = await write_repo.list_score_points(session, write_task_id)
    if not points:
        logger.info("write check-response skipped task={} points=0", write_task_id)
        return CheckResponseOut(score_points=[])

    logger.info("write check-response start task={} points={}", write_task_id, len(points))
    outline = await write_repo.list_outline(session, write_task_id)
    sections = {s.id: s for s in await write_repo.list_sections(session, write_task_id)}
    draft = _assemble_draft(outline, sections)

    statuses = await _judge_responses(clients, [p.point_text for p in points], draft)
    results: list[ScorePointResponse] = []
    for idx, point in enumerate(points):
        status = statuses.get(idx, ResponseStatus.NONE)
        await write_repo.set_score_point_response(session, point, status.value)
        results.append(ScorePointResponse(point_id=point.id, response_status=status))
    logger.info(
        "write check-response done task={} judged={}", write_task_id, len(statuses)
    )
    return CheckResponseOut(score_points=results)


async def _judge_responses(
    clients: Clients, point_texts: list[str], draft: str
) -> dict[int, ResponseStatus]:
    """一次 JSON Mode 调用评估全部评分点响应度，返回 {0基序号: 状态}。"""
    try:
        messages = v1.build_response_check_messages(point_texts, draft)
        result = await clients.llm.json_mode(messages, temperature=0.0)
    except Exception:
        logger.exception("response check llm call failed")
        return {}
    statuses: dict[int, ResponseStatus] = {}
    for raw in result.get("results", []):
        try:
            one_based = int(raw.get("index"))
        except (TypeError, ValueError):
            continue
        value = str(raw.get("responseStatus", "")).upper()
        if value in _VALID_RESPONSE:
            statuses[one_based - 1] = ResponseStatus(value)
    return statuses
