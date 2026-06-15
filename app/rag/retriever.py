"""混合检索（dense + lexical → RRF → 去重父块 → rerank）。

实现 spec §10.1 第 3~5 步：Milvus 向量检索与 PG 全文检索各取 top50，
用 RRF（k=60）融合子块排名，按父块去重取候选（≤30），再经百炼 rerank 取 top8。
检索命中子块，但回答上下文用父块文本（父子切片：子块召回、父块提供完整语境）。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.registry import Clients
from app.core.config import Settings
from app.repositories import chunk_repo


@dataclass(frozen=True)
class RetrievedBlock:
    """检索得到的父块（含溯源元数据），用于上下文装配与引用。"""

    parent_id: int
    document_id: int
    page: int | None
    paragraph_id: str | None
    text: str
    score: float


def rrf_fuse(ranked_lists: list[list[int]], *, k: int) -> list[int]:
    """RRF 融合多个有序 id 列表，返回按融合得分降序的去重 id 列表。

    标准 RRF：score(d) = Σ 1/(k + rank_i(d))，rank 从 1 起。
    """
    scores: dict[int, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked):
            scores[item_id] += 1.0 / (k + rank + 1)
    return [item_id for item_id, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


async def hybrid_retrieve(
    session: AsyncSession,
    clients: Clients,
    settings: Settings,
    *,
    query: str,
    kb_ids: list[int],
) -> list[RetrievedBlock]:
    """执行混合检索，返回 rerank 后的 top-N 父块。"""
    if not kb_ids:
        return []

    vectors = await clients.embedder.embed([query])
    if not vectors:
        return []
    dense_hits = await clients.vector_store.search(
        vectors[0], top_k=settings.rag_dense_top_k, kb_ids=kb_ids
    )
    dense_ids = [hit.chunk_id for hit in dense_hits]
    lexical_ids = await chunk_repo.lexical_search(
        session, query, kb_ids, settings.rag_lexical_top_k
    )

    fused_child_ids = rrf_fuse([dense_ids, lexical_ids], k=settings.rag_rrf_k)
    if not fused_child_ids:
        return []

    children = await chunk_repo.get_children_by_ids(session, fused_child_ids)
    parent_order: list[int] = []
    seen: set[int] = set()
    for child_id in fused_child_ids:
        child = children.get(child_id)
        if child is None or child.parent_id is None or child.parent_id in seen:
            continue
        seen.add(child.parent_id)
        parent_order.append(child.parent_id)
        if len(parent_order) >= settings.rag_parent_limit:
            break

    parents = await chunk_repo.get_parent_texts(session, parent_order)
    candidates = [parents[pid] for pid in parent_order if pid in parents]
    if not candidates:
        return []

    hits = await clients.reranker.rerank(
        query, [c.text for c in candidates], settings.rag_rerank_top_n
    )
    return [
        RetrievedBlock(
            parent_id=candidates[hit.index].id,
            document_id=candidates[hit.index].document_id,
            page=candidates[hit.index].page,
            paragraph_id=candidates[hit.index].paragraph_id,
            text=candidates[hit.index].text,
            score=hit.score,
        )
        for hit in hits
    ]
