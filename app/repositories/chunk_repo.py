"""chunks 数据访问（父子块）。"""

from __future__ import annotations

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.rag.chunker import ParentChunk


async def persist_chunks(
    session: AsyncSession,
    *,
    document_id: int,
    kb_id: int,
    parents: list[ParentChunk],
    embedding_version: str,
) -> list[Chunk]:
    """插入父块与子块，返回子块 ORM 列表（含 id），供后续向量化与回写 milvus_pk。

    子块标记 embedding_version，作为向量版本依据（新旧并存/灰度/回滚按此过滤）。
    """
    child_rows: list[Chunk] = []
    for parent in parents:
        parent_row = Chunk(
            document_id=document_id,
            kb_id=kb_id,
            parent_id=None,
            level="PARENT",
            text=parent.text,
            page=parent.page,
            paragraph_id=parent.paragraph_id,
            char_offset=parent.char_offset,
            tokens=parent.tokens,
            # 版面坐标存 metadata（无需为可空溯源信息单开列）；检索回填时读出供风险高亮。
            meta={"bbox": parent.bbox} if parent.bbox is not None else {},
        )
        session.add(parent_row)
        await session.flush()
        for child in parent.children:
            child_row = Chunk(
                document_id=document_id,
                kb_id=kb_id,
                parent_id=parent_row.id,
                level="CHILD",
                text=child.text,
                page=parent.page,
                paragraph_id=parent.paragraph_id,
                char_offset=parent.char_offset,
                tokens=child.tokens,
                embedding_ver=embedding_version,
            )
            session.add(child_row)
            child_rows.append(child_row)
    await session.flush()
    return child_rows


async def set_milvus_pks(session: AsyncSession, mapping: dict[int, int]) -> None:
    """批量回写子块的 milvus_pk（chunk_id → milvus_pk）。"""
    for chunk_id, milvus_pk in mapping.items():
        await session.execute(
            update(Chunk).where(Chunk.id == chunk_id).values(milvus_pk=milvus_pk)
        )


async def get_parent_texts(session: AsyncSession, parent_ids: list[int]) -> dict[int, Chunk]:
    """按父块 id 批量取父块（检索回填用）。"""
    if not parent_ids:
        return {}
    stmt = select(Chunk).where(Chunk.id.in_(parent_ids))
    rows = (await session.execute(stmt)).scalars().all()
    return {row.id: row for row in rows}


async def get_children_by_ids(session: AsyncSession, child_ids: list[int]) -> dict[int, Chunk]:
    """按子块 id 批量取子块（检索命中映射用）。"""
    if not child_ids:
        return {}
    stmt = select(Chunk).where(Chunk.id.in_(child_ids))
    rows = (await session.execute(stmt)).scalars().all()
    return {row.id: row for row in rows}


async def lexical_search(
    session: AsyncSession, query: str, kb_ids: list[int], limit: int
) -> list[int]:
    """词法检索：在子块上做全文匹配，返回子块 id（按相关度降序）。"""
    if not kb_ids:
        return []
    tsv = func.to_tsvector("simple", Chunk.text)
    tsq = func.plainto_tsquery("simple", query)
    rank = func.ts_rank(tsv, tsq)
    stmt = (
        select(Chunk.id)
        .where(Chunk.level == "CHILD", Chunk.kb_id.in_(kb_ids), tsv.op("@@")(tsq))
        .order_by(rank.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_document_parents(
    session: AsyncSession, document_id: int, limit: int | None = None
) -> list[Chunk]:
    """取某文档的父块（按 id 升序），用于装配整篇待审文本。"""
    stmt = (
        select(Chunk)
        .where(Chunk.document_id == document_id, Chunk.level == "PARENT")
        .order_by(Chunk.id.asc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def count_by_document(session: AsyncSession, document_id: int) -> int:
    """统计某文档的 chunk 数。"""
    stmt = select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
    return int((await session.execute(stmt)).scalar_one())


async def delete_by_document(session: AsyncSession, document_id: int) -> None:
    """删除某文档的全部 chunk（与 Milvus 删除联动由 service 负责）。"""
    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
