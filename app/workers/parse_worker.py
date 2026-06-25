"""解析后台任务（REQ-KB-04 全链路）。

MinIO 取原文 → 解析器结构化 → 父子切片 → 子块向量化 → 写 PG + Milvus →
任务 PARSED + 回调 Java。解析失败重试 1 次；最终失败置 FAILED 并回调 FAILED。
不向调用方泄露堆栈，仅日志记录 trace 级别信息（不记正文）。
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.milvus_store import VectorRecord
from app.clients.registry import Clients
from app.core.config import Settings, get_settings
from app.core.db import session_scope
from app.core.errors import CODE_PARSE_FAILED, ParseError
from app.core.trace import trace_id_ctx
from app.models.chunk import Chunk
from app.parsers.registry import get_parser
from app.rag.chunker import chunk_document
from app.repositories import chunk_repo, parse_task_repo
from app.schemas.parse import ParsedDocument

_PARSE_MAX_ATTEMPTS = 2  # 首次 + 重试 1 次


async def run_parse(parse_task_id: int, clients: Clients, trace_id: str) -> None:
    """执行解析全链路。供 BackgroundTasks 调度。"""
    trace_id_ctx.set(trace_id)
    settings = get_settings()
    document_id: int | None = None
    logger.info("parse worker start task={}", parse_task_id)
    try:
        async with session_scope() as session:
            task = await parse_task_repo.get(session, parse_task_id)
            if task is None:
                logger.error("parse task not found id={}", parse_task_id)
                return
            document_id = task.document_id
            kb_id = task.kb_id
            minio_key = task.minio_key
            mime_type = task.mime_type or ""
            await parse_task_repo.update_progress(session, task, status="PARSING", progress=10)

        data = await clients.minio.get_object_bytes(minio_key)
        parsed = await _parse_with_retry(mime_type, data, minio_key)

        async with session_scope() as session:
            task = await parse_task_repo.get(session, parse_task_id)
            if task is None:
                logger.error("parse task vanished id={}", parse_task_id)
                return
            child_rows = await _persist_and_index(
                session, clients, settings, document_id, kb_id, parsed
            )
            chunk_count = await chunk_repo.count_by_document(session, document_id)
            await parse_task_repo.update_progress(
                session,
                task,
                status="PARSED",
                progress=100,
                page_count=parsed.page_count,
                chunk_count=chunk_count,
            )
        logger.info(
            "parse success task={} children={} pages={}",
            parse_task_id,
            len(child_rows),
            parsed.page_count,
        )
        await clients.java_callback.notify_parse_done(
            document_id,
            status="PARSED",
            page_count=parsed.page_count,
            chunk_count=chunk_count,
        )
    except Exception as exc:
        await _handle_failure(parse_task_id, document_id, clients, exc)


async def recover_unfinished_parses(clients: Clients) -> None:
    """启动时重跑孤儿解析任务（PENDING/PARSING）。

    BackgroundTasks 进程内调度、重启即丢，故重启后这些任务会永久卡住。
    在此扫描并顺序重跑（run_parse 已幂等：先清旧块/旧向量再入库）。
    顺序执行以免一次性占满 embedding/Milvus 配额。
    """
    trace_id = trace_id_ctx.get() or "recover"
    try:
        async with session_scope() as session:
            tasks = await parse_task_repo.list_unfinished(session)
            task_ids = [t.id for t in tasks]
    except Exception:
        logger.exception("scan unfinished parse tasks failed")
        return
    if not task_ids:
        logger.info("no unfinished parse tasks to recover")
        return
    logger.info("recovering {} unfinished parse tasks: {}", len(task_ids), task_ids)
    for task_id in task_ids:
        try:
            await run_parse(task_id, clients, trace_id)
        except Exception:
            logger.exception("recover parse task failed id={}", task_id)


async def _parse_with_retry(mime_type: str, data: bytes, key: str) -> ParsedDocument:
    parser = get_parser(mime_type, key)
    last_exc: Exception | None = None
    for attempt in range(_PARSE_MAX_ATTEMPTS):
        try:
            return await parser.parse(data)
        except ParseError as exc:
            last_exc = exc
            logger.error("parse attempt {} failed: {}", attempt + 1, exc.message)
    raise last_exc if last_exc is not None else ParseError(CODE_PARSE_FAILED, "解析失败")


async def _persist_and_index(
    session: AsyncSession,
    clients: Clients,
    settings: Settings,
    document_id: int,
    kb_id: int,
    parsed: ParsedDocument,
) -> list[Chunk]:
    # 重入幂等：先清旧块（PG）与旧向量（Milvus），避免重试/恢复重复入库。
    # 首次解析时文档尚无块，删除为空操作，安全。
    await chunk_repo.delete_by_document(session, document_id)
    try:
        await clients.vector_store.delete_by_doc(document_id)
    except Exception as exc:
        logger.error("clear old vectors failed doc={} type={}", document_id, type(exc).__name__)
    parents = chunk_document(
        parsed.paragraphs,
        parent_tokens=settings.chunk_parent_tokens,
        child_tokens=settings.chunk_child_tokens,
        overlap_ratio=settings.chunk_overlap_ratio,
    )
    child_rows = await chunk_repo.persist_chunks(
        session,
        document_id=document_id,
        kb_id=kb_id,
        parents=parents,
        embedding_version=settings.embedding_version,
    )
    if not child_rows:
        return child_rows
    vectors = await clients.embedder.embed([c.text for c in child_rows])
    records = [
        VectorRecord(
            chunk_id=row.id,
            doc_id=document_id,
            kb_id=kb_id,
            tenant_id=row.tenant_id,
            media_type=row.media_type,
            embedding_ver=row.embedding_ver,
            metadata={"page": row.page, "paragraphId": row.paragraph_id},
            embedding=vector,
        )
        for row, vector in zip(child_rows, vectors, strict=True)
    ]
    pks = await clients.vector_store.upsert(records)
    await chunk_repo.set_milvus_pks(
        session, {row.id: pk for row, pk in zip(child_rows, pks, strict=True)}
    )
    return child_rows


async def _handle_failure(
    parse_task_id: int, document_id: int | None, clients: Clients, exc: Exception
) -> None:
    message = exc.message if isinstance(exc, ParseError) else "文档解析失败"
    logger.error("parse failed task={} type={}", parse_task_id, type(exc).__name__)
    try:
        async with session_scope() as session:
            task = await parse_task_repo.get(session, parse_task_id)
            if task is not None:
                await parse_task_repo.update_progress(
                    session, task, status="FAILED", error_msg=message
                )
    except Exception:
        logger.exception("failed to mark parse task FAILED id={}", parse_task_id)
    if document_id is not None:
        try:
            await clients.java_callback.notify_parse_done(
                document_id, status="FAILED", error_msg=message
            )
        except Exception:
            logger.exception("failed to callback Java FAILED doc={}", document_id)
