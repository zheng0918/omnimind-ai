"""write_tasks / score_points / outline_nodes / sections 数据访问（REQ-WRT / REQ-LINK）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.write import (
    WriteOutlineNode,
    WriteScorePoint,
    WriteSection,
    WriteTask,
)

# ---- write_tasks ----


async def create_task(
    session: AsyncSession,
    *,
    java_task_id: int,
    kb_id: int,
    tender_doc_id: int,
    use_history: bool,
    project_params: dict | None,
) -> WriteTask:
    """新建 EXTRACTING 编写任务并 flush 取得 id。"""
    task = WriteTask(
        java_task_id=java_task_id,
        kb_id=kb_id,
        tender_doc_id=tender_doc_id,
        status="EXTRACTING",
        use_history=use_history,
        project_params_json=project_params,
    )
    session.add(task)
    await session.flush()
    return task


async def get_task(session: AsyncSession, write_task_id: int) -> WriteTask | None:
    """按 id 取编写任务。"""
    return await session.get(WriteTask, write_task_id)


async def update_task(
    session: AsyncSession,
    task: WriteTask,
    *,
    status: str | None = None,
    total_sections: int | None = None,
    done_sections: int | None = None,
    error_msg: str | None = None,
) -> None:
    """更新任务字段（仅非 None 项）。"""
    if status is not None:
        task.status = status
    if total_sections is not None:
        task.total_sections = total_sections
    if done_sections is not None:
        task.done_sections = done_sections
    if error_msg is not None:
        task.error_msg = error_msg
    await session.flush()


async def bump_done_sections(session: AsyncSession, write_task_id: int) -> int:
    """原子自增 done_sections（并发安全），返回最新值。"""
    return int(
        (
            await session.execute(
                update(WriteTask)
                .where(WriteTask.id == write_task_id)
                .values(done_sections=WriteTask.done_sections + 1)
                .returning(WriteTask.done_sections)
            )
        ).scalar_one()
    )


# ---- score_points ----


async def add_score_point(
    session: AsyncSession, *, write_task_id: int, point_text: str, weight: float | None
) -> WriteScorePoint:
    """写入一个评分点并 flush。"""
    point = WriteScorePoint(
        write_task_id=write_task_id, point_text=point_text, weight=weight
    )
    session.add(point)
    await session.flush()
    return point


async def list_score_points(
    session: AsyncSession, write_task_id: int
) -> list[WriteScorePoint]:
    """按 id 升序取评分点。"""
    stmt = (
        select(WriteScorePoint)
        .where(WriteScorePoint.write_task_id == write_task_id)
        .order_by(WriteScorePoint.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def set_score_point_response(
    session: AsyncSession, point: WriteScorePoint, response_status: str
) -> None:
    """更新评分点响应度。"""
    point.response_status = response_status
    await session.flush()


# ---- outline_nodes ----


async def add_outline_node(
    session: AsyncSession,
    *,
    write_task_id: int,
    parent_id: int | None,
    title: str,
    order_idx: int,
) -> WriteOutlineNode:
    """写入一个大纲节点并 flush。"""
    node = WriteOutlineNode(
        write_task_id=write_task_id,
        parent_id=parent_id,
        title=title,
        order_idx=order_idx,
    )
    session.add(node)
    await session.flush()
    return node


async def list_outline(
    session: AsyncSession, write_task_id: int
) -> list[WriteOutlineNode]:
    """按 order_idx, id 升序取大纲节点。"""
    stmt = (
        select(WriteOutlineNode)
        .where(WriteOutlineNode.write_task_id == write_task_id)
        .order_by(WriteOutlineNode.order_idx.asc(), WriteOutlineNode.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def link_section(
    session: AsyncSession, node: WriteOutlineNode, section_id: int
) -> None:
    """大纲节点回填对应正文段落 id。"""
    node.section_id = section_id
    await session.flush()


# ---- sections ----


async def add_section(
    session: AsyncSession, *, write_task_id: int, outline_node_id: int | None
) -> WriteSection:
    """新建 PENDING 正文段落并 flush。"""
    section = WriteSection(
        write_task_id=write_task_id, outline_node_id=outline_node_id, status="PENDING"
    )
    session.add(section)
    await session.flush()
    return section


async def get_section(session: AsyncSession, section_id: int) -> WriteSection | None:
    """按 id 取正文段落。"""
    return await session.get(WriteSection, section_id)


async def list_sections(session: AsyncSession, write_task_id: int) -> list[WriteSection]:
    """按 id 升序取正文段落（创建顺序即文档顺序）。"""
    stmt = (
        select(WriteSection)
        .where(WriteSection.write_task_id == write_task_id)
        .order_by(WriteSection.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def update_section(
    session: AsyncSession,
    section: WriteSection,
    *,
    content_md: str | None = None,
    status: str | None = None,
    ai_model: str | None = None,
    prompt_ver: str | None = None,
    generated_at: datetime | None = None,
) -> None:
    """更新正文段落字段（仅非 None 项）。"""
    if content_md is not None:
        section.content_md = content_md
    if status is not None:
        section.status = status
    if ai_model is not None:
        section.ai_model = ai_model
    if prompt_ver is not None:
        section.prompt_ver = prompt_ver
    if generated_at is not None:
        section.generated_at = generated_at
    await session.flush()
