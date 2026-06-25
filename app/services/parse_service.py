"""解析任务编排（REQ-KB-04）。

submit 仅落库 PENDING 并立即返回，重活交给后台 worker；status 查询读任务表。
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.registry import Clients
from app.repositories import chunk_repo, parse_task_repo
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
    logger.info(
        "parse task created task={} document={} kb={}",
        task.id,
        payload.document_id,
        payload.kb_id,
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


async def cleanup(
    session: AsyncSession, clients: Clients, document_id: int
) -> dict[str, Any]:
    """文档删除联动：清理该文档的 chunks 与 Milvus 向量。

    Java 删除文档时调用（最佳努力）。Milvus 不可用不阻断 chunk 清理，仅告警。
    """
    chunk_count = await chunk_repo.count_by_document(session, document_id)
    await chunk_repo.delete_by_document(session, document_id)
    vector_deleted = True
    try:
        await clients.vector_store.delete_by_doc(document_id)
    except Exception as exc:
        vector_deleted = False
        logger.error(
            "clean milvus vectors failed document={} err={}", document_id, type(exc).__name__
        )
    logger.info(
        "document cleanup done document={} chunks_deleted={} vector_deleted={}",
        document_id,
        chunk_count,
        vector_deleted,
    )
    return {
        "documentId": document_id,
        "chunkDeleted": chunk_count,
        "vectorDeleted": vector_deleted,
    }
